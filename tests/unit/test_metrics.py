from __future__ import annotations

from app.domain.models import MetricRecord
from app.services.analytics.metrics import calculate_windows


def test_windows_calculate_exact_7_30_90_day_summaries():
    records = [
        MetricRecord(
            metric_date=f"2026-07-{day:02d}T00:00:00+08:00",
            article_id=f"a-{day}",
            article_title=f"Article {day}",
            reads=day,
            shares=1,
            favorites=2,
            followers_gained=1,
            source_type="api",
            source_record_id=f"row-{day}",
        )
        for day in range(1, 18)
    ]

    windows = calculate_windows(records, as_of="2026-07-18T00:00:00+08:00")

    assert windows["7d"].article_count == 7
    assert windows["7d"].reads == sum(range(11, 18))
    assert windows["30d"].article_count == 17
    assert windows["90d"].favorites == 34
