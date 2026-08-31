from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.main import create_app


def test_health_endpoint_exposes_safe_service_metadata(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'health.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    client = TestClient(create_app(settings, build_container(settings)))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["model"]["provider"] == "deepseek"
    assert payload["model"]["name"] == "deepseek-v4-pro"
    assert "api_key" not in response.text.lower()
    assert "app_secret" not in response.text.lower()
