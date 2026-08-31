from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from app.db.base import Database
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import (
    AnalyticsReport,
    ArticleDocument,
    ArticleQualityReport,
    ArticleSection,
    AssetManifest,
    ResearchClaim,
    ResearchPack,
    ReviewIssue,
    ReviewReport,
    StepRunReport,
    TaskSpec,
    TopicCandidate,
    VisualItem,
    VisualPlan,
    WeeklyPlan,
    WeeklyPlanItem,
)
from app.repositories.tasks import TaskRepository
from app.services.models.deepseek import ModelServiceError
from app.services.storage.artifacts import ArtifactStore
from app.workflows.graph import WorkflowDependencies, _review_can_format, run_content_task


class Research:
    async def run(self, topic, source_urls, search=None):
        return ResearchPack(
            topic=topic,
            claims=[
                ResearchClaim(
                    claim="LangGraph 支持持久化检查点。",
                    source_url="https://docs.langchain.com/oss/python/langgraph/persistence",
                    source_title="Persistence",
                    publisher="LangChain",
                    retrieved_at="2026-07-18T00:00:00+08:00",
                    source_type="official_doc",
                    confidence=0.9,
                )
            ],
            sources=["https://docs.langchain.com/oss/python/langgraph/persistence"],
        )


class Writing:
    async def run(self, task, research, *args, **kwargs):
        return ArticleDocument(
            titles=["LangGraph 检查点"],
            selected_title="LangGraph 检查点",
            digest="失败恢复设计。",
            audience="AI 应用开发者",
            sections=[
                ArticleSection(type="paragraph", content="先看进程中断。"),
                ArticleSection(type="paragraph", content="检查点保存可恢复状态。"),
            ],
            references=[str(research.sources[0])],
            ending="把失败恢复设计成正常路径。",
        )


class Visuals:
    async def run(self, article, context=None):
        return VisualPlan(
            items=[
                VisualItem(
                    kind="mermaid",
                    placement="机制之后",
                    purpose="显示恢复路径",
                    prompt_or_source="flowchart LR; A --> B",
                )
            ]
        )


class Reviews:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    async def run(self, article, research, revision_round=0):
        self.calls += 1
        passed = self.calls > self.failures
        return ReviewReport(
            score=90 if passed else 70,
            fact_source_score=23 if passed else 18,
            author_voice_score=12,
            passed=passed,
            revision_round=revision_round,
            issues=(
                []
                if passed
                else [
                    ReviewIssue(
                        severity="major",
                        code="source_gap",
                        message="事实来源不足",
                    )
                ]
            ),
        )


class Editorial:
    async def run(self, task, research):
        from app.domain.models import EditorialBlueprint, EditorialSectionPlan

        return EditorialBlueprint(
            topic=task.topic or task.request,
            reader_problem="读者需要先判断一个 Agent 运行时是否值得引入。",
            reader_outcome="读者能完成一轮安全的最小验证。",
            thesis="运行时边界需要在上线前被明确验证。",
            opening_hook="一次失败任务不应丢掉已经可人工审阅的文章。",
            structure="结论-证据-实战",
            sections=[
                EditorialSectionPlan(
                    heading=f"章节 {index}",
                    purpose="解释一个可验证的问题",
                    key_question=f"问题 {index}",
                    takeaway="完成一次检查",
                    kind=kind,
                )
                for index, kind in enumerate(
                    ["context", "mechanism", "practice", "boundary", "action"]
                )
            ],
            boundaries=["保持人工发布边界。"],
            action_checklist=["检查任务状态", "保留人工审阅稿"],
        )


class Analytics:
    async def run(self, metrics, *, topic_performance=None):
        return AnalyticsReport(
            period="last_30_days",
            key_findings=[],
            confidence=0.6,
            limitations=["样本较少"],
        )


class WeeklyPlanning:
    async def run(self, profile, analytics, request):
        return WeeklyPlan(
            week_start="2026-07-20",
            items=[
                WeeklyPlanItem(
                    day="周一",
                    topic="本周头条：LangGraph 检查点",
                    format="深度长文",
                    purpose="讲清恢复机制",
                ),
                WeeklyPlanItem(
                    day="周三",
                    topic="MCP 边界",
                    format="框架对比",
                    purpose="厘清概念",
                ),
                WeeklyPlanItem(
                    day="周五",
                    topic="Skill 路由",
                    format="案例拆解",
                    purpose="给可复用模式",
                ),
            ],
            rationale=["结合近期数据"],
        )


