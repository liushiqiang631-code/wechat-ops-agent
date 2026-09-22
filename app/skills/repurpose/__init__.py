from __future__ import annotations

from app.domain.models import ArticleDocument, RepurposedContent
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "repurpose",
    "title": "内容复用",
    "description": "从已完成文章派生视频号脚本、小红书文案与朋友圈转发语。",
    "category": "pipeline",
    "version": "1.0.1",
    "builtin": True,
    "locked": True,
}


class RepurposeSkill:
    version = "1.0.1"

    def __init__(self, model):
        self.model = model

    async def run(self, task_id: str, article: ArticleDocument) -> RepurposedContent:
        result = await self.model.generate_structured(
            system=load_prompt("repurpose"),
            user=compact_json({"task_id": task_id, "article": article}),
            response_model=RepurposedContent,
        )
        content = result.data
        if content.task_id != task_id:
            content = content.model_copy(update={"task_id": task_id})
        return content
