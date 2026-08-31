from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from app.config.settings import reset_settings_cache


@pytest.fixture
def tmp_path():
    """Create a disposable test directory without Windows symlink support.

    Pytest's built-in ``tmp_path`` fixture maintains a ``*-current`` symbolic
    link. The local Windows environment does not grant that privilege. Honour
    ``PYTEST_DEBUG_TEMPROOT`` when supplied so slower workspace volumes do not
    block SQLite schema setup; otherwise keep the workspace-local fallback.
    """
    configured_root = os.environ.get("PYTEST_DEBUG_TEMPROOT")
    root = (
        Path(configured_root)
        if configured_root
        else Path(__file__).resolve().parents[1] / ".pytest-local"
    )
    root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="case-", dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("OBJECT_STORAGE_PATH", str(tmp_path / "outputs"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("WECHAT_APP_SECRET", raising=False)
    # app.main primes get_settings() from the real .env at import time; clear the
    # cache so this test uses the isolated env vars instead of the project DB.
    reset_settings_cache()
    yield
    reset_settings_cache()
