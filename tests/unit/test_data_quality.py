from __future__ import annotations

from app.domain.models import MetricRecord
from app.services.analytics.quality import build_quality_report


def test_quality_report_detects_duplicate_missing_and_negative_values():
    records = [
        MetricRecord(
            metric_date="2026-07-17T00:00:00+08:00",
            article_id="a-1",
            article_title="",
            reads=100,
            shares=5,
            favorites=3,
            followers_gained=2,
            source_type="csv",
            source_record_id="row-1",
        ),
        MetricRecord(
            metric_date="2026-07-17T00:00:00+08:00",
            article_id="a-1",
            article_title="",
            reads=-1,
            shares=5,
            favorites=3,
            followers_gained=2,
            source_type="csv",
            source_record_id="row-1",
        ),
    ]

    report = build_quality_report(records, now="2026-07-18T00:00:00+08:00")

    assert report.duplicate_count == 1
    assert report.missing_rates["article_title"] == 1.0
    assert report.anomaly_count == 1
    assert report.confidence < 0.8
    assert report.limitations