class FailingResearch:
    async def run(self, topic, source_urls, search=None):
        raise RuntimeError("research backend unavailable")


class Topics:
    async def run(self, profile, analytics):
        return TopicCandidate(
            topic="数据驱动选出的 LangGraph 检查点",
            score=80,
            score_breakdown={
                "historical_performance": 10,
                "positioning_fit": 30,
                "timeliness": 20,
                "content_gap": 12,
                "executability": 8,
            },
            reasons=["工程化定位匹配"],
            evidence=["metrics:30d"],
            confidence=0.6,
            limitations=["历史文章不足 20 篇"],
        )


def dependencies(
    tmp_path: Path, review, *, research=None, weekly=None, topic_sync=None
) -> tuple[TaskRepository, WorkflowDependencies]:
    database = Database(f"sqlite:///{tmp_path / 'workflow.db'}")
    database.create_all()
    repository = TaskRepository(database.session_factory)
    deps = WorkflowDependencies(
        tasks=repository,
        artifacts=ArtifactStore(tmp_path / "outputs"),
        research=research or Research(),
        writing=Writing(),
        visuals=Visuals(),
        review=review,
        analytics=Analytics(),
        topics=Topics(),
        weekly=weekly,
        metrics_provider=lambda: [{"reads": 100, "shares": 8}],
        topic_sync=topic_sync,
        account_profile={"positioning": "大模型应用与 Agent 工程实践"},
        max_review_rounds=2,
    )
    return repository, deps


@pytest.mark.asyncio
async def test_workflow_runs_fixed_topic_to_formatted_with_versioned_artifacts(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert repository.get(task.id).status == TaskStatus.FORMATTED
    artifact_names = {path.name.split(".v", 1)[0] for path in deps.artifacts.list(task.id)}
    assert {"task", "research", "article", "visual_plan", "review", "wechat_html"} <= artifact_names
    assert "<script" not in result["html"].lower()


@pytest.mark.asyncio
async def test_workflow_stops_for_human_after_two_automatic_revisions(tmp_path: Path):
    reviews = Reviews(failures=99)
    repository, deps = dependencies(tmp_path, reviews)
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.NEEDS_HUMAN
    assert repository.get(task.id).status == TaskStatus.NEEDS_HUMAN
    assert reviews.calls == 3


def test_passing_review_with_an_unsupported_claim_cannot_format():
    report = ReviewReport(
        score=92,
        fact_source_score=22,
        author_voice_score=13,
        passed=True,
        revision_round=0,
        issues=[
            ReviewIssue(
                severity="minor",
                code="unsupported_claim_mcp",
                message="MCP 相关事实没有来源支持",
            )
        ],
    )

    assert _review_can_format(report) is False


@pytest.mark.asyncio
async def test_data_driven_mode_runs_analysis_and_topic_before_research(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.DATA_DRIVEN_ARTICLE,
            request="按最近数据选择最值得写的 Agent 工程主题",
        )
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert result["selected_topic"].topic.startswith("数据驱动选出的")
    persisted = repository.get(task.id)
    assert persisted.topic == result["selected_topic"].topic
    artifact_names = {path.name.split(".v", 1)[0] for path in deps.artifacts.list(task.id)}
    assert {"analytics", "topic_strategy"} <= artifact_names


@pytest.mark.asyncio
async def test_workflow_syncs_final_topic_into_feedback_hook(tmp_path: Path):
    synced: list[str] = []
    repository, deps = dependencies(
        tmp_path, Reviews(), topic_sync=lambda task: synced.append(task.topic)
    )
    task = repository.create(
        TaskSpec(
            mode=TaskMode.DATA_DRIVEN_ARTICLE,
            request="按最近数据选择最值得写的 Agent 工程主题",
        )
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert synced == ["数据驱动选出的 LangGraph 检查点"]
    assert repository.get(task.id).topic == "数据驱动选出的 LangGraph 检查点"
    repository, deps = dependencies(tmp_path, Reviews(), weekly=WeeklyPlanning())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.WEEKLY_PLAN,
            request="复盘最近数据并安排下周内容",
        )
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert result["weekly_plan"].items[0].topic == "本周头条：LangGraph 检查点"
    persisted = repository.get(task.id)
    assert persisted.topic == "本周头条：LangGraph 检查点"
    artifact_names = {path.name.split(".v", 1)[0] for path in deps.artifacts.list(task.id)}
    assert {"analytics", "weekly_plan", "article"} <= artifact_names
    plan_tasks = repository.list_by_plan(task.id)
    assert {planned.topic for planned in plan_tasks} == {"MCP 边界", "Skill 路由"}
    assert all(planned.status == TaskStatus.CREATED for planned in plan_tasks)
    assert all(planned.plan_id == task.id for planned in plan_tasks)


@pytest.mark.asyncio
async def test_node_failure_marks_task_failed_with_last_error(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews(), research=FailingResearch())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )

    with pytest.raises(RuntimeError, match="research backend unavailable"):
        await run_content_task(task.id, deps)

    persisted = repository.get(task.id)
    assert persisted.status == TaskStatus.FAILED
    assert persisted.last_error is not None
    assert "research backend unavailable" in persisted.last_error


