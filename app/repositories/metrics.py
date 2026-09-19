from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RawMetricRow
from app.domain.models import MetricRecord


class MetricsRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def insert(self, records: list[MetricRecord]) -> int:
        inserted = 0
        # The database uniqueness constraint only sees pending inserts on flush,
        # so duplicate rows in one uploaded file would otherwise fail the whole
        # transaction. Keep one snapshot for each source record before writing.
        unique_records = {
            (
                record.source_type,
                record.source_record_id,
                record.metric_date,
                "article_summary",
            ): record
            for record in records
        }
        with self.sessions.begin() as session:
            for record in unique_records.values():
                existing = (
                    session.query(RawMetricRow)
                    .filter_by(
                        source_type=record.source_type,
                        source_record_id=record.source_record_id,
                        metric_date=record.metric_date,
                        metric_name="article_summary",
                    )
                    .one_or_none()
                )
                values = {
                    "metric_value": str(record.reads),
                    "raw_json": record.model_dump_json(),
                    "imported_at": record.imported_at,
                }
                if existing is None:
                    session.add(
                        RawMetricRow(
                            source_type=record.source_type,
                            source_record_id=record.source_record_id,
                            metric_date=record.metric_date,
                            metric_name="article_summary",
                            **values,
                        )
                    )
                    inserted += 1
                else:
                    # Idempotent re-import: refresh the stored snapshot.
                    existing.metric_value = values["metric_value"]
                    existing.raw_json = values["raw_json"]
                    existing.imported_at = values["imported_at"]
        return inserted

    def list(self, limit: int = 10_000) -> list[MetricRecord]:
        with self.sessions() as session:
            rows = (
                session.query(RawMetricRow)
                .order_by(RawMetricRow.metric_date.asc())
                .limit(limit)
                .all()
            )
            return [MetricRecord.model_validate_json(row.raw_json) for row in rows]
