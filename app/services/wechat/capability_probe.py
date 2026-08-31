from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from app.domain.enums import EvidenceType, ProbeStatus
from app.domain.models import CapabilityCheck, CapabilityReport
from app.services.wechat.client import WeChatAPIError


class CapabilityProbe:
    check_order = (
        "access_token",
        "inline_image_upload",
        "cover_upload",
        "user_analytics",
        "article_analytics",
        "draft_add",
    )

    def __init__(
        self,
        *,
        account_name: str,
        app_id: str | None,
        token_manager,
        analytics,
        media,
        drafts,
        evidence_type: EvidenceType,
    ):
        self.account_name = account_name
        self.app_id = app_id
        self.token_manager = token_manager
        self.analytics = analytics
        self.media = media
        self.drafts = drafts
        self.evidence_type = evidence_type

    def _check(
        self,
        name: str,
        status: ProbeStatus,
        message: str,
        *,
        error: WeChatAPIError | None = None,
        details: dict | None = None,
    ) -> CapabilityCheck:
        return CapabilityCheck(
            name=name,
            status=status,
            evidence_type=self.evidence_type,
            error_code=error.code if error else None,
            message=message,
            details=details or {},
        )

    @staticmethod
    def _status_for_error(error: WeChatAPIError) -> ProbeStatus:
        if error.category in {"ip_whitelist", "no_permission", "invalid_app_id"}:
            return ProbeStatus.BLOCKED
        if error.category == "wechat_error":
            return ProbeStatus.UNSUPPORTED
        return ProbeStatus.ERROR

    async def _call(
        self, name: str, operation: Callable[[], Awaitable[object]]
    ) -> tuple[CapabilityCheck, object | None]:
        try:
            result = await operation()
        except WeChatAPIError as error:
            return (
                self._check(
                    name,
                    self._status_for_error(error),
                    error.operator_action,
                    error=error,
                ),
                None,
            )
        no_data = isinstance(result, dict) and not result.get("list")
        status = ProbeStatus.NO_DATA if no_data else ProbeStatus.AVAILABLE
        message = "接口可用但当前窗口无数据" if no_data else "接口调用成功"
        return self._check(name, status, message), result

    async def run(self, *, image_path: Path, enable_draft_probe: bool = False) -> CapabilityReport:
        checks: list[CapabilityCheck] = []
        next_steps: list[str] = []
        try:
            token = await self.token_manager.get()
            checks.append(self._check("access_token", ProbeStatus.AVAILABLE, "Token 获取成功"))
        except (WeChatAPIError, RuntimeError) as error:
            if isinstance(error, WeChatAPIError):
                checks.append(
                    self._check(
                        "access_token",
                        self._status_for_error(error),
                        error.operator_action,
                        error=error,
                    )
                )
                if error.category == "ip_whitelist":
                    next_steps.append("将当前服务器出口 IP 加入微信公众号 API IP 白名单")
            else:
                # Missing/empty credentials raise a plain RuntimeError; surface it
                # as a blocked check instead of a 500.
                checks.append(
                    self._check("access_token", ProbeStatus.BLOCKED, str(error))
                )
                next_steps.append("在 .env 中配置 WECHAT_APP_ID 与 WECHAT_APP_SECRET 后重试")
            checks.extend(
                self._check(name, ProbeStatus.NOT_RUN, "依赖 access_token，未执行")
                for name in self.check_order[1:]
            )
            return CapabilityReport(
                account_name=self.account_name,
                account_app_id_suffix=self.app_id[-6:] if self.app_id else None,
                checks=checks,
                limitations=["access_token 能力未通过，依赖接口未执行"],
                next_steps=next_steps,
            )

        inline_check, _ = await self._call(
            "inline_image_upload", lambda: self.media.upload_inline(token, image_path)
        )
        checks.append(inline_check)
        cover_check, thumb = await self._call(
            "cover_upload", lambda: self.media.upload_cover(token, image_path)
        )
        checks.append(cover_check)
        user_check, _ = await self._call("user_analytics", lambda: self.analytics.probe_user(token))
        checks.append(user_check)
        article_check, _ = await self._call(
            "article_analytics", lambda: self.analytics.probe_article(token)
        )
        checks.append(article_check)

        if not enable_draft_probe:
            checks.append(self._check("draft_add", ProbeStatus.NOT_RUN, "草稿探针安全开关未启用"))
        elif thumb is None:
            checks.append(self._check("draft_add", ProbeStatus.NOT_RUN, "封面素材上传未成功"))
        else:
            article = {
                "title": "接口测试，请勿发布",
                "author": self.account_name,
                "digest": "微信公众号运营 Agent V0 能力验证",
                "content": "<p>接口测试，请勿发布。</p>",
                "thumb_media_id": thumb,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
            draft_check, _ = await self._call(
                "draft_add", lambda: self.drafts.create(token, article)
            )
            checks.append(draft_check)

        blocked = [check for check in checks if check.status == ProbeStatus.BLOCKED]
        if blocked:
            next_steps.append("按 capability_report 中的错误码检查账号认证、权限与白名单")
        return CapabilityReport(
            account_name=self.account_name,
            account_app_id_suffix=self.app_id[-6:] if self.app_id else None,
            checks=checks,
            limitations=[
                "微信接口能力会随账号类型、认证状态和平台规则变化",
                "Mock 结果不能替代真实账号验收",
            ],
            next_steps=next_steps,
        )
