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

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

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

WRITTEN_PLUS_STATUSES = {
    TaskStatus.WRITTEN,
    TaskStatus.ASSETS_READY,
    TaskStatus.REVIEWED,
    TaskStatus.FORMATTED,
    TaskStatus.WECHAT_DRAFTED,
    TaskStatus.NEEDS_HUMAN,
    TaskStatus.HUMAN_REVIEWED,
    TaskStatus.PUBLISHED,
    TaskStatus.POST_ANALYZED,
}

ASSET_READY_STATUSES = WRITTEN_PLUS_STATUSES - {
    TaskStatus.WRITTEN,
    TaskStatus.NEEDS_HUMAN,
}

DRAFTED_PLUS_STATUSES = {
    TaskStatus.WECHAT_DRAFTED,
    TaskStatus.HUMAN_REVIEWED,
    TaskStatus.PUBLISHED,
    TaskStatus.POST_ANALYZED,
}

REVIEW_READY_STATUSES = {
    TaskStatus.FORMATTED,
    TaskStatus.WECHAT_DRAFTED,
    TaskStatus.NEEDS_HUMAN,
    TaskStatus.HUMAN_REVIEWED,
    TaskStatus.PUBLISHED,
    TaskStatus.POST_ANALYZED,
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
        return ("neutral", "暂无环比") if current <= 0 else ("up", "前期无数据")
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
        "created_label": task.created_at.strftime("%m-%d %H:%M"),
        "last_error": task.last_error,
    }


def daily_series(
    records: list[MetricRecord], *, days: int, reference: datetime
) -> list[dict[str, object]]:
    """Bucket imported metrics into per-day totals for the newest `days` days."""
    buckets: dict[Any, dict[str, object]] = {}
    for offset in range(days - 1, -1, -1):
        day = (reference - timedelta(days=offset)).date()
        buckets[day] = {
            "date": day.isoformat(),
            "label": f"{day.month}/{day.day}",
            "reads": 0,
            "shares": 0,
            "favorites": 0,
            "followers": 0,
            "has_data": False,
        }
    for record in records:
        bucket = buckets.get(record.metric_date.date())
        if bucket is None:
            continue
        bucket["reads"] = int(bucket["reads"]) + max(record.reads, 0)
        bucket["shares"] = int(bucket["shares"]) + record.shares
        bucket["favorites"] = int(bucket["favorites"]) + record.favorites
        bucket["followers"] = int(bucket["followers"]) + record.followers_gained
        bucket["has_data"] = True
    return list(buckets.values())


def _followers_on(records: list[MetricRecord], day: Any) -> int:
    return sum(record.followers_gained for record in records if record.metric_date.date() == day)


