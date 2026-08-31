from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.container import ApplicationContainer
from app.domain.enums import TaskMode
from app.domain.models import TaskConstraints, TaskSpec
from app.services.analytics.importers import wechat_day_to_metrics
from app.services.wechat.client import WeChatAPIError

SYNC_WINDOW_DAYS = 7


async def _sync_recent_wechat_metrics(container: ApplicationContainer) -> dict:
    """Fetch recent WeChat datacube days and insert them as source_type='api' records."""
    token = await container.token_manager.get()
    tz = container.settings.timezone
    end = (datetime.now(tz) - timedelta(days=1)).date()
    begin = end - timedelta(days=SYNC_WINDOW_DAYS - 1)
    inserted = 0
    failed_days: list[dict[str, object]] = []
    for offset in range((end - begin).days + 1):
        day = (begin + timedelta(days=offset)).isoformat()
        try:
            user = await container.wechat_analytics.fetch_user_range(token, day, day)
            article = await container.wechat_analytics.fetch_article_day(token, day)
            records = wechat_day_to_metrics(
                user.get("list", []),
                article.get("list", []),
                timezone=container.settings.business_timezone,
            )
            inserted += container.metrics.insert(records)
        except WeChatAPIError as error:
            failed_days.append({"day": day, "code": error.code, "action": error.operator_action})
    return {
        "ran_at": datetime.now(tz).isoformat(),
        "window_days": SYNC_WINDOW_DAYS,
        "inserted_records": inserted,
        "failed_days": failed_days,
        "action": "synced" if not failed_days else "partial_sync",
        "record_count": len(container.metrics.list()),
    }


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def audit_daily_metrics(container: ApplicationContainer) -> dict:
    """Daily audit; attempts a real WeChat sync when credentials are configured."""
    configured = bool(container.settings.wechat_app_id and container.settings.wechat_app_secret)
    if configured:
        if _in_event_loop():
            # Called from inside a running loop (e.g. tests): audit only.
            payload = {
                "ran_at": datetime.now(container.settings.timezone).isoformat(),
                "record_count": len(container.metrics.list()),
                "action": "no_remote_sync",
                "reason": "already_in_event_loop",
            }
        else:
            try:
                payload = asyncio.run(_sync_recent_wechat_metrics(container))
            except Exception as error:
                payload = {
                    "ran_at": datetime.now(container.settings.timezone).isoformat(),
                    "record_count": len(container.metrics.list()),
                    "action": "sync_failed",
                    "error": f"{type(error).__name__}: {error}",
                }
    else:
        payload = {
            "ran_at": datetime.now(container.settings.timezone).isoformat(),
            "record_count": len(container.metrics.list()),
            "action": "no_remote_sync",
            "reason": "wechat_not_configured",
        }
    container.artifacts.write_json("scheduler", "daily_metrics_audit", payload)
    return payload


def prepare_weekly_plan(container: ApplicationContainer) -> str:
    task = container.tasks.create(
        TaskSpec(
            mode=TaskMode.WEEKLY_PLAN,
            request="复盘最近数据，安排热点、工程深度和源码实战三篇文章，并准备第一篇草稿。",
            constraints=TaskConstraints(
                auto_push_to_draft=False,
                auto_publish=False,
                inline_image_count=3,
            ),
        )
    )
    return task.id


def build_scheduler(container: ApplicationContainer) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=container.settings.business_timezone)
    scheduler.add_job(
        audit_daily_metrics,
        "cron",
        hour=2,
        minute=15,
        id="daily_metrics_audit",
        replace_existing=True,
        args=[container],
    )
    scheduler.add_job(
        prepare_weekly_plan,
        "cron",
        day_of_week="mon",
        hour=8,
        minute=30,
        id="weekly_content_plan",
        replace_existing=True,
        args=[container],
    )
    return scheduler
