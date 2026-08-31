from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskMode
from app.scheduler.jobs import build_scheduler, prepare_weekly_plan


def test_scheduler_registers_daily_and_weekly_jobs(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'scheduler.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)

    scheduler = build_scheduler(container)
    jobs = {job.id for job in scheduler.get_jobs()}

    assert jobs == {"daily_metrics_audit", "weekly_content_plan"}


def test_weekly_job_creates_auditable_task_without_publishing(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'weekly.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)

    task_id = prepare_weekly_plan(container)
    task = container.tasks.get(task_id)

    assert task.mode == TaskMode.WEEKLY_PLAN
    assert task.constraints.auto_publish is False