def overview_kpis(
    container: ApplicationContainer, *, reference: datetime
) -> list[dict[str, object]]:
    """四张顶部指标卡：全部来自本地真实记录，没有数据时明确留空。"""
    tasks = container.tasks.list(limit=300)
    receipts = container.publications.list_draft_receipts(limit=500)
    records = container.metrics.list()
    today = reference.date()
    yesterday = today - timedelta(days=1)

    generated_today = sum(1 for task in tasks if task.created_at.date() == today)
    generated_yesterday = sum(1 for task in tasks if task.created_at.date() == yesterday)
    has_task_history = generated_today > 0 or generated_yesterday > 0
    gen_direction, gen_change = _change(generated_today, generated_yesterday)

    drafted_today = sum(1 for item in receipts if item.created_at.date() == today)
    drafted_yesterday = sum(1 for item in receipts if item.created_at.date() == yesterday)
    has_draft_history = drafted_today > 0 or drafted_yesterday > 0
    draft_direction, draft_change = _change(drafted_today, drafted_yesterday)

    written_tasks = [task for task in tasks if task.status in WRITTEN_PLUS_STATUSES]
    illustrated = [task for task in written_tasks if task.status in ASSET_READY_STATUSES]
    asset_rate = round(len(illustrated) / len(written_tasks) * 100, 1) if written_tasks else None

    latest_data_day = max((record.metric_date.date() for record in records), default=None)
    has_follower_data = latest_data_day is not None
    follower_current = _followers_on(records, latest_data_day) if latest_data_day else 0
    follower_previous = (
        _followers_on(records, latest_data_day - timedelta(days=1)) if latest_data_day else 0
    )
    follower_direction, follower_change = _change(follower_current, follower_previous)

    draft_hint = (
        "草稿上传未开启，保存动作由人工触发"
        if not container.settings.wechat_draft_enabled
        else "人工确认后写入微信草稿箱"
    )

    def _rate_display(rate: float | None) -> str:
        return f"{rate:.0f}%" if rate is not None else "—"

    return [
        {
            "key": "generated",
            "label": "今日生成文章",
            "value": generated_today,
            "display_value": str(generated_today) if has_task_history else "0",
            "has_data": has_task_history,
            "change_direction": gen_direction if has_task_history else "neutral",
            "change_text": gen_change if has_task_history else "今天还没有创建任务",
            "period": "较昨日",
        },
        {
            "key": "drafts",
            "label": "草稿箱保存",
            "value": drafted_today,
            "display_value": str(drafted_today) if has_draft_history else "0",
            "has_data": has_draft_history,
            "change_direction": draft_direction if has_draft_history else "neutral",
            "change_text": draft_change if has_draft_history else draft_hint,
            "period": "较昨日",
        },
        {
            "key": "assets",
            "label": "配图完成率",
            "value": asset_rate,
            "display_value": _rate_display(asset_rate),
            "has_data": asset_rate is not None,
            "change_direction": "neutral",
            "change_text": (
                f"{len(illustrated)}/{len(written_tasks)} 篇初稿已配图"
                if written_tasks
                else "初稿完成后自动规划配图"
            ),
            "period": "近 30 天",
        },
        {
            "key": "followers",
            "label": "粉丝增长",
            "value": follower_current,
            "display_value": (
                f"+{_format_integer(follower_current)}" if has_follower_data else "—"
            ),
            "has_data": has_follower_data,
            "change_direction": follower_direction if has_follower_data else "neutral",
            "change_text": (
                follower_change
                + (
                    ""
                    if latest_data_day == today
                    else f"（{latest_data_day.month}/{latest_data_day.day}）"
                )
                if has_follower_data
                else "导入数据后显示"
            ),
            "period": "单日新增",
        },
    ]