class FakeMaterializer:
    async def materialize(self, task_id, plan, article):
        from app.domain.models import AssetManifest

        return AssetManifest(task_id=task_id, items=[]), article


class CountingMaterializer(FakeMaterializer):
    def __init__(self):
        self.calls = 0

    async def materialize(self, task_id, plan, article):
        self.calls += 1
        return await super().materialize(task_id, plan, article)


class InvalidRewriteWriting:
    def __init__(self):
        self.calls = 0

    async def run(self, task, research, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ArticleDocument(
                titles=["LangGraph 检查点"],
                selected_title="LangGraph 检查点",
                digest="失败恢复设计。",
                audience="AI 应用开发者",
                sections=[ArticleSection(type="paragraph", content="先保留可人工修改的初稿。")],
                references=[str(research.sources[0])],
                ending="把失败恢复设计成正常路径。",
            )
        error = ModelServiceError("invalid json", code="invalid_output", retryable=True)
        error.raw_output = "{broken-json"
        raise error


class SupplementingWriting:
    def __init__(self):
        self.run_calls = 0
        self.supplement_calls = 0

    async def run(self, task, research, *args, **kwargs):
        self.run_calls += 1
        return ArticleDocument(
            titles=["LangGraph 检查点"],
            selected_title="LangGraph 检查点",
            digest="失败恢复设计。",
            audience="AI 应用开发者",
            sections=[ArticleSection(type="paragraph", content="保留已通过的开头。")],
            references=[str(research.sources[0])],
            ending="先完成最小验证。",
        )

    async def supplement(self, task, research, blueprint, *, previous_article, quality):
        self.supplement_calls += 1
        return previous_article.model_copy(
            update={
                "sections": [
                    *previous_article.sections,
                    ArticleSection(type="heading", level=2, content="实战检查"),
                    ArticleSection(type="paragraph", content="只补足缺失的实战段。"),
                ]
            }
        )


class SequenceQuality:
    def __init__(self):
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return ArticleQualityReport(
            passed=self.calls > 1,
            word_count=2_500,
            minimum_word_count=2_000,
            heading_count=5,
            issues=[],
        )


def failing_quality(*args):
    return ArticleQualityReport(
        passed=False,
        word_count=100,
        minimum_word_count=2_000,
        heading_count=0,
        issues=[],
    )


@pytest.mark.asyncio
async def test_quality_failure_skips_asset_materialization_until_text_is_acceptable(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    materializer = CountingMaterializer()
    deps = dataclasses.replace(
        deps,
        asset_materializer=materializer,
        article_quality=failing_quality,
        editorial=Editorial(),
        max_review_rounds=0,
    )
    task = repository.create(
        TaskSpec(mode=TaskMode.FIXED_TOPIC, request="写 LangGraph 检查点", topic="LangGraph 检查点")
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.NEEDS_HUMAN
    assert materializer.calls == 0
    steps = StepRunReport.model_validate(deps.artifacts.read_json(task.id, "steps"))
    nodes = [step.node for step in steps.steps]
    assert "quality" in nodes
    assert "review" not in nodes
    assert "visual_plan" not in nodes


@pytest.mark.asyncio
async def test_invalid_rewrite_output_becomes_human_handoff_with_saved_raw_text(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews(failures=1))
    deps = dataclasses.replace(deps, writing=InvalidRewriteWriting())
    task = repository.create(
        TaskSpec(mode=TaskMode.FIXED_TOPIC, request="写 LangGraph 检查点", topic="LangGraph 检查点")
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.NEEDS_HUMAN
    assert repository.get(task.id).status == TaskStatus.NEEDS_HUMAN
    saved = deps.artifacts.read_json(task.id, "invalid_model_output")
    assert saved == {"stage": "rewrite", "raw_output": "{broken-json"}


@pytest.mark.asyncio
async def test_quality_repair_uses_a_supplement_instead_of_regenerating_the_article(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    writing = SupplementingWriting()
    deps = dataclasses.replace(
        deps,
        writing=writing,
        editorial=Editorial(),
        article_quality=SequenceQuality(),
        asset_materializer=CountingMaterializer(),
        max_review_rounds=1,
    )
    task = repository.create(
        TaskSpec(mode=TaskMode.FIXED_TOPIC, request="写 LangGraph 检查点", topic="LangGraph 检查点")
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert writing.run_calls == 1
    assert writing.supplement_calls == 1


@pytest.mark.asyncio
async def test_workflow_records_step_timeline_and_asset_manifest(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'steps.db'}")
    database.create_all()
    repository = TaskRepository(database.session_factory)
    deps = WorkflowDependencies(
        tasks=repository,
        artifacts=ArtifactStore(tmp_path / "outputs"),
        research=Research(),
        writing=Writing(),
        visuals=Visuals(),
        review=Reviews(),
        asset_materializer=FakeMaterializer(),
        image_plan_context={
            "ai_generation_available": False,
            "web_search_available": False,
        },
        max_review_rounds=2,
    )
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    steps = StepRunReport.model_validate(deps.artifacts.read_json(task.id, "steps"))
    assert steps.status == "succeeded"
    assert steps.steps[0].node == "plan"
    assert steps.steps[-1].node == "format"
    assert all(step.status in {"done", "running"} for step in steps.steps)
    assert steps.steps[0].duration_ms is not None
    manifest = AssetManifest.model_validate(deps.artifacts.read_json(task.id, "assets"))
    assert manifest.items == []


@pytest.mark.asyncio
async def test_rerun_from_mid_pipeline_state_resets_and_completes(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )
    # Simulate a crash that left the task mid-pipeline (after the write node)
    # by walking the legal path up to WRITTEN without running the workflow.
    repository.transition(task.id, TaskStatus.PLANNED)
    repository.transition(task.id, TaskStatus.RESEARCHED)
    repository.transition(task.id, TaskStatus.WRITTEN)

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert repository.get(task.id).status == TaskStatus.FORMATTED


@pytest.mark.asyncio
async def test_rerunning_a_finished_task_is_rejected(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )
    await run_content_task(task.id, deps)
    assert repository.get(task.id).status == TaskStatus.FORMATTED

    with pytest.raises(ValueError, match="finished state"):
        await run_content_task(task.id, deps)


@pytest.mark.asyncio
async def test_rerun_from_failed_state_resets_and_completes(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )
    repository.transition(task.id, TaskStatus.FAILED)

    result = await run_content_task(task.id, deps)

    assert result["status"] == TaskStatus.FORMATTED
    assert repository.get(task.id).status == TaskStatus.FORMATTED


@pytest.mark.asyncio
async def test_concurrent_runs_on_same_task_are_serialized(tmp_path: Path):
    repository, deps = dependencies(tmp_path, Reviews())
    task = repository.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写 LangGraph 检查点",
            topic="LangGraph 检查点",
        )
    )

    # Overlapping runs must not interleave DB transitions. The lock serializes
    # them: the first completes, the second sees a finished task and is rejected
    # cleanly (never a random "invalid transition").
    with pytest.raises(ValueError, match="finished state"):
        await asyncio.gather(
            run_content_task(task.id, deps),
            run_content_task(task.id, deps),
        )

    assert repository.get(task.id).status == TaskStatus.FORMATTED
