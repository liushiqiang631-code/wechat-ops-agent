from __future__ import annotations

from pathlib import Path

import pytest

from app.config.env_file import format_env_value, update_env_file
from app.config.settings import Settings


def test_format_env_value_quotes_only_when_needed():
    assert format_env_value("") == ""
    assert format_env_value("wx123abc") == "wx123abc"
    assert format_env_value("我的 号") == '"我的 号"'
    assert format_env_value('含"引号') == '"含\\"引号"'
    assert format_env_value(" 前后空格 ") == '" 前后空格 "'


@pytest.mark.parametrize("value", ["line\nnext", "line\rnext", "value\x00tail"])
def test_format_env_value_rejects_control_characters(value: str):
    with pytest.raises(ValueError, match="CR, LF, or NUL"):
        format_env_value(value)


def test_update_env_file_creates_file_when_missing(tmp_path: Path):
    target = tmp_path / ".env"

    update_env_file(target, {"WECHAT_APP_ID": "wx123", "WECHAT_DRAFT_ENABLED": "false"})

    content = target.read_text(encoding="utf-8")
    assert "WECHAT_APP_ID=wx123" in content
    assert "WECHAT_DRAFT_ENABLED=false" in content


def test_update_env_file_updates_in_place_and_keeps_comments(tmp_path: Path):
    target = tmp_path / ".env"
    target.write_text(
        "# Application\n"
        "APP_ENV=development\n"
        "# WeChat Official Account\n"
        "WECHAT_ACCOUNT_NAME=\n"
        "WECHAT_APP_ID=old_id\n"
        "DEEPSEEK_API_KEY=keep-me\n",
        encoding="utf-8",
    )

    update_env_file(
        target,
        {
            "WECHAT_ACCOUNT_NAME": "我的号",
            "WECHAT_APP_ID": "wx-new",
            "WECHAT_DRAFT_ENABLED": "true",
        },
    )

    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Application"
    assert lines[1] == "APP_ENV=development"
    assert lines[2] == "# WeChat Official Account"
    assert "WECHAT_ACCOUNT_NAME=我的号" in lines
    assert "WECHAT_APP_ID=wx-new" in lines
    assert "DEEPSEEK_API_KEY=keep-me" in lines
    assert "WECHAT_DRAFT_ENABLED=true" in lines


def test_update_env_file_updates_every_duplicate_key(tmp_path: Path):
    target = tmp_path / ".env"
    target.write_text("WECHAT_APP_ID=first\nWECHAT_APP_ID=second\n", encoding="utf-8")

    update_env_file(target, {"WECHAT_APP_ID": "wx-new"})

    assert target.read_text(encoding="utf-8").splitlines() == [
        "WECHAT_APP_ID=wx-new",
        "WECHAT_APP_ID=wx-new",
    ]


def test_update_env_file_replaces_existing_file_atomically(tmp_path: Path):
    target = tmp_path / ".env"
    target.write_text("WECHAT_APP_ID=old\n", encoding="utf-8")

    update_env_file(target, {"WECHAT_APP_ID": "wx-new"})

    assert target.read_text(encoding="utf-8") == "WECHAT_APP_ID=wx-new\n"
    assert list(tmp_path.glob("..env.*.tmp")) == []


def test_update_env_file_result_round_trips_through_settings(tmp_path: Path):
    target = tmp_path / ".env"

    update_env_file(
        target,
        {
            "WECHAT_ACCOUNT_NAME": "科技充电站",
            "WECHAT_APP_ID": "wx1234567890abcdef",
            "WECHAT_APP_SECRET": "secret with spaces",
            "WECHAT_ORIGINAL_ID": "gh_abc123",
            "WECHAT_DRAFT_ENABLED": "true",
        },
    )

    settings = Settings(_env_file=target, _env_file_encoding="utf-8")
    assert settings.wechat_account_name == "科技充电站"
    assert settings.wechat_app_id == "wx1234567890abcdef"
    assert settings.wechat_app_secret is not None
    assert settings.wechat_app_secret.get_secret_value() == "secret with spaces"
    assert settings.wechat_original_id == "gh_abc123"
    assert settings.wechat_draft_enabled is True
