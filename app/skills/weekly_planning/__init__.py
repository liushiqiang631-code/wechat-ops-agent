from __future__ import annotations

from app.domain.models import AnalyticsReport, WeeklyPlan
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "weekly_planning",
    "title": "周度选题计划",
    "description": "结合近期数据生成一周内容安排并落实第一篇。",
    "category": "pipeline",
    "version": "1.0.0",
    "builtin": True,
    "locked": True,
}


class WeeklyPlanningSkill:
    version = "1.0.0"

    def __init__(self, model):
        self.model = model

    async def run(self, profile: dict, analytics: AnalyticsReport, request: str) -> WeeklyPlan:
        result = await self.model.generate_structured(
            system=load_prompt("weekly_plan"),
            user=compact_json({"profile": profile, "analytics": analytics, "request": request}),
            response_model=WeeklyPlan,
        )
        return result.data