def workflow_view(container: ApplicationContainer, *, reference: datetime) -> dict[str, object]:
    """把最近一条内容任务映射成 Agent 工作流的六个展示节点。"""
    tasks = [task for task in container.tasks.list(limit=50) if task.mode != TaskMode.WEEKLY_PLAN]
    latest = tasks[0] if tasks else None
    topic_records = {record.task_id: record for record in container.topic_records.list_published()}

    if latest is None:
        waiting_steps = [
            ("选题策划", "创建任务后自动规划选题"),
            ("AI 写稿", "研究完成后再动笔"),
            ("智能配图", "按文章内容规划封面与配图"),
            ("保存到草稿箱", "人工确认后上传（可选）"),
            ("定时提醒", "到点提醒，正式群发由人工完成"),
            ("数据复盘", "发布登记后自动回流效果"),
        ]
        steps = [
            {"title": title, "detail": detail, "state": "waiting", "time": "", "index": index + 1}
            for index, (title, detail) in enumerate(waiting_steps)
        ]
        return {"steps": steps, "running": False, "badge": "待命", "task": None, "notice": None}

    status = latest.status
    topic_record = topic_records.get(latest.id)
    done_map = {
        "选题策划": status
        in {
            TaskStatus.PLANNED,
            TaskStatus.RESEARCHED,
            TaskStatus.WRITTEN,
            TaskStatus.ASSETS_READY,
            TaskStatus.REVIEWED,
            TaskStatus.FORMATTED,
            TaskStatus.WECHAT_DRAFTED,
            TaskStatus.HUMAN_REVIEWED,
            TaskStatus.PUBLISHED,
            TaskStatus.POST_ANALYZED,
        },
        "AI 写稿": status in WRITTEN_PLUS_STATUSES,
        "智能配图": status in ASSET_READY_STATUSES,
        "保存到草稿箱": status in DRAFTED_PLUS_STATUSES,
        "定时提醒": status in {TaskStatus.PUBLISHED, TaskStatus.POST_ANALYZED},
        "数据复盘": (
            status == TaskStatus.POST_ANALYZED
            or (topic_record is not None and topic_record.measured_at is not None)
        ),
    }
    done_details = {
        "选题策划": "已完成 · 已产出选题方向",
        "AI 写稿": "已完成 · 生成 1 篇文章",
        "智能配图": "已完成 · 配图方案就绪",
        "保存到草稿箱": "已完成 · 已保存到草稿箱",
        "定时提醒": "已提醒 · 请在微信后台完成群发",
        "数据复盘": "已完成 · 效果数据已回流",
    }
    waiting_details = {
        "选题策划": "创建任务后自动规划选题",
        "AI 写稿": "研究完成后再动笔",
        "智能配图": "按文章内容规划封面与配图",
        "保存到草稿箱": "人工确认后上传（可选）",
        "定时提醒": "到点提醒，正式群发由人工完成",
        "数据复盘": "发布登记后自动回流效果",
    }
    steps: list[dict[str, object]] = []
    reached_pending = False
    is_running = status in RUNNING_STATUSES
    for index, (title, done) in enumerate(done_map.items()):
        if done:
            state = "done"
            time_label = latest.updated_at.strftime("%H:%M")
        elif not reached_pending:
            reached_pending = True
            state = "active"
            time_label = "进行中" if is_running else "等待中"
        else:
            state = "pending"
            time_label = ""
        detail = done_details[title] if done else waiting_details[title]
        steps.append(
            {
                "title": title,
                "detail": detail,
                "state": state,
                "time": time_label,
                "index": index + 1,
            }
        )

    if status == TaskStatus.WECHAT_DRAFTED:
        notice = {
            "tone": "success",
            "title": "已成功保存到微信草稿箱",
            "body": (
                f"文章《{latest.title_hint or latest.topic or latest.request}》已保存到"
                f"「{container.settings.wechat_account_name}」的草稿箱，"
                "正式发布请在微信后台完成。"
            ),
        }
    elif status == TaskStatus.FAILED:
        notice = {
            "tone": "error",
            "title": "本轮运行失败",
            "body": latest.last_error or "请查看运行记录后重试。",
        }
    elif status == TaskStatus.NEEDS_HUMAN:
        notice = {
            "tone": "warning",
            "title": "需要人工处理",
            "body": "自动修订已达两轮上限，请进入审阅页完成终稿。",
        }
    elif status == TaskStatus.FORMATTED:
        notice = {
            "tone": "info",
            "title": "等待人工审阅",
            "body": "文章已排版完成，进入审阅页确认终稿后可上传草稿箱。",
        }
    else:
        notice = {
            "tone": "info",
            "title": "Agent 正在为你规划任务",
            "body": (
                "好内容，会带来更多相遇。"
                if is_running
                else "创建任务后，工作流会自动推进每个节点。"
            ),
        }

    if is_running:
        running_badge = "运行中"
    elif status in {TaskStatus.FORMATTED, TaskStatus.NEEDS_HUMAN}:
        running_badge = "待人工"
    else:
        running_badge = "空闲"
    return {
        "steps": steps,
        "running": is_running,
        "badge": running_badge,
        "task": task_view(latest),
        "notice": notice,
    }


def latest_article_preview(container: ApplicationContainer) -> dict[str, object] | None:
    """最近一篇可审阅文章的预览信息（真实产物，未生成则为 None）。"""
    for task in container.tasks.list(limit=20):
        if task.status not in REVIEW_READY_STATUSES:
            continue
        try:
            article = ArticleDocument.model_validate(
                container.artifacts.read_json(task.id, "article")
            )
            try:
                html_payload = container.artifacts.read_json(task.id, "final_wechat_html")
            except FileNotFoundError:
                html_payload = container.artifacts.read_json(task.id, "wechat_html")
        except FileNotFoundError:
            continue
        try:
            manifest = AssetManifest.model_validate(
                container.artifacts.read_json(task.id, "assets")
            )
        except FileNotFoundError:
            manifest = None
        html = resolve_asset_urls(str(html_payload.get("html", "")), task.id, manifest)
        markdown = article_to_markdown(article)
        sections = [section for section in article.sections if section.type == "heading"]
        return {
            "task_id": task.id,
            "title": article.selected_title or task.title_hint or task.topic or task.request,
            "html": html,
            "digest": article.digest,
            "word_count": len(markdown),
            "heading_preview": [section.content for section in sections[:3] if section.content],
            "updated_label": task.updated_at.strftime("%m-%d %H:%M"),
            "status_label": STATUS_PRESENTATION.get(task.status, (task.status.value,))[0],
        }
    return None


