from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # 把接口写入的 .env 重定向到临时目录，避免覆盖仓库根目录的真实 .env；
    # 工作目录保持不变，否则 Jinja 模板的相对路径会失效。
    monkeypatch.setattr("app.api.settings._env_file_path", lambda: tmp_path / ".env")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'settings.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)
    return TestClient(create_app(settings, container))


def test_save_wechat_settings_writes_env_and_applies_at_runtime(
    tmp_path: Path, client: TestClient
):
    response = client.post(
        "/api/v1/settings/wechat",
        json={
            "account_name": "科技充电站",
            "app_id": "wx1234567890abcdef",
            "app_secret": "wx-secret-value",
            "original_id": "gh_abc123",
            "draft_enabled": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["wechat"]["configured"] is True
    assert payload["wechat"]["draft_enabled"] is True
    # 密钥绝不回显
    assert "wx-secret-value" not in response.text

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "WECHAT_APP_ID=wx1234567890abcdef" in env_text
    assert "WECHAT_APP_SECRET=wx-secret-value" in env_text
    assert "WECHAT_ORIGINAL_ID=gh_abc123" in env_text
    assert "WECHAT_DRAFT_ENABLED=true" in env_text

    container = client.app.state.container
    assert container.settings.wechat_account_name == "科技充电站"
    assert container.settings.wechat_app_id == "wx1234567890abcdef"
    assert container.settings.wechat_app_secret is not None
    assert container.settings.wechat_draft_enabled is True


def test_empty_secret_keeps_existing_value(tmp_path: Path, client: TestClient):
    container = client.app.state.container
    first = client.post(
        "/api/v1/settings/wechat",
        json={
            "account_name": "账号",
            "app_id": "wx-existing",
            "app_secret": "real-secret",
            "original_id": "",
            "draft_enabled": False,
        },
    )
    assert first.status_code == 200

    # 再次保存但密钥留空：.env 不应被覆盖为空，运行时保留原密钥
    second = client.post(
        "/api/v1/settings/wechat",
        json={
            "account_name": "账号二",
            "app_id": "wx-existing",
            "app_secret": "",
            "original_id": "",
            "draft_enabled": False,
        },
    )

    assert second.status_code == 200
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "WECHAT_APP_SECRET=real-secret" in env_text
    assert container.settings.wechat_app_secret is not None
    assert container.settings.wechat_app_secret.get_secret_value() == "real-secret"


def test_save_invalidates_cached_token(tmp_path: Path, client: TestClient):
    container = client.app.state.container
    container.token_manager._token = "stale-token"  # noqa: S105 - cache sentinel

    response = client.post(
        "/api/v1/settings/wechat",
        json={
            "account_name": "账号",
            "app_id": "wx-new",
            "app_secret": "new-secret",
            "original_id": "",
            "draft_enabled": False,
        },
    )

    assert response.status_code == 200
    assert container.token_manager._token is None


@pytest.mark.parametrize("field", ["account_name", "app_id", "app_secret", "original_id"])
def test_save_rejects_env_injection_without_writing_file(
    field: str, tmp_path: Path, client: TestClient
):
    payload = {
        "account_name": "账号",
        "app_id": "wx-existing",
        "app_secret": "real-secret",
        "original_id": "gh_existing",
        "draft_enabled": False,
    }
    payload[field] = "valid\nDEEPSEEK_API_KEY=attacker-value"

    response = client.post("/api/v1/settings/wechat", json=payload)

    assert response.status_code == 422
    assert not (tmp_path / ".env").exists()


def test_settings_page_renders_form_without_secret(tmp_path: Path, client: TestClient):
    client.post(
        "/api/v1/settings/wechat",
        json={
            "account_name": "科技充电站",
            "app_id": "wx1234567890abcdef",
            "app_secret": "wx-secret-value",
            "original_id": "gh_abc123",
            "draft_enabled": False,
        },
    )

    page = client.get("/settings")

    assert page.status_code == 200
    assert 'id="wechat-settings-form"' in page.text
    assert 'value="科技充电站"' in page.text
    assert 'value="wx1234567890abcdef"' in page.text
    # 密钥不回显，只提示已保存
    assert "wx-secret-value" not in page.text
    assert "已保存，留空保持不变" in page.text
