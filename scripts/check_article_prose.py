"""Render a task's article to Markdown and run the human-writing prose check.

Usage:
    python scripts/check_article_prose.py <task_id>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.models import ArticleDocument  # noqa: E402
from app.services.formatting.renderer import article_to_markdown  # noqa: E402

CHECK_SCRIPT = ROOT / "app" / "skills" / "human_writing" / "check_prose.py"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print("usage: python scripts/check_article_prose.py <task_id>")
        return 2
    task_id = args[0]
    root = ROOT / "outputs" / task_id
    article_path = root / "article.latest.json"
    if not article_path.exists():
        print(f"no article artifact for task {task_id}")
        return 2
    article = ArticleDocument.model_validate(
        json.loads(article_path.read_text(encoding="utf-8"))
    )
    markdown_path = root / "article.md"
    markdown_path.write_text(article_to_markdown(article), encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - fixed local script
        [sys.executable, str(CHECK_SCRIPT), str(markdown_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
