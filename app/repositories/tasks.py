from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import TaskRow
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import TaskConstraints, TaskRecord, TaskSpec


class TaskRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    @staticmethod
    def _to_model(row: TaskRow) -> TaskRecord:
        return TaskRecord(
            id=row.id,
            mode=TaskMode(row.mode),
            request=row.request,
            topic=row.topic,
            title_hint=row.title_hint,
            plan_id=row.plan_id,
            constraints=TaskConstraints.model_validate_json(row.constraints_json),
            created_at=row.created_at,
            updated_at=row.updated_at,
            status=TaskStatus(row.status),
            last_error=row.last_error,
        )

    def create(self, task: TaskSpec) -> TaskRecord:
        now = datetime.now().astimezone()
        row = TaskRow(
            id=task.id,
            mode=task.mode.value,
            request=task.request,
            topic=task.topic,
            title_hint=task.title_hint,
            plan_id=task.plan_id,
            constraints_json=task.constraints.model_dump_json(),
            status=TaskStatus.CREATED.value,
            created_at=task.created_at,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return self._to_model(row)

    def get(self, task_id: str) -> TaskRecord:
        with self.sessions() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            return self._to_model(row)

    def delete(self, task_id: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            session.delete(row)

    def list(self, limit: int = 100) -> list[TaskRecord]:
        with self.sessions() as session:
            rows = session.query(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit).all()
            return [self._to_model(row) for row in rows]

    def list_by_plan(self, plan_id: str) -> list[TaskRecord]:
        with self.sessions() as session:
            rows = (
                session.query(TaskRow)
                .filter_by(plan_id=plan_id)
                .order_by(TaskRow.created_at.asc())
                .all()
            )
            return [self._to_model(row) for row in rows]

    def list_by_mode(self, mode: TaskMode, limit: int = 10) -> list[TaskRecord]:
        with self.sessions() as session:
            rows = (
                session.query(TaskRow)
                .filter_by(mode=mode.value)
                .order_by(TaskRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._to_model(row) for row in rows]

    def set_title_hint(self, task_id: str, title: str) -> TaskRecord:
        with self.sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            row.title_hint = title
            row.updated_at = datetime.now().astimezone()
            session.add(row)
        return self._to_model(row)

    def transition(
        self, task_id: str, target: TaskStatus, *, last_error: str | None = None
    ) -> TaskRecord:
        with self.sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row.status)
            if not current.can_transition_to(target):
                raise ValueError(f"invalid task transition: {current} -> {target}")
            row.status = target.value
            row.updated_at = datetime.now().astimezone()
            row.last_error = last_error
            session.add(row)
        return self._to_model(row)

    def set_topic(self, task_id: str, topic: str) -> TaskRecord:
        with self.sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            row.topic = topic
            row.updated_at = datetime.now().astimezone()
            session.add(row)
        return self._to_model(row)

    def reset_for_retry(self, task_id: str) -> TaskRecord:
        """Recovery action: restart a task that stopped mid-pipeline.

        A process crash or an unhandled node error can leave a task in a mid-pipeline
        state (e.g. WRITTEN) from which the workflow cannot restart. This method puts
        such tasks back to CREATED so a fresh run begins cleanly. Finished or
        human-waiting states are never reset automatically.
        """
        restartable = {
            TaskStatus.DATA_SYNCED,
            TaskStatus.PLANNED,
            TaskStatus.RESEARCHED,
            TaskStatus.WRITTEN,
            TaskStatus.ASSETS_READY,
            TaskStatus.REVIEWED,
            TaskStatus.FAILED,
        }
        with self.sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row.status)
            if current in restartable:
                row.status = TaskStatus.CREATED.value
                row.updated_at = datetime.now().astimezone()
                session.add(row)
        return self._to_model(row)
