from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.container import ApplicationContainer
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import ArticleDocument, AssetManifest, MetricRecord, TaskRecord
from app.services.analytics.metrics import calculate_windows
from app.services.analytics.quality import build_quality_report
from app.services.formatting.assets import resolve_asset_urls
from app.services.formatting.renderer import article_to_markdown

PIPELINE_STAGES = ("需求", "数据/选题", "研究", "写作", "视觉", "审核", "排版", "草稿")
CAPABILITY_WARNING_TTL = timedelta(hours=1)

# Statuses that mean a pipeline run is (probably) in flight; the console polls
# the live step timeline for these tasks.
RUNNING_STATUSES = {
    TaskStatus.DATA_SYNCED,
    TaskStatus.PLANNED,
    TaskStatus.RESEARCHED,
    TaskStatus.WRITTEN,
    TaskStatus.ASSETS_READY,
    TaskStatus.REVIEWED,
}


def _asset_version() -> str:
    """Bump static asset URLs whenever app.js/app.css change, defeating browser cache."""
    static_dir = Path(__file__).resolve().parent / "static"
    try:
        js = int((static_dir / "app.js").stat().st_mtime)
        css = int((static_dir / "app.css").stat().st_mtime)
    except OSError:
        return "0"
    return f"{js}-{css}"

STATUS_PRESENTATION: dict[TaskStatus, tuple[str, int, str | None, str]] = {
    TaskStatus.CREATED: ("等待运行", 0, "run", "neutral"),
    TaskStatus.DATA_SYNCED: ("数据已准备", 1, None, "running"),
    TaskStatus.PLANNED: ("选题已规划", 1, None, "running"),
    TaskStatus.RESEARCHED: ("研究完成", 2, None, "running"),
    TaskStatus.WRITTEN: ("初稿完成", 3, None, "running"),
    TaskStatus.ASSETS_READY: ("视觉方案完成", 4, None, "running"),
    TaskStatus.REVIEWED: ("审核完成", 5, None, "running"),
    TaskStatus.FORMATTED: ("等待人工审阅", 6, "preview", "success"),
    TaskStatus.WECHAT_DRAFTED: ("已写入微信草稿", 7, "preview", "success"),
    TaskStatus.NEEDS_HUMAN: ("需要人工处理", 5, "review", "warning"),
    TaskStatus.FAILED: ("运行失败", 0, "retry", "error"),
    TaskStatus.HUMAN_REVIEWED: ("人工审核完成", 6, "preview", "success"),
    TaskStatus.PUBLISHED: ("已人工发布", 7, None, "success"),
    TaskStatus.POST_ANALYZED: ("发布后复盘完成", 7, None, "success"),
}


def _change(current: float, previous: float) -> tuple[str, str]:
    if previous <= 0:
        return ("neutral", "暂无环比") if current <= 0 else ("up", "新增数据")
    percentage = (current - previous) / previous * 100
    direction = "up" if percentage > 0 else "down" if percentage < 0 else "neutral"
    return direction, f"{percentage:+.1f}%"


def _format_integer(value: int) -> str:
    return f"{value:,}"


def metric_cards(
    records: list[MetricRecord], *, now: datetime | None = None
) -> list[dict[str, object]]:
    reference = now or datetime.now().astimezone()
    current = calculate_windows(records, as_of=reference)["30d"]
    previous = calculate_windows(records, as_of=reference - timedelta(days=30))["30d"]
    has_data = current.article_count > 0

    current_share_rate = current.shares / current.reads * 100 if current.reads > 0 else 0.0
    previous_share_rate = previous.shares / previous.reads * 100 if previous.reads > 0 else 0.0
    values = (
        ("reads", "阅读人数", current.reads, previous.reads, _format_integer(current.reads)),
        (
            "share_rate",
            "分享率",
            round(current_share_rate, 1),
            round(previous_share_rate, 1),
            f"{current_share_rate:.1f}%",
        ),
        (
            "followers",
            "新增关注",
            current.followers_gained,
            previous.followers_gained,
            _format_integer(current.followers_gained),
        ),
    )
    cards: list[dict[str, object]] = []
    for key, label, value, previous_value, display in values:
        direction, change_text = _change(float(value), float(previous_value))
        cards.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "display_value": display if has_data else "—",
                "has_data": has_data,
                "change_direction": direction if has_data else "neutral",
                "change_text": change_text if has_data else "尚未导入数据",
                "period": "近 30 天",
            }
        )
    return cards


