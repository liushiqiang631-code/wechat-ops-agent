from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from app.domain.models import StepLog, StepRunReport
from app.services.storage.artifacts import ArtifactStore

logger = logging.getLogger(__name__)


class StepRecorder:
    """Records the per-node execution timeline of one workflow run.

    The recorder is deliberately side-effect safe: a failure while persisting
    progress must never break the pipeline, so every write is best-effort.
    Progress is persisted as a versioned ``steps`` artifact after each event,
    which lets both the CLI and the web console show "what the agent is doing
    right now" instead of a black-box running state.
    """

    def __init__(
        self,
        artifacts: ArtifactStore,
        task_id: str,
        observer: Callable[[str, StepLog], None] | None = None,
    ):
        self.artifacts = artifacts
        self.task_id = task_id
        self.run_started_at = datetime.now(UTC)
        self.run_finished_at: datetime | None = None
        self.status: Literal["running", "succeeded", "failed"] = "running"
        self._steps: list[StepLog] = []
        self._current: StepLog | None = None
        self._observer = observer

    # -- event API ---------------------------------------------------------

    def start(self, node: str, label: str) -> None:
        """Mark the beginning of one pipeline node."""
        self._current = StepLog(
            node=node,
            label=label,
            status="running",
            started_at=datetime.now(UTC),
        )
        self._notify("started", self._current)
        self._persist()

    def finish(self, node: str, message: str | None = None) -> None:
        """Close the currently running node as successful."""
        if self._current is not None and self._current.node == node:
            self._close(self._current, "done", message)
            self._notify("finished", self._current)
            self._steps.append(self._current)
            self._current = None
        self._persist()

    def fail(self, node: str, error: str) -> None:
        """Close the currently running node as failed."""
        if self._current is not None and self._current.node == node:
            self._close(self._current, "failed", error)
            self._notify("failed", self._current)
            self._steps.append(self._current)
            self._current = None
        self._persist()

    def mark_succeeded(self) -> None:
        self.status = "succeeded"
        self.run_finished_at = datetime.now(UTC)
        self._persist()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.run_finished_at = datetime.now(UTC)
        if self._current is not None:
            self._close(self._current, "failed", error)
            self._steps.append(self._current)
            self._current = None
        self._persist()

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _close(step: StepLog, status: Literal["done", "failed"], message: str | None) -> None:
        finished = datetime.now(UTC)
        step.status = status
        step.finished_at = finished
        step.duration_ms = max(0, int((finished - step.started_at).total_seconds() * 1000))
        step.message = message

    def snapshot(self) -> StepRunReport:
        steps = [*self._steps]
        if self._current is not None:
            steps = [*steps, self._current]
        total = None
        if self.run_finished_at is not None:
            total = max(0, int((self.run_finished_at - self.run_started_at).total_seconds() * 1000))
        return StepRunReport(
            task_id=self.task_id,
            status=self.status,
            run_started_at=self.run_started_at,
            run_finished_at=self.run_finished_at,
            total_duration_ms=total,
            steps=steps,
        )

    def _persist(self) -> None:
        try:
            self.artifacts.write_json(
                self.task_id, "steps", self.snapshot().model_dump(mode="json")
            )
        except Exception as error:  # pragma: no cover - best effort by design
            logger.warning("could not persist step progress for task %s: %s", self.task_id, error)

    def _notify(self, event: str, step: StepLog) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event, step)
        except Exception as error:  # pragma: no cover - observers cannot affect work
            logger.warning(
                "could not notify progress observer for task %s: %s", self.task_id, error
            )
