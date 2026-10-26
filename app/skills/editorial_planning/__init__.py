from __future__ import annotations

from app.domain.models import EditorialBlueprint, ResearchPack, TaskSpec
from app.skills.common import canonical_claim_refs, compact_json, load_prompt

SKILL_META = {
    "name": "editorial_planning",
    "title": "深度文章策划",
    "description": "写作前定义读者问题、核心结论、证据分配、实战与边界。",
    "category": "pipeline",
    "version": "1.2.1",
    "builtin": True,
    "locked": True,
}


class EditorialPlanningSkill:
    version = "1.2.1"

    def __init__(self, model):
        self.model = model

    async def run(self, task: TaskSpec, research: ResearchPack) -> EditorialBlueprint:
        result = await self.model.generate_structured(
            system=load_prompt("editorial_planning"),
            user=compact_json({"task": task, "research": research}),
            response_model=EditorialBlueprint,
        )
        return result.data.model_copy(
            update={
                "sections": [
                    section.model_copy(
                        update={"claim_refs": canonical_claim_refs(section.claim_refs, research)}
                    )
                    for section in result.data.sections
                ]
            }
        )