def task_view(task: TaskRecord) -> dict[str, object]:
    label, stage_index, action, tone = STATUS_PRESENTATION.get(
        task.status,
        (task.status.value, 0, None, "neutral"),
    )
    stage_states = [
        "done" if index < stage_index else "active" if index == stage_index else "pending"
        for index in range(len(PIPELINE_STAGES))
    ]
    return {
        "id": task.id,
        "short_id": task.id[:8].upper(),
        "title": task.topic or task.request,
        "title_hint": task.title_hint,
        "request": task.request,
        "mode": task.mode.value,
        "status": task.status.value,
        "status_label": label,
        "status_tone": tone,
        "current_stage_index": stage_index,
        "current_stage": PIPELINE_STAGES[stage_index],
        "stage_states": stage_states,
        "action": action,
        "can_push_draft": task.status in {TaskStatus.FORMATTED, TaskStatus.HUMAN_REVIEWED},
        "running": task.status in RUNNING_STATUSES,
        "updated_at": task.updated_at,
        "updated_label": task.updated_at.strftime("%m-%d %H:%M"),
        "last_error": task.last_error,
    }


def _capability_report_is_fresh(report: dict[str, object], *, reference: datetime) -> bool:
    generated_at = report.get("generated_at")
    if not isinstance(generated_at, str):
        return False
    try:
        report_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if report_time.tzinfo is None and reference.tzinfo is not None:
        report_time = report_time.replace(tzinfo=reference.tzinfo)
    elif report_time.tzinfo is not None and reference.tzinfo is None:
        reference = reference.replace(tzinfo=report_time.tzinfo)
    return reference - report_time <= CAPABILITY_WARNING_TTL


def _wechat_status(container: ApplicationContainer, *, reference: datetime) -> dict[str, object]:
    configured = bool(
        container.settings.wechat_app_id and container.settings.wechat_app_secret
    )
    result: dict[str, object] = {
        "configured": configured,
        "label": "微信已配置" if configured else "等待配置微信",
        "tone": "success" if configured else "neutral",
    }
    report_root = Path(container.settings.object_storage_path) / "capabilities"
    # The API probe writes versioned artifacts (capability_report.latest.json); the
    # CLI writes a bare capability_report.json. Accept either.
    report_path = next(
        (
            candidate
            for candidate in (
                report_root / "capability_report.latest.json",
                report_root / "capability_report.json",
            )
            if candidate.exists()
        ),
        None,
    )
    if report_path is None:
        return result
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    access_token = next(
        (check for check in report.get("checks", []) if check.get("name") == "access_token"),
        None,
    )
    if (
        access_token
        and access_token.get("error_code") == 40164
        and _capability_report_is_fresh(report, reference=reference)
    ):
        result.update(
            {
                "label": "等待配置 IP 白名单",
                "tone": "warning",
                "message": "微信凭证有效，当前出口 IP 尚未加入 API 白名单。",
            }
        )
    elif access_token and access_token.get("status") == "available":
        result.update({"label": "微信接口可用", "tone": "success"})
    return result


def _greeting(now: datetime) -> str:
    if now.hour < 6:
        return "夜深了"
    if now.hour < 12:
        return "早上好"
    if now.hour < 18:
        return "下午好"
    return "晚上好"


