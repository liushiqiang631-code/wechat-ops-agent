from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import SkillStateRow


class SkillStateRepository:
    """Persists which skills the operator has enabled/disabled."""

    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def get(self, name: str) -> bool | None:
        with self.sessions() as session:
            row = session.get(SkillStateRow, name)
            return row.enabled if row is not None else None

    def set(self, name: str, enabled: bool) -> None:
        with self.sessions.begin() as session:
            row = session.get(SkillStateRow, name)
            if row is None:
                session.add(
                    SkillStateRow(
                        name=name,
                        enabled=enabled,
                        updated_at=datetime.now().astimezone(),
                    )
                )
            else:
                row.enabled = enabled
                row.updated_at = datetime.now().astimezone()
                session.add(row)

    def all(self) -> dict[str, bool]:
        with self.sessions() as session:
            rows = session.query(SkillStateRow).all()
            return {row.name: row.enabled for row in rows}