def cover_gallery(container: ApplicationContainer) -> dict[str, object]:
    """配图生成面板：本地渲染的风格示意 + 最近任务的真实配图资产。"""
    recent_assets: list[dict[str, object]] = []
    for task in container.tasks.list(limit=10):
        try:
            manifest = AssetManifest.model_validate(
                container.artifacts.read_json(task.id, "assets")
            )
        except FileNotFoundError:
            continue
        for item in manifest.items:
            if item.status != "ready" or item.kind not in {"cover", "concept"}:
                continue
            recent_assets.append(
                {
                    "task_id": task.id,
                    "asset_id": item.asset_id,
                    "caption": item.caption or item.query_or_prompt or item.kind,
                    "provider": item.provider or item.source or "deterministic",
                    "url": f"/api/v1/tasks/{task.id}/assets/{item.asset_id}",
                }
            )
        if len(recent_assets) >= 6:
            break
    return {
        "styles": [
            {"key": "mountain", "title": "用 AI 点亮高效生活", "subtitle": "让效率，成为一种习惯"},
            {"key": "desk", "title": "AI × 效率", "subtitle": "更好的自己，更专注的状态"},  # noqa: E501
            {
                "key": "coffee",
                "title": "和 AI 一起工作与成长",
                "subtitle": "更高效、更专注、更自由",
            },  # noqa: E501
        ],
        "recent_assets": recent_assets[:6],
        "ai_configured": container.settings.ai_image_generation_available,
        "search_configured": container.settings.web_image_search_available,
    }


def calendar_month_grid(reference: datetime) -> list[list[dict[str, object]]]:
    """当月日历网格（周一开头），用于总览页的迷你日历。"""
    first = reference.date().replace(day=1)
    grid_start = first - timedelta(days=first.weekday())
    weeks: list[list[dict[str, object]]] = []
    for week_index in range(6):
        week: list[dict[str, object]] = []
        for day_index in range(7):
            day = grid_start + timedelta(days=week_index * 7 + day_index)
            week.append(
                {
                    "day": day.day,
                    "in_month": day.month == reference.month,
                    "is_today": day == reference.date(),
                    "date": day.isoformat(),
                }
            )
        if any(cell["in_month"] for cell in week):
            weeks.append(week)
    return weeks


def _calendar_rows(container: ApplicationContainer) -> dict[str, object]:
    """复用内容日历逻辑：返回周计划行与按星期分组的映射。"""
    plans = container.tasks.list_by_mode(TaskMode.WEEKLY_PLAN, limit=1)
    if not plans:
        return {"has_plan": False, "rows": [], "plan_task_id": None}
    plan_task = plans[0]
    try:
        plan = container.artifacts.read_json(plan_task.id, "weekly_plan")
    except FileNotFoundError:
        plan = None
    plan_tasks = container.tasks.list_by_plan(plan_task.id)
    by_topic: dict[str, TaskRecord] = {}
    for planned in plan_tasks:
        by_topic.setdefault(planned.topic, planned)
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
    return {
        "has_plan": plan is not None,
        "plan_task_id": plan_task.id,
        "plan_created": plan_task.created_at.strftime("%Y-%m-%d"),
        "week_start": (plan or {}).get("week_start", ""),
        "rows": rows,
    }


