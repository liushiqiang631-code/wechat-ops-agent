from __future__ import annotations

import argparse
import asyncio
import json
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Thread
from time import sleep

import uvicorn

from app.config.settings import Settings
from app.container import build_container
from app.db.migrations import run_migrations
from app.domain.enums import EvidenceType, TaskMode, TaskStatus
from app.domain.models import TaskSpec
from app.services.wechat.capability_probe import CapabilityProbe
from app.workflows.graph import run_content_task

PROBE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x89\x89\x9b"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
LOCAL_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def _probe_deepseek(settings: Settings) -> int:
    report_path = settings.object_storage_path / "capabilities" / "deepseek_report.json"
    try:
        report = await build_container(settings).deepseek.health_probe()
        report["evidence_type"] = "real"
        _write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["available"] else 2
    except Exception as error:
        report = {
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "available": False,
            "evidence_type": "real",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        _write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


async def _probe_wechat(settings: Settings, enable_draft_probe: bool) -> int:
    container = build_container(settings)
    probe = CapabilityProbe(
        account_name=settings.wechat_account_name,
        app_id=settings.wechat_app_id,
        token_manager=container.token_manager,
        analytics=container.wechat_analytics,
        media=container.media,
        drafts=container.drafts,
        evidence_type=EvidenceType.REAL,
    )
    probe_path = settings.object_storage_path / "capabilities" / "wechat_probe.png"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_bytes(PROBE_PNG)
    report = await probe.run(
        image_path=probe_path,
        enable_draft_probe=enable_draft_probe,
    )
    report_path = settings.object_storage_path / "capabilities" / "capability_report.json"
    _write_json(report_path, report.model_dump(mode="json"))
    print(report.model_dump_json(indent=2))
    return 0 if report.checks[0].status.value == "available" else 2


async def _run_task(
    settings: Settings,
    mode: str,
    request: str,
    topic: str | None,
    source_urls: list[str] | None,
) -> int:
    container = build_container(settings)
    task = container.tasks.create(TaskSpec(mode=TaskMode(mode), request=request, topic=topic))

    def show_progress(event, step) -> None:
        suffix = f"：{step.message}" if step.message else ""
        print(f"[{task.id}] {step.node} {event}（{step.label}）{suffix}", flush=True)

    try:
        result = await run_content_task(
            task.id,
            container.workflow,
            source_urls=source_urls,
            progress_observer=show_progress,
        )
    except Exception as error:
        failed = {
            "task_id": task.id,
            "status": TaskStatus.FAILED.value,
            "error": f"{type(error).__name__}: {error}",
            "artifact_directory": str(settings.object_storage_path / task.id),
        }
        print(json.dumps(failed, ensure_ascii=False, indent=2))
        return 2
    safe = {
        "task_id": task.id,
        "status": result["status"].value,
        "revision_round": result["revision_round"],
        "artifact_directory": str(settings.object_storage_path / task.id),
    }
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0 if result["status"].value in {"FORMATTED", "NEEDS_HUMAN"} else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wechat-ops",
        description="微信公众号数据驱动运营 Agent 运维命令",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="启动本地运营控制台")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    reload_group = serve.add_mutually_exclusive_group()
    reload_group.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=None,
        help="启用开发自动重载（容器内请使用 --no-reload）",
    )
    reload_group.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="禁用自动重载",
    )
    serve.add_argument(
        "--no-browser",
        action="store_true",
        help="不由服务进程在就绪后打开浏览器",
    )

    subparsers.add_parser("probe-deepseek", help="真实验证 DeepSeek V4 Pro")

    wechat = subparsers.add_parser("probe-wechat", help="真实验证微信公众号接口能力")
    wechat.add_argument(
        "--enable-draft-probe",
        action="store_true",
        help="创建标题为“接口测试，请勿发布”的测试草稿",
    )

    task = subparsers.add_parser("run-task", help="运行一次内容工作流")
    task.add_argument("--mode", choices=[mode.value for mode in TaskMode], default="fixed_topic")
    task.add_argument("--request", required=True)
    task.add_argument("--topic")
    task.add_argument(
        "--source",
        action="append",
        dest="source_urls",
        metavar="URL",
        help="研究阶段使用的官方来源（可重复指定，默认使用内置官方来源）",
    )

    subparsers.add_parser("verify", help="执行完整发布验收")
    return parser


def is_healthy(health_url: str) -> bool:
    try:
        with LOCAL_HTTP_OPENER.open(health_url, timeout=1) as response:  # noqa: S310
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def open_browser_when_healthy(
    *,
    url: str,
    health_url: str,
    opener: Callable[[str], object] = webbrowser.open,
    health_checker: Callable[[str], bool] = is_healthy,
    poll_interval_seconds: float = 1,
) -> None:
    """Open the local console once the server health endpoint responds successfully."""

    def wait_for_health() -> None:
        while True:
            if health_checker(health_url):
                opener(url)
                return

            sleep(poll_interval_seconds)

    Thread(target=wait_for_health, name="open-ops-console", daemon=True).start()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "serve":
        run_migrations(settings.database_url)
        scheduler = None
        if settings.scheduler_enabled:
            from app.container import build_container
            from app.scheduler.jobs import build_scheduler

            scheduler = build_scheduler(build_container(settings))
            scheduler.start()
            print("[SCHEDULER] 调度已启动：每日指标审计 + 每周内容计划", flush=True)
        reload_enabled = (settings.app_env == "development") if args.reload is None else args.reload
        host = args.host or settings.app_host
        port = args.port or settings.app_port
        if not args.no_browser:
            browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host  # noqa: S104
            open_browser_when_healthy(
                url=f"http://{browser_host}:{port}",
                health_url=f"http://127.0.0.1:{port}/health",
            )
        try:
            uvicorn.run(
                "app.main:app",
                host=host,
                port=port,
                reload=reload_enabled,
            )
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
        return 0
    if args.command == "probe-deepseek":
        return asyncio.run(_probe_deepseek(settings))
    if args.command == "probe-wechat":
        return asyncio.run(_probe_wechat(settings, args.enable_draft_probe))
    if args.command == "run-task":
        return asyncio.run(
            _run_task(settings, args.mode, args.request, args.topic, args.source_urls)
        )
    if args.command == "verify":
        from scripts.verify_release import main as verify_release

        return verify_release()
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
