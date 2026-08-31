from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.domain.enums import TaskMode
from app.domain.models import (
    AnalyticsReport,
    ArticleDocument,
    ArticleSection,
    RepurposedContent,
    ResearchClaim,
    ResearchPack,
    ReviewReport,
    SourceSnapshot,
    TaskSpec,
    TitleProposal,
    TopicCandidate,
    VisualPlan,
    WeeklyPlan,
)
from app.services.models.deepseek import ModelResult, ModelUsage
from app.skills.analytics import AnalyticsSkill
from app.skills.repurpose import RepurposeSkill
from app.skills.research import ResearchSkill
from app.skills.review import ReviewSkill
from app.skills.titles import TitleSkill
from app.skills.topic_strategy import TopicStrategySkill
from app.skills.visual_planning import VisualPlanningSkill
from app.skills.weekly_planning import WeeklyPlanningSkill
from app.skills.writing import WritingSkill


class FakeModel:
    def __init__(self, responses: dict[type, dict[str, Any]]):
        self.responses = responses
        self.calls: list[type] = []

    async def generate_structured(self, *, response_model, **_: Any):
        self.calls.append(response_model)
        return ModelResult(
            data=response_model.model_validate(self.responses[response_model]),
            usage=ModelUsage(),
            model="fake",
        )


@pytest.mark.asyncio
async def test_skills_return_typed_outputs_without_secret_side_effects():
    claim = {
        "claim": "LangGraph 支持检查点。",
        "source_url": "https://docs.langchain.com/oss/python/langgraph/persistence",
        "source_title": "Persistence",
        "publisher": "LangChain",
        "retrieved_at": "2026-07-18T00:00:00+08:00",
        "source_type": "official_doc",
        "confidence": 0.9,
    }
    article = {
        "titles": ["LangGraph 检查点为什么重要"],
        "selected_title": "LangGraph 检查点为什么重要",
        "digest": "从失败恢复看工作流设计。",
        "audience": "AI 应用开发者",
        "sections": [{"type": "paragraph", "content": "先看一个中断场景。"}],
        "references": ["https://docs.langchain.com/oss/python/langgraph/persistence"],
        "ending": "检查点的价值是把失败变成可恢复状态。",
    }
    fake = FakeModel(
        {
            AnalyticsReport: {
                "period": "last_30_days",
                "key_findings": [],
                "confidence": 0.5,
                "limitations": ["样本较少"],
            },
            TopicCandidate: {
                "topic": "LangGraph 检查点",
                "score": 82,
                "score_breakdown": {
                    "historical_performance": 12,
                    "positioning_fit": 24,
                    "timeliness": 18,
                    "content_gap": 14,
                    "executability": 10,
                },
                "reasons": ["符合工程化定位"],
                "evidence": ["account_profile"],
                "confidence": 0.7,
                "limitations": ["历史文章不足 20 篇"],
            },
            ResearchPack: {
                "topic": "LangGraph 检查点",
                "claims": [claim],
                "sources": [claim["source_url"]],
            },
            ArticleDocument: article,
            ReviewReport: {
                "score": 90,
                "fact_source_score": 23,
                "author_voice_score": 12,
                "passed": True,
                "issues": [],
            },
            WeeklyPlan: {
                "week_start": "2026-07-20",
                "items": [
                    {
                        "day": "周一",
                        "topic": "LangGraph 检查点实战",
                        "format": "深度长文",
                        "purpose": "讲清楚检查点机制",
                        "source_notes": "LangGraph 官方文档",
                    },
                    {
                        "day": "周三",
                        "topic": "MCP 与 Tools 边界",
                        "format": "框架对比",
                        "purpose": "厘清概念",
                        "source_notes": "Model Context Protocol 文档",
                    },
                    {
                        "day": "周五",
                        "topic": "Skill 路由实践",
                        "format": "案例拆解",
                        "purpose": "给出可复用模式",
                        "source_notes": "",
                    },
                ],
                "rationale": ["结合近期数据与工程定位"],
            },
            VisualPlan: {
                "items": [
                    {
                        "kind": "mermaid",
                        "placement": "机制之后",
                        "purpose": "显示恢复路径",
                        "prompt_or_source": "flowchart LR; A --> B",
                        "provider": "deterministic",
                    }
                ],
                "concept_image_generation_enabled": False,
            },
            TitleProposal: {
                "topic": "LangGraph 检查点",
                "candidates": [
                    {
                        "title": "LangGraph 检查点：把失败变成可恢复状态",
                        "rationale": "工程视角切入",
                    },
                    {
                        "title": "如何用检查点构建可恢复的 Agent 流水线",
                        "rationale": "实操导向",
                    },
                    {
                        "title": "Agent 工程中的恢复机制",
                        "rationale": "概念清晰",
                    },
                ],
            },
            RepurposedContent: {
                "task_id": "task-1",
                "video_script": "开场钩子 + 检查点三句话",
                "xiaohongshu_post": "标题：检查点为什么重要\n正文：三点总结",
                "moments_blurb": "把失败变成可恢复状态，是 Agent 工程的必修课。",
            },
        }
    )
    task = TaskSpec(mode=TaskMode.FIXED_TOPIC, request="写 LangGraph 检查点", topic="LangGraph")

    analytics = await AnalyticsSkill(fake).run([{"read_count": 10}])
    topic = await TopicStrategySkill(fake).run({}, analytics)
    weekly = await WeeklyPlanningSkill(fake).run({}, analytics, task.request)
    titles = await TitleSkill(fake).run(topic.topic, task.request)
    research = await ResearchSkill(fake).run(topic.topic, [claim["source_url"]])
    written = await WritingSkill(fake).run(task, research)
    repurposed = await RepurposeSkill(fake).run(task.id, written)
    visuals = await VisualPlanningSkill(fake).run(
        written, {"ai_generation_available": False, "web_search_available": False}
    )
    review = await ReviewSkill(fake).run(written, research)

    assert isinstance(analytics, AnalyticsReport)
    assert isinstance(topic, TopicCandidate)
    assert isinstance(weekly, WeeklyPlan)
    assert len(weekly.items) >= 3
    assert isinstance(titles, TitleProposal)
    assert len(titles.candidates) >= 3
    assert isinstance(research.claims[0], ResearchClaim)
    assert isinstance(written.sections[0], ArticleSection)
    assert isinstance(repurposed, RepurposedContent)
    assert repurposed.task_id == task.id
    assert visuals.concept_image_generation_enabled is False
    assert all(item.provider == "deterministic" for item in visuals.items)
    assert review.passed is True


