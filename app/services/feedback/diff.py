from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.domain.models import EditDiffReport


def _title(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _paragraphs(markdown: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", markdown.strip())
    return [
        block.strip() for block in blocks if block.strip() and not block.lstrip().startswith("#")
    ]


def diff_final_version(generated: str, final: str) -> EditDiffReport:
    generated_paragraphs = _paragraphs(generated)
    final_paragraphs = _paragraphs(final)
    matcher = SequenceMatcher(a=generated_paragraphs, b=final_paragraphs)
    deleted = sum(
        i2 - i1 for tag, i1, i2, _, _ in matcher.get_opcodes() if tag in {"delete", "replace"}
    )
    added = sum(
        j2 - j1 for tag, _, _, j1, j2 in matcher.get_opcodes() if tag in {"insert", "replace"}
    )
    character_similarity = SequenceMatcher(a=generated, b=final).ratio()
    structural_changes: list[str] = []
    if _title(generated) != _title(final):
        structural_changes.append("标题已修改")
    if deleted:
        structural_changes.append(f"删除或重写 {deleted} 个段落")
    rules: list[str] = []
    opening_cliches = ("在当今时代", "随着科技不断发展", "在人工智能浪潮下")
    ending_cliches = ("总的来说", "未来可期", "赋能千行百业")
    if any(phrase in generated and phrase not in final for phrase in opening_cliches):
        rules.append("删除模板化开头，直接进入具体问题")
    if any(phrase in generated and phrase not in final for phrase in ending_cliches):
        rules.append("删除口号式结尾，改为判断、局限或下一步")
    if _title(generated) != _title(final):
        rules.append("标题优先表达工程边界，降低入门教程式措辞")
    return EditDiffReport(
        title_changed=_title(generated) != _title(final),
        deleted_paragraph_count=deleted,
        added_paragraph_count=added,
        replacement_rate=round(1 - character_similarity, 4),
        structural_changes=structural_changes,
        reusable_rules=rules,
    )
