from __future__ import annotations

from app.domain.models import (
    ArticleDocument,
    ArticleQualityReport,
    GenUiDocument,
    ResearchPack,
    ReviewReport,
)
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "genui",
    "title": "安全生成式界面",
    "description": "把文章质量、证据和下一步动作组织成受控的可视化组件。",
    "category": "pipeline",
    "version": "1.0.1",
    "builtin": True,
    "locked": True,
}


class GenUiSkill:
    version = "1.0.1"

    def __init__(self, model):
        self.model = model

    async def run(
        self,
        article: ArticleDocument,
        research: ResearchPack,
        review: ReviewReport,
        quality: ArticleQualityReport | None,
    ) -> GenUiDocument:
        result = await self.model.generate_structured(
            system=load_prompt("genui"),
            user=compact_json(
                {
                    "article": article,
                    "research": research,
                    "review": review,
                    "quality": quality,
                }
            ),
            response_model=GenUiDocument,
        )
        return result.data
