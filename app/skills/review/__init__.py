from __future__ import annotations

from app.domain.models import ArticleDocument, ResearchPack, ReviewReport
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "review",
    "title": "事实与结构审核",
    "description": "按事实来源、表达与结构标准评审文章，最多两轮自动修订。",
    "category": "pipeline",
    "version": "1.1.0",
    "builtin": True,
    "locked": True,
}


class ReviewSkill:
    version = "1.1.0"

    def __init__(self, model):
        self.model = model

    async def run(
        self, article: ArticleDocument, research: ResearchPack, revision_round: int = 0
    ) -> ReviewReport:
        result = await self.model.generate_structured(
            system=load_prompt("review"),
            user=compact_json(
                {
                    "article": article,
                    "research": research,
                    "revision_round": revision_round,
                    "intentional_error_count": 0,
                }
            ),
            response_model=ReviewReport,
        )
        return result.data
