from __future__ import annotations

from datetime import datetime

from app.domain.models import DataQualityReport, MetricRecord


def build_quality_report(
    records: list[MetricRecord], *, now: str | datetime | None = None
) -> DataQualityReport:
    reference = (
        datetime.fromisoformat(now) if isinstance(now, str) else now or datetime.now().astimezone()
    )
    total = len(records)
    fields = ("article_id", "article_title", "metric_date")
    missing = {
        field: (
            sum(not bool(getattr(record, field)) for record in records) / total if total else 0.0
        )
        for field in fields
    }
    seen: set[tuple[str, str, datetime]] = set()
    duplicate_count = 0
    anomaly_count = 0
    for record in records:
        key = (record.source_type, record.source_record_id, record.metric_date)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        if record.reads < 0:
            anomaly_count += 1
    latest = max((record.metric_date for record in records), default=None)
    delay = max((reference - latest).total_seconds() / 86400, 0) if latest is not None else None
    limitations: list[str] = []
    if total == 0:
        # No data at all: report a confidence of zero and an actionable hint,
        # rather than a misleading high confidence on nothing.
        return DataQualityReport(
            total_records=0,
            missing_rates=missing,
            duplicate_count=0,
            anomaly_count=0,
            delay_days=None,
            source_types=[],
            confidence=0.0,
            limitations=["尚未导入数据，先导入公众号导出数据后再判断质量"],
        )
    penalty = (
        sum(missing.values()) * 0.35
        + (duplicate_count / max(total, 1)) * 0.25
        + (anomaly_count / max(total, 1)) * 0.25
        + (0.15 if delay is None or delay > 3 else 0)
    )
    if total < 20:
        limitations.append("样本少于 20 条，趋势结论仅作弱信号")
    if any(missing.values()):
        limitations.append("存在关键字段缺失")
    if duplicate_count:
        limitations.append("存在重复记录，派生指标前应去重")
    if anomaly_count:
        limitations.append("存在负数或异常指标")
    return DataQualityReport(
        total_records=total,
        missing_rates=missing,
        duplicate_count=duplicate_count,
        anomaly_count=anomaly_count,
        delay_days=round(delay, 2) if delay is not None else None,
        source_types=sorted({record.source_type for record in records}),
        confidence=max(0.0, round(1.0 - penalty, 3)),
        limitations=limitations,
    )
