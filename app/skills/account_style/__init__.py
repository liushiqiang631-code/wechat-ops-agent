from __future__ import annotations

SKILL_META = {
    "name": "account_style",
    "title": "账号结构与彩色排版（account-style）",
    "description": (
        "农业公众号内容规格：优先本地知识库与图库，不足时核验农业权威来源；"
        "农事问题开场、编号大节与田间行动清单；语义化彩色胶囊排版标记；"
        "成稿用 check_prose 复检去模型腔。"
    ),
    "category": "writing_style",
    "version": "1.1.1",
    "builtin": False,
    "locked": False,
    "enabled": True,
}


class AccountStyleSkill:
    """Writing-style skill: loaded by WritingSkill when enabled in the registry."""

    version = "1.1.1"
