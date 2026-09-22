from __future__ import annotations

from app.domain.models import AnalyticsReport, TopicCandidate
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "topic_strategy",
    "title": "选题策略",
    "description": "结合账号定位与数据表现，评分候选选题并给出理由。",
    "category": "pipeline",
    "version": "1.0.1",
    "builtin": True,
    "locked": True,
}


class TopicStrategySkill:
    version = "1.0.1"

    def __init__(self, model):
        self.model = model

    async def run(self, profile: dict, analytics: AnalyticsReport) -> TopicCandidate:
        result = await self.model.generate_structured(
            system=load_prompt("topic_strategy"),
            user=compact_json({"profile": profile, "analytics": analytics}),
            response_model=TopicCandidate,
        )
        return result.data
