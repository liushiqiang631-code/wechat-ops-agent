"""全域内容运营平台的视图模型：发布中心、渠道、脚本、对比与团队协作页。

所有数字都来自本地数据库的真实记录；首启种入的示例数据同样落在这些表里，
因此页面计算路径与真实数据完全一致。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

from app.container import ApplicationContainer
from app.domain.enums import Channel, ChannelPostStatus, TaskStatus
from app.domain.models import ChannelPost, VideoScript

CHANNEL_PRESENTATION: dict[Channel, dict[str, str]] = {
    Channel.XIAOHONGSHU: {"label": "小红书", "color": "#ff2442"},
    Channel.SHIPINHAO: {"label": "视频号", "color": "#f79c38"},
    Channel.DOUYIN: {"label": "抖音", "color": "#1c1e27"},
    Channel.KUAISHOU: {"label": "快手", "color": "#ff6600"},
    Channel.WECHAT: {"label": "公众号", "color": "#07c160"},
}

STATUS_PRESENTATION_POST: dict[ChannelPostStatus, dict[str, str]] = {
    ChannelPostStatus.PUBLISHED: {"label": "已发布", "tone": "success"},
    ChannelPostStatus.PENDING_REVIEW: {"label": "待审核", "tone": "warning"},
    ChannelPostStatus.SCHEDULED: {"label": "待发布", "tone": "info"},
    ChannelPostStatus.DRAFT: {"label": "草稿", "tone": "neutral"},
    ChannelPostStatus.FAILED: {"label": "发布失败", "tone": "error"},
}

POST_ACTION_LABELS = {
    ChannelPostStatus.PUBLISHED: ("查看详情", "复制链接"),
    ChannelPostStatus.PENDING_REVIEW: ("审核内容", "编辑记录"),
    ChannelPostStatus.SCHEDULED: ("查看详情", "编辑记录"),
    ChannelPostStatus.DRAFT: ("继续编辑", "提交审核"),
    ChannelPostStatus.FAILED: ("查看详情", "重试发布"),
}

REVIEW_PENDING_STATUSES = {TaskStatus.FORMATTED, TaskStatus.NEEDS_HUMAN}

WEEKDAY_LABELS_OMNI = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def compact_number(value: int | float) -> str:
    value = int(value)
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿".rstrip("0").rstrip(".")
    if value >= 10_000:
        text = f"{value / 10_000:.1f}万"
        return text.replace(".0万", "万")
    return f"{value:,}"


def _display_time(post: ChannelPost) -> datetime:
    if post.status == ChannelPostStatus.PUBLISHED and post.published_at:
        return post.published_at
    if post.status == ChannelPostStatus.FAILED and post.published_at:
        return post.published_at
    if post.status == ChannelPostStatus.SCHEDULED and post.scheduled_at:
        return post.scheduled_at
    return post.created_at


def _aware(value: datetime, tz) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=tz)


def _cover_tone(post: ChannelPost) -> str:
    """由内容标识稳定派生封面色调，保证同一记录每次渲染结果一致。"""
    digest = hashlib.md5((post.cover_seed or post.id).encode(), usedforsecurity=False).hexdigest()
    return f"tone-{int(digest[:2], 16) % 6}"


def _ago(delta: timedelta) -> str:
    seconds = max(int(delta.total_seconds()), 60)
    if seconds < 3600:
        return f"{seconds // 60}分钟前"
    if seconds < 86_400:
        return f"{seconds // 3600}小时前"
    return f"{seconds // 86_400}天前"


def post_view(post: ChannelPost, *, now: datetime, tz) -> dict[str, object]:
    presentation = STATUS_PRESENTATION_POST[post.status]
    action_primary, action_secondary = POST_ACTION_LABELS[post.status]
    moment = _aware(_display_time(post), tz)
    published_label = ""
    if post.status == ChannelPostStatus.PUBLISHED and post.published_at:
        published_label = f"{_aware(post.published_at, tz):%m/%d %H:%M} 发布"
    elif post.status == ChannelPostStatus.FAILED and post.published_at:
        published_label = f"{_aware(post.published_at, tz):%m/%d %H:%M} 尝试发布"
    elif post.status == ChannelPostStatus.SCHEDULED and post.scheduled_at:
        published_label = f"计划 {_aware(post.scheduled_at, tz):%m/%d %H:%M} 发布"
    else:
        published_label = f"{_aware(post.created_at, tz):%m/%d %H:%M} 保存"
    return {
        "id": post.id,
        "channel": post.channel.value,
        "channel_label": CHANNEL_PRESENTATION[post.channel]["label"],
        "channel_color": CHANNEL_PRESENTATION[post.channel]["color"],
        "content_type": post.content_type,
        "category": post.category,
        "title": post.title,
        "excerpt": post.excerpt,
        "status": post.status.value,
        "status_label": presentation["label"],
        "status_tone": presentation["tone"],
        "cover_seed": post.cover_seed or post.id[:8],
        "cover_class": _cover_tone(post),
        "views": post.views,
        "likes": post.likes,
        "comments": post.comments,
        "shares": post.shares,
        "views_label": compact_number(post.views) if post.views else "—",
        "likes_label": compact_number(post.likes) if post.likes else "—",
        "comments_label": compact_number(post.comments) if post.comments else "—",
        "time_label": f"{moment:%H:%M}",
        "date_iso": f"{moment:%Y-%m-%d}",
        "ago_label": _ago(now - moment) if moment <= now else "计划中",
        "published_label": published_label,
        "action_primary": action_primary,
        "action_secondary": action_secondary,
        "can_publish": post.status in {ChannelPostStatus.PENDING_REVIEW, ChannelPostStatus.DRAFT},
        "can_retry": post.status == ChannelPostStatus.FAILED,
        "can_metrics": post.status == ChannelPostStatus.PUBLISHED,
        "last_error": post.last_error,
        "task_id": post.task_id,
        "script_id": post.script_id,
        "source": post.source,
    }


def _in_window(post: ChannelPost, start: datetime, end: datetime) -> bool:
    moment = _display_time(post)
    if moment.tzinfo is None:
        # SQLite 不保留时区；按统计窗口的时区解释本地时间。
        moment = moment.replace(tzinfo=start.tzinfo)
    return start <= moment < end


def publish_overview(
    posts: list[ChannelPost], *, reference: datetime
) -> dict[str, object]:
    """近 7 天发布概览：四类状态计数 + 环比 + 成功率（全部由真实记录计算）。"""
    window_start = reference - timedelta(days=6)
    window_start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = reference + timedelta(days=1)
    previous_start = window_start - timedelta(days=7)

    current = [post for post in posts if _in_window(post, window_start, window_end)]
    previous = [post for post in posts if _in_window(post, previous_start, window_start)]

    def _count(items: list[ChannelPost], status: ChannelPostStatus) -> int:
        return sum(1 for post in items if post.status == status)

    def _delta(label: str, now_value: int, prev_value: int) -> dict[str, object]:
        if now_value == 0 and prev_value == 0:
            return {"direction": "neutral", "text": "暂无数据"}
        if prev_value == 0:
            return {"direction": "neutral", "text": "上周无对比"}
        percent = (now_value - prev_value) / prev_value * 100
        direction = "up" if percent > 0 else "down" if percent < 0 else "flat"
        return {"direction": direction, "text": f"较上周 {percent:+.0f}%"}

    published = _count(current, ChannelPostStatus.PUBLISHED)
    pending = _count(current, ChannelPostStatus.PENDING_REVIEW)
    draft = _count(current, ChannelPostStatus.DRAFT)
    failed = _count(current, ChannelPostStatus.FAILED)
    attempts = published + failed
    success_rate = round(published / attempts * 100) if attempts else None
    # 排期中的内容属于「本周发布计划」，不计入发布概览与时间线。
    total = published + pending + draft + failed

    return {
        "range_label": f"{window_start:%Y/%m/%d} - {(window_end - timedelta(days=1)):%m/%d}",
        "cards": [
            {
                "key": "published",
                "label": "已发布",
                "value": published,
                **_delta("published", published, _count(previous, ChannelPostStatus.PUBLISHED)),
                "direction_good": "up",
            },
            {
                "key": "pending",
                "label": "待审核",
                "value": pending,
                **_delta("pending", pending, _count(previous, ChannelPostStatus.PENDING_REVIEW)),
                "direction_good": "down",
            },
            {
                "key": "draft",
                "label": "草稿",
                "value": draft,
                **_delta("draft", draft, _count(previous, ChannelPostStatus.DRAFT)),
                "direction_good": "flat",
            },
            {
                "key": "failed",
                "label": "发布失败",
                "value": failed,
                **_delta("failed", failed, _count(previous, ChannelPostStatus.FAILED)),
                "direction_good": "down",
            },
        ],
        "success_rate": success_rate,
        "attempts": attempts,
        "total": total,
    }


def publish_timeline(
    posts: list[ChannelPost], *, now: datetime, tz, limit_days: int = 14
) -> list[dict[str, object]]:
    """按天分组的发布记录时间线（新 → 旧）。"""
    views = [
        post_view(post, now=now, tz=tz)
        for post in sorted(
            posts, key=lambda post: _aware(_display_time(post), tz), reverse=True
        )
    ]
    grouped: dict[str, dict[str, object]] = {}
    for view in views:
        day = str(view["date_iso"])
        bucket = grouped.get(day)
        if bucket is None:
            date = datetime.strptime(day, "%Y-%m-%d").date()
            bucket = {
                "date_iso": day,
                "date_label": f"{date:%Y/%m/%d}",
                "weekday": WEEKDAY_LABELS_OMNI[date.weekday()],
                "entries": [],
            }
            grouped[day] = bucket
        bucket["entries"].append(view)  # type: ignore[union-attr]
        if len(grouped) >= limit_days:
            break
    return list(grouped.values())


def todo_items(
    container: ApplicationContainer, *, reference: datetime, limit: int = 6
) -> dict[str, object]:
    """待处理事项：真实流水线任务 + 渠道发布记录聚合。"""
    items: list[dict[str, object]] = []

    for task in container.tasks.list(limit=30):
        if task.status in REVIEW_PENDING_STATUSES:
            title = task.title_hint or task.topic or task.request[:36]
            items.append(
                {
                    "kind": "review",
                    "channel": "wechat",
                    "channel_label": CHANNEL_PRESENTATION[Channel.WECHAT]["label"],
                    "title": "公众号文章待审阅",
                    "detail": title,
                    "href": f"/review/{task.id}",
                    "ref_id": task.id,
                    "moment": _aware(task.updated_at, container.settings.timezone),
                }
            )

    for post in container.channels.list_posts(limit=120):
        moment = _aware(_display_time(post), container.settings.timezone)
        if post.status == ChannelPostStatus.PENDING_REVIEW:
            items.append(
                {
                    "kind": "post_review",
                    "channel": post.channel.value,
                    "channel_label": CHANNEL_PRESENTATION[post.channel]["label"],
                    "title": f"{CHANNEL_PRESENTATION[post.channel]['label']}内容待审核",
                    "detail": post.title,
                    "href": "/approvals",
                    "ref_id": post.id,
                    "moment": moment,
                }
            )
        elif post.status == ChannelPostStatus.FAILED:
            items.append(
                {
                    "kind": "post_failed",
                    "channel": post.channel.value,
                    "channel_label": CHANNEL_PRESENTATION[post.channel]["label"],
                    "title": f"{CHANNEL_PRESENTATION[post.channel]['label']}发布失败",
                    "detail": post.last_error or "可重试发布",
                    "href": "/approvals",
                    "ref_id": post.id,
                    "moment": moment,
                }
            )
        elif (
            post.status == ChannelPostStatus.SCHEDULED
            and post.scheduled_at
            and _aware(post.scheduled_at, container.settings.timezone) <= reference
        ):
            items.append(
                {
                    "kind": "post_due",
                    "channel": post.channel.value,
                    "channel_label": CHANNEL_PRESENTATION[post.channel]["label"],
                    "title": f"{CHANNEL_PRESENTATION[post.channel]['label']}内容到点待发布",
                    "detail": post.title,
                    "href": "/calendar",
                    "ref_id": post.id,
                    "moment": moment,
                }
            )

    # 人工审阅永远排在最前，其余按时间倒序。
    priority = {"review": 0, "post_review": 1, "post_failed": 2, "post_due": 3}
    items.sort(
        key=lambda item: (
            priority.get(item["kind"], 9),
            -item["moment"].timestamp(),  # type: ignore[union-attr]
        )
    )
    for item in items:
        moment = item.pop("moment")  # type: ignore[union-attr]
        item["ago_label"] = _ago(reference - moment)
    return {"entries": items[:limit], "total": len(items)}


def week_plan(
    container: ApplicationContainer, *, reference: datetime, limit: int = 6
) -> dict[str, object]:
    """本周发布计划：本周内待发布 / 待审核 / 草稿的排期视图。"""
    week_start = (reference - timedelta(days=reference.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    days = [
        {
            "weekday": "一二三四五六日"[index],
            "day": (week_start + timedelta(days=index)).day,
            "is_today": (week_start + timedelta(days=index)).date() == reference.date(),
        }
        for index in range(7)
    ]
    rows: list[dict[str, object]] = []
    for post in container.channels.list_posts(limit=200):
        if post.status not in {
            ChannelPostStatus.SCHEDULED,
            ChannelPostStatus.PENDING_REVIEW,
            ChannelPostStatus.DRAFT,
        }:
            continue
        moment = _aware(post.scheduled_at or post.created_at, container.settings.timezone)
        if not (week_start <= moment < week_end):
            continue
        rows.append(
            {
                "time_label": f"{moment:%H:%M}",
                "channel": post.channel.value,
                "channel_label": CHANNEL_PRESENTATION[post.channel]["label"],
                "channel_color": CHANNEL_PRESENTATION[post.channel]["color"],
                "format": post.content_type,
                "title": post.title,
                "status_label": STATUS_PRESENTATION_POST[post.status]["label"],
                "status_tone": STATUS_PRESENTATION_POST[post.status]["tone"],
                "moment": moment,
            }
        )
    rows.sort(key=lambda row: row["moment"])  # type: ignore[arg-type]
    for row in rows:
        row.pop("moment")
    return {
        "days": days,
        "rows": rows[:limit],
        "total": len(rows),
        "week_label": f"{week_start:%m/%d} - {(week_end - timedelta(days=1)):%m/%d}",
    }


def platform_performance(
    posts: list[ChannelPost], *, reference: datetime
) -> dict[str, object]:
    """各平台数据表现：近 7 天浏览量 + 环比，用于发布中心右栏与平台对比页。"""
    window_start = (reference - timedelta(days=6)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    window_end = reference + timedelta(days=1)
    previous_start = window_start - timedelta(days=7)

    def _views(items: list[ChannelPost], channel: Channel, start: datetime, end: datetime) -> int:
        return sum(
            post.views
            for post in items
            if post.channel == channel
            and post.status == ChannelPostStatus.PUBLISHED
            and post.published_at
            and start <= _aware(post.published_at, reference.tzinfo) < end
        )

    rows: list[dict[str, object]] = []
    for channel in Channel:
        current = _views(posts, channel, window_start, window_end)
        previous = _views(posts, channel, previous_start, window_start)
        if previous > 0:
            percent = (current - previous) / previous * 100
            change_text = f"{percent:+.0f}%"
            direction = "up" if percent > 0 else "down" if percent < 0 else "flat"
        elif current > 0:
            change_text = "上周无对比"
            direction = "neutral"
        else:
            change_text = "暂无数据"
            direction = "neutral"
        rows.append(
            {
                "channel": channel.value,
                "channel_label": CHANNEL_PRESENTATION[channel]["label"],
                "channel_color": CHANNEL_PRESENTATION[channel]["color"],
                "views": current,
                "views_label": compact_number(current) if current else "—",
                "change_text": change_text,
                "change_direction": direction,
            }
        )
    max_views = max((int(row["views"]) for row in rows), default=0) or 1
    for row in rows:
        row["bar_percent"] = round(int(row["views"]) / max_views * 100)  # type: ignore[arg-type]
    total = sum(int(row["views"]) for row in rows)
    return {
        "rows": sorted(rows, key=lambda row: int(row["views"]), reverse=True),  # type: ignore[arg-type]
        "total_label": compact_number(total),
    }


def script_view(script: VideoScript, *, tz) -> dict[str, object]:
    created = _aware(script.created_at, tz)
    minutes, seconds = divmod(script.duration_seconds, 60)
    return {
        "id": script.id,
        "title": script.title,
        "topic": script.topic,
        "channel": script.channel.value,
        "channel_label": CHANNEL_PRESENTATION[script.channel]["label"],
        "channel_color": CHANNEL_PRESENTATION[script.channel]["color"],
        "duration_label": f"{minutes}分{seconds:02d}秒" if minutes else f"{seconds} 秒",
        "duration_seconds": script.duration_seconds,
        "audience": script.audience,
        "hook": script.hook,
        "beats": [
            {
                "time_range": beat.time_range,
                "shot": beat.shot,
                "voiceover": beat.voiceover,
                "on_screen_text": beat.on_screen_text,
            }
            for beat in script.beats
        ],
        "ending": script.ending,
        "cover_idea": script.cover_idea,
        "hashtags": script.hashtags,
        "article_angle": script.article_angle,
        "status": script.status,
        "status_label": "已转写文章" if script.status == "converted" else "草稿",
        "source": script.source,
        "source_label": {"model": "AI 生成", "manual": "手动录入", "demo": "示例"}.get(
            script.source, script.source
        ),
        "task_id": script.task_id,
        "voiceover_text": script.voiceover_text,
        "created_label": f"{created:%m-%d %H:%M}",
    }


def engagement_rate(post: ChannelPost) -> float:
    if post.views <= 0:
        return 0.0
    return (post.likes + post.comments + post.shares + post.favorites) / post.views * 100


# ---------------------------------------------------------------------------
# 页面级 context 组装
# ---------------------------------------------------------------------------

from app.web.view_models import _base_context  # noqa: E402


def _parse_filters(
    channel: str | None, status: str | None
) -> tuple[Channel | None, ChannelPostStatus | None]:
    try:
        channel_filter = Channel(channel) if channel and channel != "all" else None
    except ValueError:
        channel_filter = None
    try:
        status_filter = (
            ChannelPostStatus(status) if status and status != "all" else None
        )
    except ValueError:
        status_filter = None
    return channel_filter, status_filter


def build_publish_context(
    container: ApplicationContainer,
    *,
    channel: str | None = None,
    status: str | None = None,
    q: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """发布中心（首页）：概览 + 筛选 + 时间线 + 右栏三卡片。"""
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    channel_filter, status_filter = _parse_filters(channel, status)
    posts = container.channels.list_posts(limit=500)
    overview = publish_overview(posts, reference=reference)

    visible = [post for post in posts if post.status != ChannelPostStatus.SCHEDULED]
    if channel_filter is not None:
        visible = [post for post in visible if post.channel == channel_filter]
    if status_filter is not None:
        visible = [post for post in visible if post.status == status_filter]
    if q:
        keyword = q.strip()
        visible = [
            post
            for post in visible
            if keyword in post.title or keyword in post.excerpt or keyword in post.category
        ]

    def _chip_href(status_key: str) -> str:
        params: dict[str, str] = {}
        if status_key != "all":
            params["status"] = status_key
        if channel_filter is not None:
            params["channel"] = channel_filter.value
        if q and q.strip():
            params["q"] = q.strip()
        query = "&".join(f"{key}={quote_plus(value)}" for key, value in params.items())
        return f"/?{query}" if query else "/"

    chips = [
        {"key": "all", "label": "全部渠道", "count": overview["total"], "href": _chip_href("all")},
        {
            "key": ChannelPostStatus.PUBLISHED.value,
            "label": "已发布",
            "count": next(c["value"] for c in overview["cards"] if c["key"] == "published"),
            "href": _chip_href(ChannelPostStatus.PUBLISHED.value),
        },
        {
            "key": ChannelPostStatus.PENDING_REVIEW.value,
            "label": "待审核",
            "count": next(c["value"] for c in overview["cards"] if c["key"] == "pending"),
            "href": _chip_href(ChannelPostStatus.PENDING_REVIEW.value),
        },
        {
            "key": ChannelPostStatus.DRAFT.value,
            "label": "草稿",
            "count": next(c["value"] for c in overview["cards"] if c["key"] == "draft"),
            "href": _chip_href(ChannelPostStatus.DRAFT.value),
        },
        {
            "key": ChannelPostStatus.FAILED.value,
            "label": "失败",
            "count": next(c["value"] for c in overview["cards"] if c["key"] == "failed"),
            "href": _chip_href(ChannelPostStatus.FAILED.value),
        },
    ]
    active_chip = status_filter.value if status_filter else "all"

    context.update(
        {
            "overview": overview,
            "chips": chips,
            "active_chip": active_chip,
            "active_channel": channel or "all",
            "search_query": (q or "").strip(),
            "timeline": publish_timeline(visible, now=reference, tz=tz),
            "timeline_count": len(visible),
            "todos": todo_items(container, reference=reference),
            "week_plan": week_plan(container, reference=reference),
            "performance": platform_performance(posts, reference=reference),
            "channel_options": [
                {
                    "key": key.value,
                    "label": CHANNEL_PRESENTATION[key]["label"],
                    "color": CHANNEL_PRESENTATION[key]["color"],
                }
                for key in Channel
            ],
        }
    )
    return context


def build_channels_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """渠道管理：五个渠道固定成卡；未接入的渠道留空占位，接入后自动填充。"""
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    posts = container.channels.list_posts(limit=500)
    performance = platform_performance(posts, reference=reference)
    by_channel = {row["channel"]: row for row in performance["rows"]}  # type: ignore[index]
    accounts = {account.key: account for account in container.channels.list_accounts()}
    rows: list[dict[str, object]] = []
    for channel in Channel:
        account = accounts.get(channel)
        perf = by_channel.get(channel.value, {})
        connected = account is not None
        rows.append(
            {
                "key": channel.value,
                "channel_label": CHANNEL_PRESENTATION[channel]["label"],
                "channel_color": CHANNEL_PRESENTATION[channel]["color"],
                "connected": connected,
                "display_name": account.display_name if account else "",
                "handle": account.handle if account else "",
                "account_type": account.account_type if account else "",
                "status": account.status if account else "not_connected",
                "status_label": (
                    ("运营中" if account.status == "active" else "已暂停")
                    if account
                    else "未接入"
                ),
                "followers_label": (
                    compact_number(account.followers) if account else "—"
                ),
                "views_7d": perf.get("views_label", "—") if perf.get("views") else "—",
                "change_text": (
                    perf.get("change_text", "暂无数据") if perf.get("views") else "暂无数据"
                ),
                "change_direction": perf.get("change_direction", "neutral"),
            }
        )
    context["channels_page"] = {
        "rows": rows,
        "model_configured": container.settings.deepseek_api_key is not None,
    }
    return context


def build_channel_detail_context(
    container: ApplicationContainer,
    key: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """单渠道页：已接入显示账号信息与统计，未接入则整体留占位。"""
    try:
        channel = Channel(key)
    except ValueError:
        return None
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    account = container.channels.get_account(channel)
    posts = container.channels.list_posts(channel=channel, limit=100)
    published = [post for post in posts if post.status == ChannelPostStatus.PUBLISHED]
    views_7d = 0
    engagement = 0.0
    published_30d = 0
    if posts:
        window_start = reference - timedelta(days=6)
        views_7d = sum(
            post.views
            for post in published
            if post.published_at and _aware(post.published_at, tz) >= window_start
        )
        engagement = (
            sum(engagement_rate(post) for post in published) / len(published)
            if published
            else 0.0
        )
        published_30d = sum(
            1
            for post in published
            if post.published_at
            and _aware(post.published_at, tz) >= reference - timedelta(days=30)
        )
    has_posts = bool(posts)
    context["channel_page"] = {
        "key": channel.value,
        "label": CHANNEL_PRESENTATION[channel]["label"],
        "color": CHANNEL_PRESENTATION[channel]["color"],
        "connected": account is not None,
        "display_name": account.display_name if account else "",
        "handle": account.handle if account else "",
        "account_type": account.account_type if account else "",
        "status": account.status if account else "not_connected",
        "status_label": (
            ("运营中" if account.status == "active" else "已暂停")
            if account
            else "未接入"
        ),
        "followers_label": compact_number(account.followers) if account else "—",
        "views_7d": compact_number(views_7d) if views_7d else "—",
        "published_30d": published_30d if has_posts else None,
        "engagement_label": f"{engagement:.1f}%" if published else "—",
        "posts": [
            post_view(post, now=reference, tz=tz) for post in posts[:20]
        ],
        "total": len(posts),
    }
    return context


def build_scripts_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """脚本生成：脚本列表 + 生成表单所需状态。"""
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    scripts = container.scripts.list(limit=30)
    context["scripts_page"] = {
        "rows": [script_view(script, tz=tz) for script in scripts],
        "total": len(scripts),
        "model": {
            "configured": container.settings.deepseek_api_key is not None,
            "name": container.settings.deepseek_model,
        },
        "channel_options": [
            {"key": key.value, "label": CHANNEL_PRESENTATION[key]["label"]}
            for key in (Channel.SHIPINHAO, Channel.DOUYIN, Channel.KUAISHOU, Channel.XIAOHONGSHU)
        ],
    }
    return context


def build_performance_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """内容表现：近 30 天已发布内容的浏览排名。"""
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    posts = container.channels.list_posts(limit=500)
    published = [
        post
        for post in posts
        if post.status == ChannelPostStatus.PUBLISHED
        and post.published_at
        and _aware(post.published_at, tz) >= reference - timedelta(days=30)
    ]
    published.sort(key=lambda post: post.views, reverse=True)
    total_views = sum(post.views for post in published)
    context["performance_page"] = {
        "rows": [
            {
                "rank": index + 1,
                **post_view(post, now=reference, tz=tz),
                "engagement_label": f"{engagement_rate(post):.1f}%",
            }
            for index, post in enumerate(published[:20])
        ],
        "total": len(published),
        "total_views_label": compact_number(total_views) if published else "—",
        "avg_views_label": compact_number(total_views / len(published)) if published else "—",
    }
    return context


def engagement_rate_batch(posts: list[ChannelPost]) -> float:
    views = sum(post.views for post in posts)
    if views <= 0:
        return 0.0
    interactions = sum(
        post.likes + post.comments + post.shares + post.favorites for post in posts
    )
    return interactions / views * 100


def build_compare_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """平台对比：近 30 天各渠道核心指标横向对比。"""
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    posts = container.channels.list_posts(limit=500)
    window_start = reference - timedelta(days=29)
    rows: list[dict[str, object]] = []
    for channel in Channel:
        published = [
            post
            for post in posts
            if post.channel == channel
            and post.status == ChannelPostStatus.PUBLISHED
            and post.published_at
            and _aware(post.published_at, tz) >= window_start
        ]
        views = sum(post.views for post in published)
        likes = sum(post.likes for post in published)
        comments = sum(post.comments for post in published)
        rows.append(
            {
                "channel": channel.value,
                "channel_label": CHANNEL_PRESENTATION[channel]["label"],
                "channel_color": CHANNEL_PRESENTATION[channel]["color"],
                "posts": len(published),
                "views": views,
                "views_label": compact_number(views) if views else "—",
                "likes_label": compact_number(likes) if likes else "—",
                "comments_label": compact_number(comments) if comments else "—",
                "avg_views_label": compact_number(views / len(published)) if published else "—",
                "engagement_label": (
                    f"{engagement_rate_batch(published):.1f}%" if published else "—"
                ),
            }
        )
    max_views = max((int(row["views"]) for row in rows), default=0) or 1
    for row in rows:
        row["bar_percent"] = round(int(row["views"]) / max_views * 100)  # type: ignore[arg-type]
    context["compare_page"] = {"rows": rows}
    return context


def build_team_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """团队成员：本地单运营者 + 角色说明（不做虚构成员）。"""
    reference = now or datetime.now(container.settings.timezone)
    context = _base_context(container, reference=reference)
    context["team_page"] = {
        "operator": container.settings.operator_name,
        "team": container.settings.team_name,
        "role": "管理员",
    }
    return context


def build_approvals_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """审批流程：待审阅写稿任务 + 待审核发布记录 + 失败重试。"""
    from app.web.view_models import task_view

    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    task_rows = []
    for task in container.tasks.list(limit=30):
        if task.status in REVIEW_PENDING_STATUSES:
            view = task_view(task)
            task_rows.append(
                {
                    "task_id": task.id,
                    "title": view["title"],
                    "status_label": view["status_label"],
                    "updated_label": view["updated_label"],
                }
            )
    post_rows = []
    for post in container.channels.list_posts(limit=200):
        if post.status in {ChannelPostStatus.PENDING_REVIEW, ChannelPostStatus.FAILED}:
            view = post_view(post, now=reference, tz=tz)
            view["action_primary"] = (
                "确认发布"
                if post.status == ChannelPostStatus.PENDING_REVIEW
                else "重试发布"
            )
            post_rows.append(view)
    context["approvals_page"] = {
        "tasks": task_rows,
        "posts": post_rows,
        "task_count": len(task_rows),
        "post_count": len(post_rows),
    }
    return context


LOG_KIND_LABELS = {
    "seed": "初始化",
    "channel_update": "渠道管理",
    "post_create": "发布登记",
    "post_publish": "确认发布",
    "post_retry": "重试发布",
    "post_metrics": "效果回流",
    "post_delete": "删除记录",
    "script_generate": "生成脚本",
    "script_manual": "录入脚本",
    "script_to_article": "脚本转文章",
    "script_to_post": "脚本转内容",
    "script_delete": "删除脚本",
}


def build_logs_context(
    container: ApplicationContainer, *, now: datetime | None = None
) -> dict[str, Any]:
    """操作日志：真实操作流水。"""
    tz = container.settings.timezone
    reference = now or datetime.now(tz)
    context = _base_context(container, reference=reference)
    logs = container.activity.list(limit=120)
    context["logs_page"] = {
        "rows": [
            {
                "id": log.id,
                "kind": log.kind,
                "kind_label": LOG_KIND_LABELS.get(log.kind, log.kind),
                "title": log.title,
                "detail": log.detail,
                "channel": log.channel.value if log.channel else None,
                "channel_label": CHANNEL_PRESENTATION[log.channel]["label"] if log.channel else "",
                "channel_color": CHANNEL_PRESENTATION[log.channel]["color"] if log.channel else "",
                "time_label": f"{_aware(log.created_at, tz):%m-%d %H:%M}",
            }
            for log in logs
        ],
        "total": len(logs),
    }
    return context