def fans_summary(container: ApplicationContainer, *, reference: datetime) -> dict[str, object]:
    """粉丝运营概览：全部由导入的指标与已发布选题推导。"""
    records = container.metrics.list()
    today = reference.date()
    followers_today = _followers_on(records, today)
    followers_7d = sum(
        record.followers_gained
        for record in records
        if today - timedelta(days=6) <= record.metric_date.date() <= today
    )
    followers_30d = calculate_windows(records, as_of=reference)["30d"].followers_gained
    has_data = bool(records)

    interactions_7d = sum(
        record.shares + record.favorites
        for record in records
        if today - timedelta(days=6) <= record.metric_date.date() <= today
    )

    topic_shares: dict[str, int] = {}
    for record in records:
        title = record.article_title or "未命名文章"
        topic_shares[title] = topic_shares.get(title, 0) + max(record.reads, 0)
    ranked = sorted(topic_shares.items(), key=lambda pair: pair[1], reverse=True)[:5]
    total_reads = sum(value for _, value in ranked) or 1
    palette = ("green", "blue", "violet", "orange", "gray")
    distribution = [
        {
            "label": label,
            "percent": round(value / total_reads * 100, 1),
            "tone": palette[index],
        }
        for index, (label, value) in enumerate(ranked)
    ]

    return {
        "cards": [
            {
                "label": "新增关注（今日）",
                "value": f"+{_format_integer(followers_today)}" if has_data else "—",
                "tone": "green",
                "hint": "来自当天导入的指标",
            },
            {
                "label": "近 7 天新增关注",
                "value": f"+{_format_integer(followers_7d)}" if has_data else "—",
                "tone": "blue",
                "hint": "按日汇总",
            },
            {
                "label": "近 30 天新增关注",
                "value": f"+{_format_integer(followers_30d)}" if has_data else "—",
                "tone": "orange",
                "hint": "按日汇总",
            },
        ],
        "interactions_7d": _format_integer(interactions_7d) if has_data else "—",
        "distribution": distribution,
        "has_data": has_data,
    }


def _pretty_y_ticks(max_value: int) -> list[dict[str, object]]:
    if max_value <= 0:
        return [{"value": 0, "label": "0", "ratio": 0.0}]
    step = max_value / 2
    return [
        {"value": round(max_value), "label": _compact_number(int(max_value)), "ratio": 1.0},
        {"value": round(step), "label": _compact_number(int(step)), "ratio": 0.5},
        {"value": 0, "label": "0", "ratio": 0.0},
    ]


def _compact_number(value: int) -> str:
    if value >= 10000:
        return f"{value // 1000 / 10:.1f}万".rstrip("0").rstrip(".")
    return f"{value:,}"


def trend_chart(
    series: list[dict[str, object]], *, mode: str = "reads_shares"
) -> dict[str, object]:
    """近 N 天趋势组合图（服务端计算坐标，模板只负责画 SVG）。

    mode="reads_shares"：阅读量 + 分享次数双柱与阅读折线；
    mode="followers"：仅每日新增关注单柱。
    """
    width, height = 560, 180
    pad_left, pad_right, pad_top, pad_bottom = 42, 10, 12, 26
    inner_w = width - pad_left - pad_right
    inner_h = height - pad_top - pad_bottom
    count = max(len(series), 1)
    column = inner_w / count
    primary_key = "followers" if mode == "followers" else "reads"
    max_primary = max([int(item[primary_key]) for item in series] + [1])
    max_reads = max_primary
    max_shares = (
        max([int(item["shares"]) for item in series] + [1])
        if mode != "followers"
        else 1
    )

    bars: list[dict[str, float]] = []
    shares_bars: list[dict[str, float]] = []
    line_points: list[str] = []
    dots: list[dict[str, float]] = []
    labels: list[dict[str, object]] = []
    for index, item in enumerate(series):
        center = pad_left + column * index + column / 2
        reads = int(item[primary_key])
        shares = int(item["shares"]) if mode != "followers" else 0
        reads_h = inner_h * reads / max_reads
        shares_h = inner_h * shares / max_shares
        bar_w = min(14.0, column * 0.26)
        bar_offset = 0 if mode == "followers" else -bar_w - 2
        bars.append(
            {
                "x": round(center + bar_offset, 1),
                "y": round(pad_top + inner_h - reads_h, 1),
                "w": round(bar_w, 1),
                "h": round(reads_h, 1),
            }
        )
        shares_bars.append(
            {
                "x": round(center + 2, 1),
                "y": round(pad_top + inner_h - shares_h, 1),
                "w": round(bar_w, 1),
                "h": round(shares_h, 1),
            }
        )
        line_y = pad_top + inner_h - reads_h
        line_points.append(f"{center:.1f},{line_y:.1f}")
        dots.append({"x": round(center, 1), "y": round(line_y, 1)})
        labels.append({"x": round(center, 1), "label": str(item["label"])})

    return {
        "width": width,
        "height": height,
        "pad_left": pad_left,
        "pad_bottom": pad_bottom,
        "inner_h": inner_h,
        "baseline_y": pad_top + inner_h,
        "bars": bars,
        "shares_bars": shares_bars,
        "line_points": " ".join(line_points),
        "dots": dots,
        "labels": labels,
        "y_ticks": _pretty_y_ticks(max_reads),
        "empty": not any(item["has_data"] for item in series),
        "series_json": json.dumps(
            [
                {"label": item["label"], "reads": int(item["reads"]), "shares": int(item["shares"])}
                for item in series
            ],
            ensure_ascii=False,
        ),
    }


