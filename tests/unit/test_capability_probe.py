from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.enums import EvidenceType, ProbeStatus
from app.services.wechat.capability_probe import CapabilityProbe
from app.services.wechat.client import WeChatAPIError


class FakeToken:
    async def get(self):
        return "token"


class FakeAnalytics:
    async def probe_user(self, token):
        return {"list": []}

    async def probe_article(self, token):
        raise WeChatAPIError(48001, "unauthorized")


class FakeMedia:
    async def upload_inline(self, token, path):
        return "https://mmbiz.qpic.cn/probe.png"

    async def upload_cover(self, token, path):
        return "thumb-1"


class FakeDraft:
    async def create(self, token, article):
        return "draft-1"


@pytest.mark.asyncio
async def test_probe_records_success_no_data_and_permission_without_faking(
    tmp_path: Path,
):
    image = tmp_path / "probe.png"
    image.write_bytes(b"probe")
    probe = CapabilityProbe(
        account_name="示例技术观察站",
        app_id="wx123456",
        token_manager=FakeToken(),
        analytics=FakeAnalytics(),
        media=FakeMedia(),
        drafts=FakeDraft(),
        evidence_type=EvidenceType.MOCK,
    )

    report = await probe.run(image_path=image, enable_draft_probe=True)
    checks = {check.name: check for check in report.checks}

    assert checks["access_token"].status == ProbeStatus.AVAILABLE
    assert checks["user_analytics"].status == ProbeStatus.NO_DATA
    assert checks["article_analytics"].status == ProbeStatus.BLOCKED
    assert checks["article_analytics"].error_code == 48001
    assert checks["draft_add"].status == ProbeStatus.AVAILABLE
    assert all(check.evidence_type == EvidenceType.MOCK for check in report.checks)


class BlockedToken:
    async def get(self):
        raise WeChatAPIError(40164, "ip not in whitelist")


@pytest.mark.asyncio
async def test_token_block_marks_dependent_checks_not_run(tmp_path: Path):
    image = tmp_path / "probe.png"
    image.write_bytes(b"probe")
    probe = CapabilityProbe(
        account_name="示例技术观察站",
        app_id="wx123456",
        token_manager=BlockedToken(),
        analytics=FakeAnalytics(),
        media=FakeMedia(),
        drafts=FakeDraft(),
        evidence_type=EvidenceType.REAL,
    )

    report = await probe.run(image_path=image, enable_draft_probe=True)

    assert report.checks[0].status == ProbeStatus.BLOCKED
    assert all(check.status == ProbeStatus.NOT_RUN for check in report.checks[1:])
    assert any("IP 白名单" in step for step in report.next_steps)
