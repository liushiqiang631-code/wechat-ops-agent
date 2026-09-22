from __future__ import annotations

import ast
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[2]


def test_all_python_sources_parse_and_no_formal_publish_endpoint_exists():
    source_text = []
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        ast.parse(text, filename=str(path))
        source_text.append(text)
    combined = "\n".join(source_text)

    assert "/cgi-bin/message/mass/send" not in combined
    assert "/cgi-bin/freepublish/submit" not in combined
    assert "auto_publish: bool = True" not in combined


def test_text_sources_contain_no_real_secret_shapes():
    secret = re.compile(r"\bsk-[0-9a-fA-F]{24,}\b")
    candidates = [
        *ROOT.glob("*.toml"),
        *ROOT.glob("*.yml"),
        *ROOT.glob("*.yaml"),
        *ROOT.glob("*.md"),
        *ROOT.glob(".env.example"),
        *(ROOT / "app").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
    ]

    leaks = [
        str(path.relative_to(ROOT))
        for path in candidates
        if path.is_file() and secret.search(path.read_text(encoding="utf-8"))
    ]

    assert leaks == []


def test_alembic_initial_migration_builds_core_tables(tmp_path: Path):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration.db'}")

    command.upgrade(config, "head")

    from sqlalchemy import create_engine

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    table_names = set(inspect(engine).get_table_names())
    assert {
        "content_tasks",
        "draft_receipts",
        "publication_records",
        "raw_metrics",
        "capability_reports",
    } <= table_names


def test_deployment_files_never_bake_credentials():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY=" not in dockerfile
    assert "WECHAT_APP_SECRET=" not in dockerfile
    assert "env_file:" in compose
    assert compose.startswith("name: wechat-ops-agent")
    assert "replace_with" in env_example


def test_docker_context_excludes_local_secrets_and_runtime_state():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert ".venv/" in ignored
    assert ".git/" in ignored
    assert "outputs/" in ignored


def test_windows_launcher_is_cmd_safe_and_waits_for_health():
    launcher = (ROOT / "启动.bat").read_bytes()

    assert launcher.isascii()
    text = launcher.decode("ascii").lower()
    # The launcher runs on the system Python via the py launcher; it must not
    # depend on a project-local virtual environment.
    assert ".venv" not in text
    assert "py -3.13" in text
    assert "@('-m','app.cli','serve'" in text
    # The CLI owns health polling and opens the browser only after /health responds.
    assert "--no-browser" not in text
    assert "start \"\" \"http://127.0.0.1:%port%\"" in text
    assert "runtime\\wechat-ops.pid" in text

    stopper = (ROOT / "停止服务.bat").read_bytes()
    assert stopper.isascii()
    stop_text = stopper.decode("ascii").lower()
    assert "runtime\\wechat-ops.pid" in stop_text
    assert "app\\.cli\\s+serve" in stop_text
    assert "taskkill" not in stop_text
