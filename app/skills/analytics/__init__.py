from __future__ import annotations

from typing import Any

from app.domain.models import AnalyticsReport
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "analytics",
    "title": "数据分析",
    "description": "分析近 7/30/90 天运营指标，输出关键发现与行动建议。",
    "category": "pipeline",
    "version": "1.1.0",
    "builtin": True,
    "locked": True,
}


class AnalyticsSkill:
    version = "1.1.0"

    def __init__(self, model):
        self.model = model

    async def run(
        self,
        metrics: list[dict[str, Any]],
        *,
        topic_performance: list[dict[str, Any]] | None = None,
    ) -> AnalyticsReport:
        payload: dict[str, Any] = {"metrics": metrics}
        if topic_performance:
            payload["published_topic_performance"] = topic_performance
        result = await self.model.generate_structured(
            system=load_prompt("analytics"),
            user=compact_json(payload),
            response_model=AnalyticsReport,
        )
        return result.data
