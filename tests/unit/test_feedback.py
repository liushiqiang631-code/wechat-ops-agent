from __future__ import annotations

from app.services.feedback.diff import diff_final_version


def test_human_edit_diff_extracts_reusable_style_signals():
    generated = """# Agent Skills 入门

在当今时代，Agent Skills 值得注意。

## 定义

Skill 是一种可复用方法。

总的来说，未来可期。
"""
    final = """# Agent Skills 的工程边界

先看一个真实的开发问题。

## 定义与边界

Skill 是一种可复用方法，但它不直接保存密钥。
"""

    report = diff_final_version(generated, final)

    assert report.title_changed is True
    assert report.deleted_paragraph_count >= 1
    assert report.replacement_rate > 0
    assert any("删除模板化开头" in rule for rule in report.reusable_rules)
    assert any("删除口号式结尾" in rule for rule in report.reusable_rules)
