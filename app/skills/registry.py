from __future__ import annotations

import importlib
import pkgutil

from app.domain.models import SkillRecord
from app.repositories.skills import SkillStateRepository


class SkillRegistry:
    """Discovers versioned skills and merges the operator's enable/disable state.

    Each skill package declares a module-level ``SKILL_META`` dict. Core
    pipeline skills are builtin and locked; user skills (e.g. human_writing)
    can be toggled from the console, and the enabled state persists in the
    ``skill_states`` table.
    """

    SKILLS_PACKAGE = "app.skills"

    def __init__(self, repository: SkillStateRepository | None = None):
        self.repository = repository

    # -- discovery ---------------------------------------------------------

    def _module_names(self) -> list[str]:
        package = importlib.import_module(self.SKILLS_PACKAGE)
        return sorted(
            module.name
            for module in pkgutil.iter_modules(package.__path__)
            if not module.name.startswith("_")
        )

    def _load(self, module_name: str) -> SkillRecord | None:
        module = importlib.import_module(f"{self.SKILLS_PACKAGE}.{module_name}")
        meta = getattr(module, "SKILL_META", None)
        if not meta:
            # helper modules (common.py, registry.py) are not skills
            return None
        return SkillRecord(
            name=meta.get("name", module_name),
            title=meta.get("title", module_name),
            description=meta.get("description", ""),
            category=meta.get("category", "pipeline"),
            version=meta.get("version", "0.0.0"),
            builtin=bool(meta.get("builtin", True)),
            locked=bool(meta.get("locked", False)),
            enabled=bool(meta.get("enabled", True)),
        )

    def discover(self) -> list[SkillRecord]:
        records = [
            record
            for name in self._module_names()
            if (record := self._load(name)) is not None
        ]
        if self.repository is None:
            return records
        stored = self.repository.all()
        for record in records:
            if record.name not in stored and not record.locked:
                self.repository.set(record.name, record.enabled)
        stored = self.repository.all()
        merged: list[SkillRecord] = []
        for record in records:
            if record.name in stored and not record.locked:
                merged.append(record.model_copy(update={"enabled": stored[record.name]}))
            else:
                merged.append(record)
        return merged

    # -- queries / mutations ----------------------------------------------

    def get(self, name: str) -> SkillRecord | None:
        return next((record for record in self.discover() if record.name == name), None)

    def enabled_skills(self, category: str | None = None) -> list[SkillRecord]:
        return [
            record
            for record in self.discover()
            if record.enabled and (category is None or record.category == category)
        ]

    def set_enabled(self, name: str, enabled: bool) -> SkillRecord:
        record = self.get(name)
        if record is None:
            raise KeyError(f"skill {name} is not installed")
        if record.locked:
            raise ValueError(f"skill {name} is locked and cannot be toggled")
        if self.repository is not None:
            self.repository.set(name, enabled)
        return record.model_copy(update={"enabled": enabled})
