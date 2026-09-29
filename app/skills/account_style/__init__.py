from __future__ import annotations

SKILL_META = {
    "name": "account_style",
    "title": "账号结构与彩色排版（account-style）",
    "description": (
        "本公众号内容规格：技术内容先核验官方论文、文档与 GitHub 等一手资料；"
        "固定结构骨架（痛点开场、编号大节、终极公式）；语义化彩色胶囊排版标记；"
        "成稿用 check_prose 复检去模型腔。"
    ),
    "category": "writing_style",
    "version": "1.0.0",
    "builtin": False,
    "locked": False,
    "enabled": True,
}


class AccountStyleSkill:
    """Writing-style skill: loaded by WritingSkill when enabled in the registry."""

    version = "1.0.0"
