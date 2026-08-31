from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.models import MetricRecord, TopicRecord

if TYPE_CHECKING:
    from app.container import ApplicationContainer

_PUNCT = re.compile(r"[\s，。、：；！？,.!?；:（）()【】\[\]\"'“”\-—–]+")


def normalize_title(title: str) -> str:
    return _PUNCT.sub("", title).lower()


def _title_candidates(container: ApplicationContainer, task_id: str) -> list[str]:
    """Ordered candidate titles for a task: chosen hint, topic, generated title."""
    task = container.tasks.get(task_id)
    candidates = []
    if task.title_hint:
        candidates.append(task.title_hint)
    if task.topic:
        candidates.append(task.topic)
    try:
        article = container.artifacts.read_json(task_id, "article")
    except FileNotFoundError:
        article = {}
    selected = article.get("selected_title") if isinstance(article, dict) else None
    if selected:
        candidates.append(str(selected))
    return candidates


def _matching_records(records: list[MetricRecord], candidates: list[str]) -> list[MetricRecord]:
    normalized = [normalize_title(candidate) for candidate in candidates if candidate]
    if not normalized:
        return []
    matched: list[MetricRecord] = []
    for record in records:
        title = normalize_title(record.article_title or "")
        if not title:
            continue
        if any(target and (target in title or title in target) for target in normalized):
            matched.append(record)
    return matched


def backfill_published_metrics(container: ApplicationContainer, task_id: str) -> TopicRecord:
    """Link a published task to its imported metrics by title and store measured totals.

    Matching is best-effort by normalized title; a published article usually spans
    several daily rows, which are summed. Returns the updated TopicRecord.
    """
    try:
        publication = container.publications.get_by_task(task_id)
    except KeyError as exc:
        raise ValueError("该任务尚未登记发布") from exc
    topic = container.topic_records.get(task_id)
    candidates = _title_candidates(container, task_id)
    records = container.metrics.list()
    matched = _matching_records(records, candidates)
    if not matched:
        raise ValueError("未能在导入指标中匹配到该文章的标题")
    now = datetime.now(container.settings.timezone)
    topic.reads = sum(record.reads for record in matched if record.reads >= 0)
    topic.shares = sum(record.shares for record in matched)
    topic.favorites = sum(record.favorites for record in matched)
    topic.followers_gained = sum(record.followers_gained for record in matched)
    topic.published_at = publication.published_at
    topic.article_url = str(publication.article_url)
    topic.measured_at = now
    return container.topic_records.upsert(topic)


def sync_topic_record_from(publications, topic_records, task) -> TopicRecord:
    """Record or refresh the topic performance row for a task from repositories.

    Existing measured metrics (reads/shares/favorites/followers/measured_at) are
    preserved so re-syncing never wipes backfilled performance data.
    """
    try:
        existing = topic_records.get(task.id)
    except KeyError:
        existing = None
    record = TopicRecord(
        task_id=task.id,
        topic=task.topic or task.request[:80],
        mode=task.mode,
        created_at=existing.created_at if existing is not None else task.created_at,
        published_at=existing.published_at if existing is not None else None,
        article_url=existing.article_url if existing is not None else None,
        reads=existing.reads if existing is not None else None,
        shares=existing.shares if existing is not None else None,
        favorites=existing.favorites if existing is not None else None,
        followers_gained=existing.followers_gained if existing is not None else None,
        measured_at=existing.measured_at if existing is not None else None,
    )
    try:
        publication = publications.get_by_task(task.id)
        record.published_at = publication.published_at
        record.article_url = str(publication.article_url)
    except KeyError:
        pass
    return topic_records.upsert(record)


def sync_topic_record(container: ApplicationContainer, task) -> TopicRecord:
    """Record or refresh the topic performance row for a task."""
    return sync_topic_record_from(container.publications, container.topic_records, task)
