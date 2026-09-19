from __future__ import annotations

import os
from datetime import datetime, timedelta
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
from app.domain.models import MetricRecord
from app.services.analytics.importers import import_metrics
from app.services.analytics.metrics import calculate_windows
from app.services.analytics.quality import build_quality_report

router = APIRouter(prefix="/metrics", tags=["metrics"])

# 虚构演示数据：标题与数值均为虚构，仅用于本地体验控制台，
# 日期在导入时按“今天”回推生成。真实运营请导入自己的后台导出文件。
DEMO_ARTICLES: tuple[tuple[str, int, int, int, int], ...] = (
    # (标题, 日阅读基数, 日阅读波动, 分享基数, 关注基数)
    ("AI 工作流入门：从零搭建第一支数字员工", 1420, 420, 96, 24),
    ("效率工具清单：这 8 个应用帮我每周省 10 小时", 1180, 380, 88, 19),
    ("自动化写作实践：让 Agent 成为你的初稿搭档", 960, 300, 64, 15),
    ("数据驱动选题：用后台指标决定下一篇写什么", 810, 260, 52, 12),
    ("个人知识库搭建：把碎片信息变成创作素材", 700, 220, 47, 11),
)


def build_demo_records(reference: datetime) -> list[MetricRecord]:
    """生成确定性的虚构指标（14 天 × 5 篇文章），日期相对“今天”。

    metric_date 取业务时区当日零点，保证同一天重复导入可被幂等去重。
    """
    records: list[MetricRecord] = []
    for offset in range(13, -1, -1):
        day = (reference - timedelta(days=offset)).date()
        stamped = datetime(day.year, day.month, day.day, tzinfo=reference.tzinfo)
        for index, (title, base, swing, shares, followers) in enumerate(DEMO_ARTICLES):
            wave = ((offset * 7 + index * 13) % 11) - 5
            reads = max(base + swing * (wave // 2), 120)
            records.append(
                MetricRecord(
                    metric_date=stamped,
                    article_id=f"demo-article-{index + 1}",
                    article_title=f"【虚构示例】{title}",
                    reads=reads,
                    shares=max(shares + wave * 3, 0),
                    favorites=max(shares // 2 + wave * 2, 0),
                    followers_gained=max(followers + wave, 0),
                    source_type="manual",
                    source_record_id=f"demo-{index + 1}-{day.isoformat()}",
                )
            )
    return records


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


@router.post("/import-demo")
def import_demo_metrics(
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    """一键导入虚构示例数据（标题均已标注【虚构示例】），便于本地体验控制台。"""
    reference = datetime.now(container.settings.timezone)
    inserted = container.metrics.insert(build_demo_records(reference))
    all_records = container.metrics.list()
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
        "demo": True,
        "windows": windows,
    }


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
