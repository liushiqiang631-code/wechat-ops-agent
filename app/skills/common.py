from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_ROOT / f"{name}.md").read_text(encoding="utf-8")


def compact_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
