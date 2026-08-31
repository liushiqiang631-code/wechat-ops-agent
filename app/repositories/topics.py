from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import TopicRecordRow
from app.domain.enums import TaskMode
from app.domain.models import TopicRecord


class TopicRecordRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    @staticmethod
    def _to_model(row: TopicRecordRow) -> TopicRecord:
        return TopicRecord(
            task_id=row.task_id,
            topic=row.topic,
            mode=TaskMode(row.mode),
            created_at=row.created_at,
            published_at=row.published_at,
            article_url=row.article_url,
            reads=row.reads,
            shares=row.shares,
            favorites=row.favorites,
            followers_gained=row.followers_gained,
            measured_at=row.measured_at,
        )

    def upsert(self, record: TopicRecord) -> TopicRecord:
        with self.sessions.begin() as session:
            row = session.get(TopicRecordRow, record.task_id)
            if row is None:
                row = TopicRecordRow(
                    task_id=record.task_id,
                    topic=record.topic,
                    mode=record.mode.value,
                    created_at=record.created_at,
                    published_at=record.published_at,
                    article_url=record.article_url,
                    reads=record.reads,
                    shares=record.shares,
                    favorites=record.favorites,
                    followers_gained=record.followers_gained,
                    measured_at=record.measured_at,
                )
                session.add(row)
            else:
                row.topic = record.topic
                row.mode = record.mode.value
                row.published_at = record.published_at
                row.article_url = record.article_url
                row.reads = record.reads
                row.shares = record.shares
                row.favorites = record.favorites
                row.followers_gained = record.followers_gained
                row.measured_at = record.measured_at
        return self._to_model(row)

    def get(self, task_id: str) -> TopicRecord:
        with self.sessions() as session:
            row = session.get(TopicRecordRow, task_id)
            if row is None:
                raise KeyError(task_id)
            return self._to_model(row)

    def delete(self, task_id: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(TopicRecordRow, task_id)
            if row is not None:
                session.delete(row)

    def list_published(self, limit: int = 50) -> list[TopicRecord]:
        with self.sessions() as session:
            rows = (
                session.query(TopicRecordRow)
                .filter(TopicRecordRow.published_at.is_not(None))
                .order_by(TopicRecordRow.published_at.desc())
                .limit(limit)
                .all()
            )
            return [self._to_model(row) for row in rows]
