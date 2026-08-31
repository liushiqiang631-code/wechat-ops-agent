from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.enums import EvidenceType
from app.domain.models import CapabilityReport
from app.services.wechat.capability_probe import CapabilityProbe

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

PROBE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x89\x89\x9b"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@router.post("/probe", response_model=CapabilityReport)
async def probe_capabilities(
    container: ApplicationContainer = Depends(get_container),
) -> CapabilityReport:
    probe = CapabilityProbe(
        account_name=container.settings.wechat_account_name,
        app_id=container.settings.wechat_app_id,
        token_manager=container.token_manager,
        analytics=container.wechat_analytics,
        media=container.media,
        drafts=container.drafts,
        evidence_type=EvidenceType.REAL,
    )
    path: str | None = None
    try:
        with NamedTemporaryFile(suffix=".png", delete=False) as image:
            image.write(PROBE_PNG)
            path = image.name
        report = await probe.run(
            image_path=Path(path),
            enable_draft_probe=container.settings.wechat_draft_enabled,
        )
        container.artifacts.write_json(
            "capabilities",
            "capability_report",
            report.model_dump(mode="json"),
        )
        return report
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
