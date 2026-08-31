from __future__ import annotations

from pathlib import Path

from app.db.base import Database
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import DraftReceipt, PublicationRecord, TaskSpec
from app.repositories.publications import PublicationRepository
from app.repositories.tasks import TaskRepository
from app.services.storage.artifacts import ArtifactStore


def test_task_repository_round_trip_and_validated_state_transition(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'repo.db'}")
    database.create_all()
    repository = TaskRepository(database.session_factory)
    task = TaskSpec(mode=TaskMode.FIXED_TOPIC, request="解释 LangGraph 检查点")

    created = repository.create(task)
    updated = repository.transition(created.id, TaskStatus.PLANNED)

    assert repository.get(created.id).request == task.request
    assert updated.status == TaskStatus.PLANNED


def test_draft_receipt_is_idempotent_by_key(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'receipt.db'}")
    database.create_all()
    repository = PublicationRepository(database.session_factory)
    receipt = DraftReceipt(
        idempotency_key="account:task:hash",
        task_id="task-1",
        media_id="media-1",
        content_hash="hash",
        evidence_type="mock",
    )

    first = repository.save_draft_receipt(receipt)
    second = repository.save_draft_receipt(receipt.model_copy(update={"media_id": "media-2"}))

    assert first.media_id == "media-1"
    assert second.media_id == "media-1"


def test_publication_requires_task_url_and_publish_time(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'publication.db'}")
    database.create_all()
    repository = PublicationRepository(database.session_factory)
    publication = PublicationRecord(
        task_id="task-1",
        article_url="https://mp.weixin.qq.com/s/example",
        published_at="2026-07-18T20:00:00+08:00",
        draft_media_id="media-1",
    )

    saved = repository.register(publication)

    assert saved.task_id == "task-1"
    assert repository.get_by_task("task-1").article_url == publication.article_url


def test_artifact_store_versions_without_overwriting(tmp_path: Path):
    store = ArtifactStore(tmp_path / "outputs")

    first = store.write_json("task-1", "article", {"title": "v1"})
    second = store.write_json("task-1", "article", {"title": "v2"})

    assert first.version == 1
    assert second.version == 2
    assert store.read_json("task-1", "article", version=1)["title"] == "v1"
    assert store.read_json("task-1", "article")["title"] == "v2"
