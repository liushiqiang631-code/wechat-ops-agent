from __future__ import annotations

from app.domain.models import TitleProposal
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "titles",
    "title": "标题候选",
    "description": "为选题生成 3–5 个标题候选，供人工选定后作为写作约束。",
    "category": "pipeline",
    "version": "1.0.0",
    "builtin": True,
    "locked": True,
}


class TitleSkill:
    version = "1.0.0"

    def __init__(self, model):
        self.model = model

    async def run(self, topic: str, request: str) -> TitleProposal:
        result = await self.model.generate_structured(
            system=load_prompt("titles"),
            user=compact_json({"topic": topic, "request": request}),
            response_model=TitleProposal,
        )
        return result.data