def _base_context(container: ApplicationContainer, *, reference: datetime) -> dict[str, Any]:
    raw_tasks = container.tasks.list(limit=20)
    views = [task_view(task) for task in raw_tasks]
    return {
        "account_name": container.settings.wechat_account_name,
        "tasks": raw_tasks,
        "task_views": views,
        "pending_task_count": sum(
            view["status"] not in {"FORMATTED", "WECHAT_DRAFTED", "PUBLISHED", "POST_ANALYZED"}
            for view in views
        ),
        "model_name": container.settings.deepseek_model,
        "model_status": {
            "configured": container.settings.deepseek_api_key is not None,
            "label": (
                "模型已连接"
                if container.settings.deepseek_api_key is not None
                else "等待配置模型"
            ),
        },
        "wechat_status": _wechat_status(container, reference=reference),
        "wechat_configured": bool(
            container.settings.wechat_app_id and container.settings.wechat_app_secret
        ),
        "draft_enabled": container.settings.wechat_draft_enabled,
        "operator_name": container.settings.operator_name,
        "greeting": _greeting(reference),
        "local_time": reference.strftime("%Y-%m-%d %H:%M"),
        "asset_version": _asset_version(),
    }


def build_dashboard_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """工作台：欢迎面板 + 当前流水线 + 最近任务概览。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    context.update(
        {
            "active_task": context["task_views"][0] if context["task_views"] else None,
            "pipeline_stages": PIPELINE_STAGES,
        }
    )
    return context


def build_tasks_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """内容任务：完整任务列表与操作。"""
    reference = now or datetime.now(container.settings.timezone)
    return _base_context(container, reference=reference)


def build_review_context(
    container: ApplicationContainer,
    task_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """人工审阅：格式化 HTML 预览 + 可编辑 Markdown 终稿。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    try:
        task = container.tasks.get(task_id)
    except KeyError:
        task = None
    context["task"] = task
    context["review"] = {"ok": False, "reason": "任务不存在"}
    if task is None:
        return context
    try:
        article_payload = container.artifacts.read_json(task_id, "article")
        try:
            html_payload = container.artifacts.read_json(task_id, "final_wechat_html")
        except FileNotFoundError:
            html_payload = container.artifacts.read_json(task_id, "wechat_html")
    except FileNotFoundError:
        context["review"] = {"ok": False, "reason": "任务尚未产出文章，请先运行任务"}
        return context
    article = ArticleDocument.model_validate(article_payload)
    generated_markdown = article_to_markdown(article)
    final_markdown = generated_markdown
    try:
        final_version = container.artifacts.read_json(task_id, "final_version")
        final_markdown = str(final_version.get("markdown", generated_markdown))
    except FileNotFoundError:
        pass
    # Point figure images at the local asset endpoint so the preview shows the
    # real generated/searched images instead of empty frames.
    try:
        manifest = AssetManifest.model_validate(container.artifacts.read_json(task_id, "assets"))
    except FileNotFoundError:
        manifest = None
    html = resolve_asset_urls(str(html_payload.get("html", "")), task_id, manifest)
    diff = None
    try:
        diff = container.artifacts.read_json(task_id, "human_edit_diff")
    except FileNotFoundError:
        pass
    is_reviewed = task.status in {
        TaskStatus.HUMAN_REVIEWED,
        TaskStatus.PUBLISHED,
        TaskStatus.POST_ANALYZED,
    }
    context["review"] = {
        "ok": True,
        "task_id": task_id,
        "title": task.topic or task.request,
        "status": task.status.value,
        "html": html,
        "generated_markdown": generated_markdown,
        "final_markdown": final_markdown,
        "diff": diff,
        "is_reviewed": is_reviewed,
    }
    return context


