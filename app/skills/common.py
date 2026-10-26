from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.domain.models import ResearchPack

PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_ROOT / f"{name}.md").read_text(encoding="utf-8")


def compact_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def canonical_claim_refs(refs: list[str], research: ResearchPack) -> list[str]:
    """Resolve known document IDs to their actual retrieved snapshot, without inventing evidence."""
    aliases: dict[str, set[str]] = {}
    valid = {claim.source_snapshot_hash for claim in research.claims if claim.source_snapshot_hash}
    for claim in research.claims:
        if claim.source_type != "knowledge_base" or not claim.source_snapshot_hash:
            continue
        for identifier in parse_qs(urlparse(str(claim.source_url)).query).get("source", []):
            aliases.setdefault(identifier, set()).add(claim.source_snapshot_hash)
    resolved = []
    for ref in refs:
        candidates = aliases.get(ref, set())
        canonical = next(iter(candidates)) if ref not in valid and len(candidates) == 1 else ref
        if canonical not in resolved:
            resolved.append(canonical)
    return resolved