@pytest.mark.asyncio
async def test_research_normalizes_snapshot_timestamp_to_datetime():
    claim = {
        "claim": "官方文档说明检查点可用于恢复。",
        "source_url": "https://docs.example.com/checkpoints",
        "source_title": "Checkpoints",
        "publisher": "Example",
        "retrieved_at": "2026-08-23T00:00:00+08:00",
        "source_type": "official_doc",
        "confidence": 0.9,
    }

    class Fetcher:
        async def fetch(self, url):
            return SourceSnapshot(
                url=url,
                title="Checkpoints",
                content_excerpt="官方文档快照",
                retrieved_at=datetime(2026, 8, 23, 0, 0).astimezone(),
                content_hash="snapshot-hash",
                content_type="text/html",
            )

    model = FakeModel(
        {ResearchPack: {"topic": "检查点", "claims": [claim], "sources": [claim["source_url"]]}}
    )

    pack = await ResearchSkill(model, fetcher=Fetcher()).run("检查点", [claim["source_url"]])

    assert isinstance(pack.claims[0].retrieved_at, datetime)
    assert pack.claims[0].source_snapshot_hash == "snapshot-hash"


@pytest.mark.asyncio
async def test_visual_plan_marks_acquisition_as_planned_not_as_a_real_provider():
    article = ArticleDocument(
        titles=["标题"],
        selected_title="标题",
        digest="摘要",
        audience="开发者",
        sections=[ArticleSection(type="paragraph", content="正文")],
        references=[],
        ending="结尾",
    )
    model = FakeModel(
        {
            VisualPlan: {
                "items": [
                    {
                        "kind": "cover",
                        "placement": "cover",
                        "purpose": "封面",
                        "prompt_or_source": "prompt",
                        "source": "ai_generated",
                    }
                ]
            }
        }
    )

    plan = await VisualPlanningSkill(model).run(article, {"ai_generation_available": True})

    assert plan.items[0].provider == "planned"
