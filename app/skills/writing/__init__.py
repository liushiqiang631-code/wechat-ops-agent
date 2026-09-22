from __future__ import annotations

from app.domain.models import (
    ArticleDocument,
    ArticleQualityReport,
    ArticleSupplement,
    EditorialBlueprint,
    ResearchPack,
    ReviewReport,
    TaskSpec,
)
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "writing",
    "title": "文章写作",
    "description": "按任务约束与研究材料生成结构化文章，可叠加启用中的写作风格 Skill。",
    "category": "pipeline",
    "version": "1.2.1",
    "builtin": True,
    "locked": True,
}


class WritingSkill:
    version = "1.2.1"

    def __init__(self, model, registry=None):
        self.model = model
        self.registry = registry

    async def run(
        self,
        task: TaskSpec,
        research: ResearchPack,
        blueprint: EditorialBlueprint | None = None,
        *,
        previous_article: ArticleDocument | None = None,
        review: ReviewReport | None = None,
        quality: ArticleQualityReport | None = None,
    ) -> ArticleDocument:
        system = load_prompt("writing")
        if self.registry is not None:
            # Enabled writing-style skills (e.g. human_writing) layer their
            # style guide on top of the base writing contract.
            for style in self.registry.enabled_skills(category="writing_style"):
                system += "\n\n" + load_prompt(style.name)
        title_hint = getattr(task, "title_hint", None)
        if title_hint:
            system += (
                f"\nThe human has selected this exact title: {title_hint}. "
                "Use it as selected_title verbatim."
            )
        result = await self.model.generate_structured(
            system=system,
            user=compact_json(
                {
                    "task": task,
                    "research": research,
                    "editorial_blueprint": blueprint,
                    "previous_article": previous_article,
                    "review_feedback": review,
                    "quality_feedback": quality,
                }
            ),
            response_model=ArticleDocument,
        )
        article = result.data
        if title_hint and article.selected_title != title_hint:
            titles = [title_hint, *[t for t in article.titles if t != title_hint]][:10]
            article = article.model_copy(
                update={"selected_title": title_hint, "titles": titles}
            )
        return article

    async def supplement(
        self,
        task: TaskSpec,
        research: ResearchPack,
        blueprint: EditorialBlueprint,
        *,
        previous_article: ArticleDocument,
        quality: ArticleQualityReport,
    ) -> ArticleDocument:
        """Generate only missing sections, preserving an already reviewable draft."""
        system = load_prompt("writing") + (
            "\n\nThe article failed deterministic quality checks. Return only new or replacement "
            "sections that remedy the listed gaps. Do not repeat unchanged sections."
        )
        if self.registry is not None:
            for style in self.registry.enabled_skills(category="writing_style"):
                system += "\n\n" + load_prompt(style.name)
        result = await self.model.generate_structured(
            system=system,
            user=compact_json(
                {
                    "task": task,
                    "research": research,
                    "editorial_blueprint": blueprint,
                    "previous_article": previous_article,
                    "quality_feedback": quality,
                }
            ),
            response_model=ArticleSupplement,
        )
        supplement = result.data
        return previous_article.model_copy(
            update={
                "sections": [*previous_article.sections, *supplement.sections],
                "ending": supplement.ending or previous_article.ending,
                "quality_summary": supplement.quality_summary or previous_article.quality_summary,
            }
        )
