from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import VideoScriptRow
from app.domain.enums import Channel
from app.domain.models import ScriptBeat, VideoScript


def _now() -> datetime:
    return datetime.now().astimezone()


def _row_to_model(row: VideoScriptRow) -> VideoScript:
    return VideoScript(
        id=row.id,
        title=row.title,
        topic=row.topic,
        channel=Channel(row.channel),
        duration_seconds=row.duration_seconds,
        audience=row.audience,
        hook=row.hook,
        beats=[ScriptBeat.model_validate(item) for item in json.loads(row.beats_json)],
        ending=row.ending,
        cover_idea=row.cover_idea,
        hashtags=json.loads(row.hashtags_json),
        article_angle=row.article_angle,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        task_id=row.task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ScriptRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def create(self, script: VideoScript) -> VideoScript:
        now = _now()
        row = VideoScriptRow(
            id=script.id,
            title=script.title,
            topic=script.topic,
            channel=script.channel.value,
            duration_seconds=script.duration_seconds,
            audience=script.audience,
            hook=script.hook,
            beats_json=json.dumps(
                [beat.model_dump(mode="json") for beat in script.beats], ensure_ascii=False
            ),
            ending=script.ending,
            cover_idea=script.cover_idea,
            hashtags_json=json.dumps(script.hashtags, ensure_ascii=False),
            article_angle=script.article_angle,
            status=script.status,
            source=script.source,
            task_id=script.task_id,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return _row_to_model(row)

    def get(self, script_id: str) -> VideoScript | None:
        with self.sessions() as session:
            row = session.get(VideoScriptRow, script_id)
            return _row_to_model(row) if row else None

    def list(self, limit: int = 50) -> list[VideoScript]:
        with self.sessions() as session:
            rows = (
                session.query(VideoScriptRow)
                .order_by(VideoScriptRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_model(row) for row in rows]

    def mark_converted(self, script_id: str, task_id: str) -> VideoScript:
        with self.sessions.begin() as session:
            row = session.get(VideoScriptRow, script_id)
            if row is None:
                raise KeyError(script_id)
            row.status = "converted"
            row.task_id = task_id
            row.updated_at = _now()
            session.add(row)
        return _row_to_model(row)

    def delete(self, script_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(VideoScriptRow, script_id)
            if row is None:
                return False
            session.delete(row)
            return True
