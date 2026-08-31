from __future__ import annotations

from pathlib import Path

from app.services.progress.step_recorder import StepRecorder
from app.services.storage.artifacts import ArtifactStore


def test_recorder_tracks_each_step_with_duration(tmp_path: Path):
    store = ArtifactStore(tmp_path / "outputs")
    recorder = StepRecorder(store, "task-1")

    recorder.start("research", "研究权威来源")
    recorder.finish("research", "提炼 3 条事实")
    recorder.start("write", "生成文章初稿")
    recorder.mark_succeeded()

    snapshot = recorder.snapshot()
    assert snapshot.status == "succeeded"
    assert [step.node for step in snapshot.steps] == ["research", "write"]
    assert snapshot.steps[0].status == "done"
    assert snapshot.steps[0].duration_ms >= 0
    assert snapshot.steps[0].message == "提炼 3 条事实"
    # The write step was still open when the run ended.
    assert snapshot.steps[1].status == "running"
    assert snapshot.total_duration_ms is not None

    persisted = store.read_json("task-1", "steps")
    assert persisted["status"] == "succeeded"
    assert persisted["steps"][0]["node"] == "research"


def test_recorder_marks_failed_run_with_error_message(tmp_path: Path):
    store = ArtifactStore(tmp_path / "outputs")
    recorder = StepRecorder(store, "task-2")

    recorder.start("research", "研究权威来源")
    recorder.mark_failed("RuntimeError: research backend unavailable")

    snapshot = recorder.snapshot()
    assert snapshot.status == "failed"
    assert snapshot.steps[0].status == "failed"
    assert "research backend unavailable" in (snapshot.steps[0].message or "")


def test_recorder_finish_ignores_unmatched_node(tmp_path: Path):
    store = ArtifactStore(tmp_path / "outputs")
    recorder = StepRecorder(store, "task-3")

    recorder.start("research", "研究权威来源")
    recorder.finish("write", "不应匹配")

    snapshot = recorder.snapshot()
    # The unmatched finish leaves the research step open and never closes it.
    assert len(snapshot.steps) == 1
    assert snapshot.steps[0].node == "research"
    assert snapshot.steps[0].status == "running"
    assert snapshot.status == "running"


def test_step_recorder_notifies_cli_observer_of_start_and_finish(tmp_path):
    events: list[tuple[str, str]] = []
    recorder = StepRecorder(
        ArtifactStore(tmp_path / "outputs"),
        "task-1",
        observer=lambda event, step: events.append((event, step.node)),
    )

    recorder.start("research", "研究权威来源")
    recorder.finish("research", "提炼 3 条事实")

    assert events == [("started", "research"), ("finished", "research")]
