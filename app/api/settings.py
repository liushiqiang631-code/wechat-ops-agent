from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr, field_validator

from app.api.dependencies import get_container
from app.config.env_file import update_env_file
from app.container import ApplicationContainer

router = APIRouter(prefix="/settings", tags=["settings"])


class WeChatSettingsUpdate(BaseModel):
    account_name: str = Field(default="", max_length=60)
    app_id: str = Field(default="", max_length=64)
    # 留空表示保持已保存的密钥不变；明文只在保存瞬间出现，接口不回显。
    app_secret: str = Field(default="", max_length=256)
    original_id: str = Field(default="", max_length=64)
    draft_enabled: bool = False

    @field_validator("account_name", "app_id", "app_secret", "original_id")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(char in value for char in ("\r", "\n", "\x00")):
            raise ValueError("配置值不能包含换行符或空字符")
        return value


@router.post("/wechat")
def save_wechat_settings(
    payload: WeChatSettingsUpdate,
    container: ApplicationContainer = Depends(get_container),
) -> dict[str, object]:
    """保存公众号连接配置：写入本机 .env 并即时生效，不重启进程。"""
    settings = container.settings
    account_name = payload.account_name.strip()
    app_id = payload.app_id.strip()
    app_secret = payload.app_secret
    original_id = payload.original_id.strip()

    updates = {
        "WECHAT_ACCOUNT_NAME": account_name,
        "WECHAT_APP_ID": app_id,
        "WECHAT_ORIGINAL_ID": original_id,
        "WECHAT_DRAFT_ENABLED": "true" if payload.draft_enabled else "false",
    }
    if app_secret.strip():
        updates["WECHAT_APP_SECRET"] = app_secret
    update_env_file(container.settings_file or _env_file_path(), updates)

    settings.wechat_account_name = account_name
    settings.wechat_app_id = app_id or None
    settings.wechat_original_id = original_id or None
    settings.wechat_draft_enabled = payload.draft_enabled
    if app_secret.strip():
        settings.wechat_app_secret = SecretStr(app_secret)
    container.token_manager.invalidate()

    return {
        "ok": True,
        "wechat": {
            "account": settings.wechat_account_name,
            "configured": bool(settings.wechat_app_id and settings.wechat_app_secret),
            "draft_enabled": settings.wechat_draft_enabled,
        },
    }


def _env_file_path() -> Path:
    # Settings 通过 env_file=".env"（相对当前工作目录）加载，这里保持一致。
    return Path.cwd() / ".env"
