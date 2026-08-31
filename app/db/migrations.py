from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _legacy_revision(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        version: str | None = None
        if "alembic_version" in tables:
            with engine.connect() as connection:
                version = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar_one_or_none()
        if "content_tasks" not in tables:
            return None
        task_columns = {column["name"] for column in inspector.get_columns("content_tasks")}
        has_topic_schema = (
            "topic_records" in tables
            and {"title_hint", "plan_id"}.issubset(task_columns)
        )
        if has_topic_schema and "skill_states" in tables:
            return "head" if version != "0003_skill_states" else None
        if has_topic_schema:
            revision = "0002_topic_records_and_plan_id"
            return revision if version != revision else None
        return "0001_initial" if version != "0001_initial" else None
    finally:
        engine.dispose()


def run_migrations(database_url: str) -> None:
    """Upgrade the configured database before the application starts serving."""

    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    legacy_revision = _legacy_revision(database_url)
    if legacy_revision is not None:
        command.stamp(config, legacy_revision)
    command.upgrade(config, "head")