def trend_change_summary(records: list[MetricRecord], *, reference: datetime) -> dict[str, object]:
    """近 7 天 vs 前 7 天的简易环比，用于总览页迷你指标。"""
    series = daily_series(records, days=14, reference=reference)
    current = series[7:]
    previous = series[:7]
    reads_now = sum(int(item["reads"]) for item in current)
    reads_prev = sum(int(item["reads"]) for item in previous)
    shares_now = sum(int(item["shares"]) for item in current)
    shares_prev = sum(int(item["shares"]) for item in previous)
    articles_now = len([item for item in current if item["has_data"]])
    per_now = reads_now / articles_now if articles_now else 0.0
    articles_prev = len([item for item in previous if item["has_data"]])
    per_prev = reads_prev / articles_prev if articles_prev else 0.0
    reads_direction, reads_text = _change(reads_now, reads_prev)
    shares_direction, shares_text = _change(shares_now, shares_prev)
    per_direction, per_text = _change(per_now, per_prev)
    has_base = reads_prev > 0 or shares_prev > 0
    if not has_base:
        reads_text = shares_text = per_text = "上周暂无对比"
    return {
        "reads_direction": reads_direction if has_base else "neutral",
        "reads_text": reads_text,
        "shares_direction": shares_direction if has_base else "neutral",
        "shares_text": shares_text,
        "per_direction": per_direction if has_base else "neutral",
        "per_text": per_text,
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
    configured = bool(container.settings.wechat_app_id and container.settings.wechat_app_secret)
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
    pending_count = sum(
        view["status"] not in {"FORMATTED", "WECHAT_DRAFTED", "PUBLISHED", "POST_ANALYZED"}
        for view in views
    )
    review_pending = sum(
        1 for task in raw_tasks if task.status in {TaskStatus.FORMATTED, TaskStatus.NEEDS_HUMAN}
    )
    return {
        "account_name": container.settings.wechat_account_name,
        "tasks": raw_tasks,
        "task_views": views,
        "pending_task_count": pending_count,
        "review_pending_count": review_pending,
        "model_name": container.settings.deepseek_model,
        "model_status": {
            "configured": container.settings.deepseek_api_key is not None,
            "label": (
                "模型已连接" if container.settings.deepseek_api_key is not None else "等待配置模型"
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
    """总览：顶部指标卡 + 生成/预览/配图/工作流 + 日历/数据/粉丝。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    records = container.metrics.list()
    series_7d = daily_series(records, days=7, reference=reference)
    calendar_data = _calendar_rows(container)
    windows = calculate_windows(records, as_of=reference)
    today_weekday = WEEKDAY_LABELS[reference.weekday()]
    today_rows = [
        row for row in calendar_data["rows"] if row["day"] == today_weekday
    ] or calendar_data["rows"][:3]
    context.update(
        {
            "active_task": context["task_views"][0] if context["task_views"] else None,
            "pipeline_stages": PIPELINE_STAGES,
            "kpi_cards": overview_kpis(container, reference=reference),
            "workflow": workflow_view(container, reference=reference),
            "article_preview": latest_article_preview(container),
            "covers": cover_gallery(container),
            "mini_calendar": {
                "weeks": calendar_month_grid(reference),
                "month_label": f"{reference.year} 年 {reference.month} 月",
                "today_label": f"{reference.month} 月 {reference.day} 日 · 今天",
                "weekday": today_weekday,
            },
            "calendar": calendar_data,
            "today_plan_rows": today_rows,
            "trend": trend_chart(series_7d),
            "trend_month": trend_chart(daily_series(records, days=30, reference=reference)),
            "trend_change": trend_change_summary(records, reference=reference),
            "summary": {
                "reads": windows["7d"].reads,
                "shares": windows["7d"].shares,
                "read_per_article": windows["7d"].read_per_article,
                "has_data": windows["7d"].article_count > 0,
            },
            "trend_range": "近 7 天",
            "fans": fans_summary(container, reference=reference),
            "has_metric_data": bool(records),
        }
    )
    return context


def build_tasks_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """AI 写稿：完整任务列表与操作。"""
    reference = now or datetime.now(container.settings.timezone)
    return _base_context(container, reference=reference)


def build_topics_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """选题中心：已发布选题表现 + 选题信号说明。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    topics = container.topic_records.list_published()
    measured = [record for record in topics if record.measured_at is not None]
    context["topics"] = {
        "rows": [
            {
                "topic": record.topic,
                "mode": record.mode.value,
                "published_at": (
                    record.published_at.strftime("%Y-%m-%d") if record.published_at else "—"
                ),
                "reads": record.reads,
                "shares": record.shares,
                "favorites": record.favorites,
                "followers": record.followers_gained,
                "measured": record.measured_at is not None,
                "task_id": record.task_id,
            }
            for record in topics
        ],
        "total": len(topics),
        "measured": len(measured),
        "has_data": bool(topics),
    }
    return context


def build_media_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """配图生成：能力状态 + 最近真实配图资产。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    context["covers"] = cover_gallery(container)
    context["image_provider"] = {
        "ai_generation_available": container.settings.ai_image_generation_available,
        "web_search_available": container.settings.web_image_search_available,
        "image_model": container.settings.siliconflow_image_model,
        "provider": container.settings.image_model_provider,
        "search_provider": container.settings.image_search_provider,
        "dashscope_model": container.settings.dashscope_image_model,
    }
    return context


def build_drafts_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """草稿箱同步：草稿回执与待审阅任务。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    receipts = container.publications.list_draft_receipts(limit=100)
    task_by_id = {task.id: task for task in context["tasks"]}
    rows: list[dict[str, object]] = []
    for receipt in receipts:
        task = task_by_id.get(receipt.task_id)
        rows.append(
            {
                "task_id": receipt.task_id,
                "title": (task.title_hint or task.topic or task.request)
                if task
                else receipt.task_id[:8],
                "media_id": receipt.media_id,
                "status_label": (
                    STATUS_PRESENTATION.get(task.status, (task.status.value,))[0]
                    if task
                    else "已上传"
                ),
                "status_tone": (
                    STATUS_PRESENTATION.get(task.status, (task.status.value, 0, None, "neutral"))[3]
                    if task
                    else "success"
                ),
                "created_label": receipt.created_at.strftime("%m-%d %H:%M"),
                "short_id": receipt.task_id[:8].upper(),
            }
        )
    context["drafts"] = {
        "rows": rows,
        "enabled": container.settings.wechat_draft_enabled,
        "count": len(rows),
    }
    return context


def build_schedule_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """定时群发（提醒）：发布等待清单与边界说明，不提供任何群发接口。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    waiting = [
        task_view(task)
        for task in container.tasks.list(limit=50)
        if task.status
        in {TaskStatus.FORMATTED, TaskStatus.HUMAN_REVIEWED, TaskStatus.WECHAT_DRAFTED}
    ]
    calendar_data = _calendar_rows(container)
    context["schedule"] = {
        "waiting": waiting,
        "has_plan": calendar_data["has_plan"],
        "plan_rows": calendar_data["rows"],
        "today_weekday": WEEKDAY_LABELS[reference.weekday()],
    }
    return context


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
    """运营日历：把周度计划映射成逐日任务看板。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    calendar_data = _calendar_rows(container)
    context["calendar"] = {
        "has_plan": False,
        "rows": [],
        "plan_task_id": None,
        "plan_created": "",
        "week_start": "",
        **calendar_data,
    }
    context["mini_calendar"] = {
        "weeks": calendar_month_grid(reference),
        "month_label": f"{reference.year} 年 {reference.month} 月",
        "today_label": f"{reference.month} 月 {reference.day} 日 · 今天",
        "weekday": WEEKDAY_LABELS[reference.weekday()],
    }
    return context


def build_data_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """数据分析：指标卡、数据质量与 7/30/90 天窗口。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    records = container.metrics.list()
    quality = build_quality_report(records, now=reference)
    windows = calculate_windows(records, as_of=reference)
    cards = metric_cards(records, now=reference)
    series_7d = daily_series(records, days=7, reference=reference)
    series_30d = daily_series(records, days=30, reference=reference)
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
                    (f"{quality.delay_days:.1f} 天" if quality.delay_days is not None else "—"),
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
                        record.published_at.strftime("%Y-%m-%d") if record.published_at else "—"
                    ),
                    "reads": record.reads if record.reads is not None else None,
                    "shares": record.shares,
                    "favorites": record.favorites,
                    "followers": record.followers_gained,
                    "measured": record.measured_at is not None,
                }
                for record in container.topic_records.list_published()
            ],
            "trend": trend_chart(series_7d),
            "trend_month": trend_chart(series_30d),
            "summary": {
                "reads": windows["7d"].reads,
                "shares": windows["7d"].shares,
                "read_per_article": windows["7d"].read_per_article,
                "has_data": windows["7d"].article_count > 0,
            },
        }
    )
    return context


def build_fans_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """粉丝运营页：关注趋势、互动与选题流量分布。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    records = container.metrics.list()
    series = daily_series(records, days=30, reference=reference)
    summary = fans_summary(container, reference=reference)

    top_articles: dict[str, int] = {}
    for record in records:
        title = record.article_title or "未命名文章"
        top_articles[title] = top_articles.get(title, 0) + max(record.reads, 0)
    ranked = sorted(top_articles.items(), key=lambda pair: pair[1], reverse=True)[:8]
    top_rows = [
        {"title": title, "reads": value, "share_display": _compact_number(value)}
        for title, value in ranked
    ]

    context["fans_page"] = {
        "summary": summary,
        "chart": trend_chart(series, mode="followers"),
        "top_articles": top_rows,
        "has_data": bool(records),
        "range_label": "近 30 天",
    }
    return context


def build_agent_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """工作流：Skills 注册表、MCP 服务器与配图能力状态。"""
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


def build_settings_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """系统设置：只读展示配置状态，不显示任何密钥值。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    settings = container.settings
    context["system"] = {
        "app_env": settings.app_env,
        "timezone": str(settings.timezone),
        "business_timezone": settings.business_timezone,
        "model": {
            "provider": settings.text_model_provider,
            "name": settings.deepseek_model,
            "configured": settings.deepseek_api_key is not None,
        },
        "wechat": {
            "account": settings.wechat_account_name,
            "configured": bool(settings.wechat_app_id and settings.wechat_app_secret),
            "draft_enabled": settings.wechat_draft_enabled,
            "auto_publish": False,
        },
        "images": {
            "ai_generation": settings.ai_image_generation_available,
            "provider": settings.image_model_provider,
            "web_search": settings.web_image_search_available,
        },
        "limits": {
            "upload_max_mb": round(settings.metrics_upload_max_bytes / 1024 / 1024, 1),
        },
        "skills_count": len(container.skills.discover()),
        "mcp_count": len(container.mcp.snapshot()),
    }
    return context
