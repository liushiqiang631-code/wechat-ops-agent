from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from app.db.base import Database
from app.db.migrations import run_migrations


def _version(database_url: str) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version_num FROM alembic_version"))
            return str(result.scalar_one())
    finally:
        engine.dispose()


def test_migrations_adopt_legacy_create_all_database_and_remain_idempotent(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy = Database(database_url)
    legacy.create_all()
    legacy.engine.dispose()

    run_migrations(database_url)
    run_migrations(database_url)

    assert _version(database_url) == "0004_omni_channel"


def test_migrations_build_a_new_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'new.db'}"

    run_migrations(database_url)

    assert _version(database_url) == "0004_omni_channel"


def test_migrations_reconcile_stale_revision_when_legacy_table_already_exists(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale-version.db'}"
    legacy = Database(database_url)
    legacy.create_all()
    with legacy.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('0002_topic_records_and_plan_id')"
            )
        )
    legacy.engine.dispose()

    run_migrations(database_url)

    assert _version(database_url) == "0004_omni_channel"
