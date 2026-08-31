from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.dependencies import get_container
from app.api.uploads import (
    UploadTooLargeError,
    read_upload_limited,
    validate_xlsx_archive,
)
from app.container import ApplicationContainer
from app.services.analytics.importers import import_metrics
from app.services.analytics.metrics import calculate_windows
from app.services.analytics.quality import build_quality_report

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.post("/import")
async def import_metrics_file(
    file: UploadFile = File(...),
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    suffix = (Path(file.filename or "metrics.csv").suffix or ".csv").lower()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "仅支持 CSV 或 XLSX 文件")
    try:
        body = await read_upload_limited(
            file,
            max_bytes=container.settings.metrics_upload_max_bytes,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    if suffix == ".xlsx":
        try:
            validate_xlsx_archive(body)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    temporary_path: str | None = None
    try:
        with NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(body)
            temporary_path = temporary.name
        imported = import_metrics(Path(temporary_path), container.settings.business_timezone)
        inserted = container.metrics.insert(imported.records)
        all_records = container.metrics.list()
        reference = datetime.now(container.settings.timezone)
        quality = build_quality_report(all_records, now=reference)
        windows = calculate_windows(all_records, as_of=reference)
        container.artifacts.write_json(
            "analytics",
            "data_quality_report",
            quality.model_dump(mode="json"),
        )
        container.artifacts.write_json(
            "analytics",
            "metrics_windows",
            {key: value.model_dump(mode="json") for key, value in windows.items()},
        )
        return {
            "imported": inserted,
            "parsed": len(imported.records),
            "field_mapping": imported.field_mapping,
            "quality": quality,
            "windows": windows,
        }
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


@router.get("/overview")
def analytics_overview(
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    records = container.metrics.list()
    reference = datetime.now(container.settings.timezone)
    return {
        "quality": build_quality_report(records, now=reference),
        "windows": calculate_windows(records, as_of=reference),
    }
