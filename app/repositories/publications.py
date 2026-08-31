from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import DraftReceiptRow, PublicationRow, TaskRow, TopicRecordRow
from app.domain.enums import EvidenceType, TaskStatus
from app.domain.models import DraftReceipt, PublicationRecord


class PublicationRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    @staticmethod
    def _receipt_model(row: DraftReceiptRow) -> DraftReceipt:
        return DraftReceipt(
            idempotency_key=row.idempotency_key,
            task_id=row.task_id,
            media_id=row.media_id,
            content_hash=row.content_hash,
            evidence_type=EvidenceType(row.evidence_type),
            created_at=row.created_at,
        )

    def save_draft_receipt(self, receipt: DraftReceipt) -> DraftReceipt:
        with self.sessions.begin() as session:
            existing = (
                session.query(DraftReceiptRow)
                .filter_by(idempotency_key=receipt.idempotency_key)
                .one_or_none()
            )
            if existing is not None:
                return self._receipt_model(existing)
            row = DraftReceiptRow(
                idempotency_key=receipt.idempotency_key,
                task_id=receipt.task_id,
                media_id=receipt.media_id,
                content_hash=receipt.content_hash,
                evidence_type=receipt.evidence_type.value,
                created_at=receipt.created_at,
            )
            session.add(row)
        return self._receipt_model(row)

    def get_draft_receipt(self, idempotency_key: str) -> DraftReceipt:
        with self.sessions() as session:
            row = (
                session.query(DraftReceiptRow)
                .filter_by(idempotency_key=idempotency_key)
                .one_or_none()
            )
            if row is None:
                raise KeyError(idempotency_key)
            return self._receipt_model(row)

    def register(self, publication: PublicationRecord) -> PublicationRecord:
        with self.sessions.begin() as session:
            row = session.get(PublicationRow, publication.task_id)
            values = publication.model_dump()
            values["article_url"] = str(publication.article_url)
            if row is None:
                row = PublicationRow(**values)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.add(row)
        return publication

    def register_published(self, publication: PublicationRecord) -> PublicationRecord:
        """Register publication, task status and topic feedback in one transaction."""

        with self.sessions.begin() as session:
            task = session.get(TaskRow, publication.task_id)
            if task is None:
                raise KeyError(publication.task_id)
            if TaskStatus(task.status) != TaskStatus.HUMAN_REVIEWED:
                raise ValueError(f"task is not human reviewed: {task.status}")
            values = publication.model_dump()
            values["article_url"] = str(publication.article_url)
            row = session.get(PublicationRow, publication.task_id)
            if row is None:
                row = PublicationRow(**values)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.add(row)

            task.status = TaskStatus.PUBLISHED.value
            task.updated_at = datetime.now().astimezone()
            session.add(task)

            topic = session.get(TopicRecordRow, publication.task_id)
            if topic is None:
                topic = TopicRecordRow(
                    task_id=task.id,
                    topic=task.topic or task.request[:80],
                    mode=task.mode,
                    created_at=task.created_at,
                )
            topic.published_at = publication.published_at
            topic.article_url = str(publication.article_url)
            session.add(topic)
        return publication

    def get_by_task(self, task_id: str) -> PublicationRecord:
        with self.sessions() as session:
            row = session.get(PublicationRow, task_id)
            if row is None:
                raise KeyError(task_id)
            return PublicationRecord(
                task_id=row.task_id,
                article_url=row.article_url,
                published_at=row.published_at,
                draft_media_id=row.draft_media_id,
                final_content_hash=row.final_content_hash,
            )
