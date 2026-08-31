from __future__ import annotations

import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from app.cli import build_parser, main
from app.config.settings import Settings
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import StepLog, TaskRecord


def test_cli_help_lists_operator_commands(capsys):
    with pytest.raises(SystemExit) as captured:
        main(["--help"])

    output = capsys.readouterr().out
    assert captured.value.code == 0
    assert "serve" in output
    assert "probe-deepseek" in output
    assert "probe-wechat" in output
    assert "run-task" in output
    assert "verify" in output


def test_serve_accepts_no_browser_for_launcher_health_gate():
    args = build_parser().parse_args(["serve", "--no-browser"])

    assert args.no_browser is True


def test_browser_opens_after_health_endpoint_becomes_available():
    from app import cli

    opened = Event()
    opened_urls: list[str] = []
    attempts = 0

    def becomes_healthy(_: str) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts == 2

    cli.open_browser_when_healthy(
        url="http://127.0.0.1:8000",
        health_url="http://127.0.0.1:8000/health",
        opener=lambda url: (opened_urls.append(url), opened.set()),
        health_checker=becomes_healthy,
        poll_interval_seconds=0.01,
    )

    assert opened.wait(timeout=1)
    assert attempts == 2
    assert opened_urls == ["http://127.0.0.1:8000"]


def test_health_check_bypasses_configured_http_proxy():
    from app import cli

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()

    try:
        assert cli.is_healthy(f"http://127.0.0.1:{server.server_port}/health")
    finally:
        server.shutdown()
        server.server_close()


def test_run_task_prints_step_progress(monkeypatch: pytest.MonkeyPatch, capsys):
    from app import cli

    task = TaskRecord(mode=TaskMode.FIXED_TOPIC, request="写文章", id="task-cli")
    monkeypatch.setattr(
        cli,
        "build_container",
        lambda settings: SimpleNamespace(
            tasks=SimpleNamespace(create=lambda spec: task), workflow=object()
        ),
    )

    async def fake_run(task_id, workflow, *, source_urls=None, progress_observer=None):
        progress_observer(
            "started",
                StepLog(
                    node="research",
                    label="研究权威来源",
                    status="running",
                    started_at=datetime.now().astimezone(),
                ),
        )
        progress_observer(
            "finished",
            StepLog(
                node="research",
                label="研究权威来源",
                status="done",
                started_at=datetime.now().astimezone(),
                message="提炼 3 条事实",
            ),
        )
        return {"status": TaskStatus.FORMATTED, "revision_round": 0}

    monkeypatch.setattr(cli, "run_content_task", fake_run)

    result = asyncio.run(
        cli._run_task(Settings(_env_file=None), "fixed_topic", "写文章", None, None)
    )

    output = capsys.readouterr().out
    assert result == 0, output
    assert "[task-cli] research started（研究权威来源）" in output
    assert "[task-cli] research finished（研究权威来源）：提炼 3 条事实" in output