def build_calendar_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """内容日历：把周度计划映射成逐日任务看板。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    context["calendar"] = {"has_plan": False, "rows": []}
    plans = container.tasks.list_by_mode(TaskMode.WEEKLY_PLAN, limit=1)
    if not plans:
        return context
    plan_task = plans[0]
    try:
        plan = container.artifacts.read_json(plan_task.id, "weekly_plan")
    except FileNotFoundError:
        plan = None
    plan_tasks = container.tasks.list_by_plan(plan_task.id)
    by_topic: dict[str, TaskRecord] = {}
    for planned in plan_tasks:
        by_topic.setdefault(planned.topic, planned)
    # The first plan item is represented by the plan task itself (its topic is set
    # to items[0] mid-run), not by a child task with plan_id.
    if plan_task.topic:
        by_topic.setdefault(plan_task.topic, plan_task)
    rows: list[dict[str, object]] = []
    if plan and plan.get("items"):
        for item in plan["items"]:
            planned = by_topic.get(item.get("topic"))
            view = task_view(planned) if planned is not None else None
            rows.append(
                {
                    "day": item.get("day", ""),
                    "topic": item.get("topic", ""),
                    "format": item.get("format", ""),
                    "purpose": item.get("purpose", ""),
                    "task_id": planned.id if planned is not None else None,
                    "status": planned.status.value if planned is not None else None,
                    "status_label": view["status_label"] if view else "未建任务",
                    "status_tone": view["status_tone"] if view else "neutral",
                    "action": view["action"] if view else "create",
                }
            )
    context["calendar"] = {
        "has_plan": plan is not None,
        "plan_task_id": plan_task.id,
        "plan_created": plan_task.created_at.strftime("%Y-%m-%d"),
        "rows": rows,
    }
    return context


def build_data_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """数据复盘：指标卡、数据质量与 7/30/90 天窗口。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    records = container.metrics.list()
    quality = build_quality_report(records, now=reference)
    windows = calculate_windows(records, as_of=reference)
    cards = metric_cards(records, now=reference)
    context.update(
        {
            "metric_cards": cards,
            "has_data": cards[0]["has_data"] if cards else False,
            "data_quality": quality,
            "quality_fields": [
                ("记录总数", f"{quality.total_records} 条"),
                (
                    "数据置信度",
                    f"{quality.confidence:.0%}" if quality.total_records > 0 else "—",
                ),
                ("重复记录", f"{quality.duplicate_count} 条"),
                ("异常记录", f"{quality.anomaly_count} 条"),
                (
                    "数据延迟",
                    (
                        f"{quality.delay_days:.1f} 天"
                        if quality.delay_days is not None
                        else "—"
                    ),
                ),
                ("来源类型", "、".join(quality.source_types) or "—"),
            ],
            "missing_fields": [
                {"field": field, "rate": f"{rate:.0%}"}
                for field, rate in quality.missing_rates.items()
                if rate > 0
            ],
            "windows": [
                {
                    "period": label,
                    "articles": window.article_count,
                    "reads": window.reads,
                    "shares": window.shares,
                    "favorites": window.favorites,
                    "followers": window.followers_gained,
                    "read_per_article": window.read_per_article,
                }
                for label, window in (
                    ("近 7 天", windows["7d"]),
                    ("近 30 天", windows["30d"]),
                    ("近 90 天", windows["90d"]),
                )
            ],
            "topic_performance": [
                {
                    "task_id": record.task_id,
                    "topic": record.topic,
                    "published_at": (
                        record.published_at.strftime("%Y-%m-%d")
                        if record.published_at
                        else "—"
                    ),
                    "reads": record.reads if record.reads is not None else None,
                    "shares": record.shares,
                    "favorites": record.favorites,
                    "followers": record.followers_gained,
                    "measured": record.measured_at is not None,
                }
                for record in container.topic_records.list_published()
            ],
        }
    )
    return context


def build_agent_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """Agent 能力：Skills 注册表、MCP 服务器与配图能力状态。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    context.update(
        {
            "skills": container.skills.discover(),
            "mcp_servers": container.mcp.snapshot(),
            "image_provider": {
                "ai_generation_available": container.settings.ai_image_generation_available,
                "web_search_available": container.settings.web_image_search_available,
                "image_model": container.settings.siliconflow_image_model,
                "provider": container.settings.image_model_provider,
                "search_provider": container.settings.image_search_provider,
                "dashscope_model": container.settings.dashscope_image_model,
            },
            "web_search_status": {
                "provider": container.settings.web_search_provider,
                "available": container.settings.web_search_available,
            },
        }
    )
    return context
