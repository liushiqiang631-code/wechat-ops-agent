from __future__ import annotations

from app.domain.models import ArticleDocument, VisualPlan
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "visual_planning",
    "title": "视觉策划",
    "description": "规划封面与配图，选择 AI 生图或网上找图，并给出可执行提示词。",
    "category": "pipeline",
    "version": "2.0.0",
    "builtin": True,
    "locked": True,
}


class VisualPlanningSkill:
    version = "2.0.0"

    def __init__(self, model):
        self.model = model

    async def run(self, article: ArticleDocument, context: dict | None = None) -> VisualPlan:
        result = await self.model.generate_structured(
            system=load_prompt("visual_planning"),
            user=compact_json({"article": article, "context": context or {}}),
            response_model=VisualPlan,
        )
        plan = result.data
        capability = context or {}
        normalized = []
        for item in plan.items:
            can_acquire = (
                item.source == "ai_generated" and capability.get("ai_generation_available")
            ) or (item.source == "web_search" and capability.get("web_search_available"))
            if item.source is not None and item.provider != "deterministic":
                provider = "planned" if can_acquire else "disabled"
                item = item.model_copy(update={"provider": provider})
            normalized.append(item)
        return plan.model_copy(update={"items": normalized})
