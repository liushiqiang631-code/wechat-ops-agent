from __future__ import annotations

SKILL_META = {
    "name": "human_writing",
    "title": "活人感写作（human-writing）",
    "description": (
        "来自 github.com/KKKKhazix/human-writing 的中文写作 Skill：先查材料再动笔，"
        "把文章写成具体的人在说话；清除翻案腔、冒号滥用、破折号与模型黑话；"
        "现实内容严格核验事实与来源。"
    ),
    "category": "writing_style",
    "version": "1.1.0",
    "builtin": False,
    "locked": False,
    "enabled": True,
}


class HumanWritingSkill:
    """Writing-style skill: loaded by WritingSkill when enabled in the registry."""

    version = "1.1.0"
