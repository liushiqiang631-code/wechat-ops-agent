from __future__ import annotations

from app.domain.models import ArticleDocument, VisualItem, VisualPlan
from app.services.knowledge import KnowledgeUnavailable
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "visual_planning",
    "title": "视觉策划",
    "description": "先检索知识库图库，逐张选择合适素材；没有合适图片再联网找图或 AI 生成。",
    "category": "pipeline",
    "version": "2.3.0",
    "builtin": True,
    "locked": True,
}


class VisualPlanningSkill:
    version = "2.3.0"

    def __init__(self, model, knowledge=None):
        self.model = model
        self.knowledge = knowledge

    async def local_plan(
        self, article: ArticleDocument, context: dict | None = None
    ) -> VisualPlan:
        """Prepare a human-review draft using matching gallery originals, without an LLM."""
        if self.knowledge is None:
            return VisualPlan()
        try:
            result = await self.knowledge.search(
                article.selected_title, text_limit=0, image_limit=24
            )
        except KnowledgeUnavailable:
            return VisualPlan()
        images = [image for image in result.images if image.folder_name
                  and len(image.folder_name) >= 2 and image.folder_name in article.selected_title]
        context = context or {}
        covers = min(1, max(0, int(context.get("cover_count", 1))))
        inline = min(3, max(0, int(context.get("inline_image_count", 3))))
        return VisualPlan(items=[
            VisualItem(
                kind="cover" if index < covers else "concept", provider="planned",
                placement="封面" if index < covers else "正文", source="knowledge_base",
                knowledge_image_id=image.id, purpose=f"展示{image.folder_name}图库中的原始素材",
                prompt_or_source=f"{image.folder_name}/{image.name}",
                caption=f"{image.folder_name}图库素材",
            ) for index, image in enumerate(images[:covers + inline])
        ])

    async def run(self, article: ArticleDocument, context: dict | None = None) -> VisualPlan:
        capability = dict(context or {})
        capability["image_source_priority"] = ["knowledge_base", "web_search_or_ai"]
        images = []
        subject_images = []
        if self.knowledge is not None:
            try:
                result = await self.knowledge.search(
                    article.selected_title, text_limit=0, image_limit=24
                )
                images = result.images
                # A pasted filename carries no subject, but its product folder does.
                # Exact folder matches also exclude similarly named sibling products.
                subject_images = [
                    item for item in images
                    if item.folder_name and len(item.folder_name) >= 2
                    and item.folder_name in article.selected_title
                ]
                if subject_images:
                    images = subject_images
                    capability["matched_subject_folders"] = sorted({
                        item.folder_name for item in subject_images
                    })
                capability["knowledge_images"] = [image.model_dump() for image in images]
                capability["knowledge_base_available"] = True
            except KnowledgeUnavailable:
                capability["knowledge_images"] = []
                capability["knowledge_base_available"] = False
        result = await self.model.generate_structured(
            system=load_prompt("visual_planning"),
            user=compact_json({"article": article, "context": capability}),
            response_model=VisualPlan,
        )
        plan = result.data
        normalized = []
        available_ids = {image.id for image in images}
        used_ids = set()
        for item in plan.items:
            local = next((image for image in subject_images if image.id not in used_ids), None)
            if local is not None and item.source in {
                "knowledge_base", "ai_generated", "web_search",
            } and (
                item.source != "knowledge_base"
                or item.knowledge_image_id not in available_ids
                or item.knowledge_image_id in used_ids
            ):
                # Enforce knowledge-first acquisition in code, including inline slots;
                # a model cannot spend on a generic replacement while originals remain.
                item = item.model_copy(update={
                    "source": "knowledge_base",
                    "knowledge_image_id": local.id,
                    "prompt_or_source": f"{local.folder_name}/{local.name}",
                    "purpose": f"展示{local.folder_name}图库中的原始素材",
                    "caption": f"{local.folder_name}图库素材",
                })
            can_acquire = (
                item.source == "ai_generated" and capability.get("ai_generation_available")
            ) or (item.source == "web_search" and capability.get("web_search_available"))
            if item.source == "knowledge_base":
                can_acquire = (
                    item.knowledge_image_id in available_ids
                    and item.knowledge_image_id not in used_ids
                )
                if not can_acquire:
                    continue
                used_ids.add(item.knowledge_image_id)
            if item.source is not None and item.provider != "deterministic":
                provider = "planned" if can_acquire else "disabled"
                item = item.model_copy(update={"provider": provider})
            normalized.append(item)
        return plan.model_copy(update={"items": normalized})
