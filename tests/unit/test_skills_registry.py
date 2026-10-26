from __future__ import annotations

from pathlib import Path

import pytest

from app.db.base import Database
from app.repositories.skills import SkillStateRepository
from app.skills.registry import SkillRegistry


def build_registry(tmp_path: Path) -> SkillRegistry:
    database = Database(f"sqlite:///{tmp_path / 'skills.db'}")
    database.create_all()
    return SkillRegistry(SkillStateRepository(database.session_factory))


def test_registry_discovers_all_skill_packages(tmp_path: Path):
    registry = build_registry(tmp_path)

    skills = registry.discover()
    names = {skill.name for skill in skills}

    assert {"writing", "research", "analytics", "visual_planning"} <= names
    assert "human_writing" in names
    # helper modules are not skills
    assert "common" not in names
    assert "registry" not in names


def test_human_writing_is_installed_and_enabled_by_default(tmp_path: Path):
    registry = build_registry(tmp_path)

    human_writing = registry.get("human_writing")

    assert human_writing is not None
    assert human_writing.enabled is True
    assert human_writing.builtin is False
    assert human_writing.locked is False
    assert human_writing.category == "writing_style"
    assert human_writing.version == "1.1.0"


def test_core_pipeline_skills_are_locked_and_cannot_be_toggled(tmp_path: Path):
    registry = build_registry(tmp_path)

    with pytest.raises(ValueError, match="locked"):
        registry.set_enabled("writing", False)


def test_toggle_persists_across_registry_instances(tmp_path: Path):
    registry = build_registry(tmp_path)
    registry.set_enabled("human_writing", False)

    fresh = build_registry(tmp_path)

    assert fresh.get("human_writing").enabled is False


def test_enabled_writing_styles_are_listed_for_the_writer(tmp_path: Path):
    registry = build_registry(tmp_path)

    styles = registry.enabled_skills(category="writing_style")

    # alphabetical by module name: account_style < human_writing
    assert [style.name for style in styles] == ["account_style", "human_writing"]


def test_account_style_is_installed_and_enabled_by_default(tmp_path: Path):
    registry = build_registry(tmp_path)

    account_style = registry.get("account_style")

    assert account_style is not None
    assert account_style.enabled is True
    assert account_style.builtin is False
    assert account_style.locked is False
    assert account_style.category == "writing_style"
    assert account_style.version == "1.1.1"
    assert "农业" in account_style.description
