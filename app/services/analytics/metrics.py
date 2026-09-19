from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.models import MetricRecord, MetricWindow


def calculate_windows(
    records: list[MetricRecord], *, as_of: str | datetime | None = None
) -> dict[str, MetricWindow]:
    reference = (
        datetime.fromisoformat(as_of)
        if isinstance(as_of, str)
        else as_of or datetime.now().astimezone()
    )
    result: dict[str, MetricWindow] = {}
    for days in (7, 30, 90):
        start = reference - timedelta(days=days)
        selected = [record for record in records if start <= record.metric_date < reference]
        article_ids = {record.article_id for record in selected}
        reads = sum(record.reads for record in selected if record.reads >= 0)
        result[f"{days}d"] = MetricWindow(
            period=f"{days}d",
            article_count=len(article_ids),
            reads=reads,
            shares=sum(record.shares for record in selected),
            favorites=sum(record.favorites for record in selected),
            followers_gained=sum(record.followers_gained for record in selected),
            read_per_article=round(reads / len(article_ids), 2) if article_ids else 0.0,
        )
    return result
