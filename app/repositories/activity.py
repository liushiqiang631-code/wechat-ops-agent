from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ActivityLogRow
from app.domain.enums import Channel
from app.domain.models import ActivityLog


class ActivityLogRepository:
    """操作日志：真实操作落库，供「团队协作 → 操作日志」页回放。"""

    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def log(
        self,
        kind: str,
        title: str,
        *,
        detail: str | None = None,
        channel: Channel | str | None = None,
        ref_id: str | None = None,
    ) -> ActivityLog:
        row = ActivityLogRow(
            kind=kind,
            title=title[:200],
            detail=detail[:500] if detail else None,
            channel=channel.value if isinstance(channel, Channel) else channel,
            ref_id=ref_id[:80] if ref_id else None,
            created_at=datetime.now().astimezone(),
        )
        with self.sessions.begin() as session:
            session.add(row)
            session.flush()
            row_id = row.id
        return ActivityLog(
            id=row_id,
            kind=row.kind,
            title=row.title,
            detail=row.detail,
            channel=channel if isinstance(channel, Channel) else None,
            ref_id=row.ref_id,
            created_at=row.created_at,
        )

    def list(self, limit: int = 100) -> list[ActivityLog]:
        with self.sessions() as session:
            rows = (
                session.query(ActivityLogRow)
                .order_by(ActivityLogRow.created_at.desc(), ActivityLogRow.id.desc())
                .limit(limit)
                .all()
            )
            return [
                ActivityLog(
                    id=row.id,
                    kind=row.kind,
                    title=row.title,
                    detail=row.detail,
                    channel=Channel(row.channel) if row.channel else None,
                    ref_id=row.ref_id,
                    created_at=row.created_at,
                )
                for row in rows
            ]
