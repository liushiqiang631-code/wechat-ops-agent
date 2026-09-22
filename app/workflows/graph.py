from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.config.logging import redact_secrets
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import AssetManifest, TaskSpec
from app.services.formatting.renderer import render_wechat_html
from app.services.formatting.sentinels import check_html_sentinels
from app.services.genui.renderer import render_genui_static_html
from app.services.genui.validator import validate_genui
from app.services.models.deepseek import ModelServiceError
from app.services.progress.step_recorder import StepRecorder
from app.workflows.state import ContentState

logger = logging.getLogger(__name__)

DEFAULT_OFFICIAL_SOURCES = [
    "https://docs.langchain.com/oss/python/langgraph/overview",
    "https://modelcontextprotocol.io/docs",
    "https://api-docs.deepseek.com/",
    "https://developers.weixin.qq.com/doc/offiaccount/Getting_Started/Overview.html",
    "https://github.com/openai/openai-agents-python",
]

ADDITIVE_QUALITY_ISSUES = {
    "article_too_short",
    "too_few_sections",
    "missing_evidence_bindings",
    "blueprint_evidence_not_used",
    "missing_mechanism_section",
    "missing_practice_section",
    "missing_boundary_section",
    "missing_action_section",
    "missing_verified_code",
}


@dataclass(slots=True)
class WorkflowDependencies:
    tasks: object
    artifacts: object
    research: object
    writing: object
    visuals: object
    review: object
    editorial: object | None = None
    article_quality: object | None = None
    genui: object | None = None
    model_budget: object | None = None
    analytics: object | None = None
    topics: object | None = None
    weekly: object | None = None
    metrics_provider: object | None = None
    topic_performance_provider: object | None = None
    topic_sync: object | None = None
    asset_materializer: object | None = None
    image_plan_context: dict | None = None
    web_search: object | None = None
    account_profile: dict = field(default_factory=dict)
    max_review_rounds: int = 2
    source_urls: list[str] = field(default_factory=lambda: list(DEFAULT_OFFICIAL_SOURCES))
    checkpoint_path: Path | None = None
    checkpointer: object = field(
        default_factory=lambda: InMemorySaver(serde=JsonPlusSerializer(pickle_fallback=True))
    )


def _topic_performance(deps: WorkflowDependencies) -> list[dict]:
    """Measured performance of previously published topics, for analytics input."""
    if deps.topic_performance_provider is None:
        return []
    records = deps.topic_performance_provider()
    result: list[dict] = []
    for record in records:
        reads = getattr(record, "reads", None)
        if reads is None:
            continue
        published_at = getattr(record, "published_at", None)
        result.append(
            {
                "topic": getattr(record, "topic", ""),
                "published_at": published_at.isoformat() if published_at else None,
                "reads": reads,
                "shares": getattr(record, "shares", 0) or 0,
                "favorites": getattr(record, "favorites", 0) or 0,
                "followers_gained": getattr(record, "followers_gained", 0) or 0,
            }
        )
    return result


def _materialize_plan_tasks(deps: WorkflowDependencies, plan_task_id: str, plan: object) -> None:
    """Create CREATED tasks for the remaining weekly plan items (idempotent)."""
    existing_topics = {task.topic for task in deps.tasks.list_by_plan(plan_task_id)}
    for item in plan.items[1:]:  # type: ignore[attr-defined]
        if item.topic in existing_topics:  # type: ignore[attr-defined]
            continue
        deps.tasks.create(
            TaskSpec(
                mode=TaskMode.FIXED_TOPIC,
                request=item.purpose or item.topic,  # type: ignore[attr-defined]
                topic=item.topic,  # type: ignore[attr-defined]
                plan_id=plan_task_id,
            )
        )


def _asset_summary(result: dict) -> str:
    manifest = result.get("asset_manifest")
    if manifest is None:
        return "无需位图素材"
    ready = sum(1 for item in manifest.items if item.status == "ready")
    return f"{ready} 张图片就绪"


def _writing_token_reserve(task: object) -> int:
    constraints = task.constraints
    return max(8_000, constraints.target_words * 3)


def _review_can_format(report: object) -> bool:
    """Allow formatting only when the review has no source-support gaps."""
    if not getattr(report, "passed", False):
        return False
    return not any(
        getattr(issue, "code", "").startswith("unsupported_claim")
        or getattr(issue, "code", "") == "source_gap"
        for issue in getattr(report, "issues", [])
    )


def _quality_can_supplement(report: object) -> bool:
    """Return whether appending sections can resolve every reported quality gap."""
    if getattr(report, "heading_count", 0) > 8:
        return False
    issues = getattr(report, "issues", [])
    return all(getattr(issue, "code", "") in ADDITIVE_QUALITY_ISSUES for issue in issues)


def _tracked(
    recorder: StepRecorder | None,
    node: str,
    label: str,
    message_for=None,
):
    """Wrap a graph node so every step is visible to the console (like Codex).

    Records start/finish/failure of the node with wall-clock timing. Recording
    itself never raises into the pipeline; failures are still re-raised so the
    task is marked FAILED with the real error.
    """

    def decorate(fn):
        async def wrapped(state: ContentState) -> dict:
            if recorder is not None:
                recorder.start(node, label)
            try:
                result = (
                    await fn(state) if asyncio.iscoroutinefunction(fn) else fn(state)
                )
                if recorder is not None:
                    message = message_for(result) if message_for is not None else None
                    recorder.finish(node, message)
                return result
            except Exception as error:
                if recorder is not None:
                    recorder.fail(node, f"{type(error).__name__}: {error}")
                raise

        return wrapped

    return decorate


def build_content_graph(deps: WorkflowDependencies, recorder: StepRecorder | None = None):
    async def data_prepare(state: ContentState) -> dict:
        if deps.analytics is None or deps.topics is None or deps.metrics_provider is None:
            raise RuntimeError("data-driven workflow dependencies are not configured")
        records = deps.metrics_provider()
        metrics = [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            for record in records
        ]
        analytics = await deps.analytics.run(
            metrics, topic_performance=_topic_performance(deps)
        )
        selected = await deps.topics.run(deps.account_profile, analytics)
        deps.artifacts.write_json(state["task"].id, "analytics", analytics.model_dump(mode="json"))
        deps.artifacts.write_json(
            state["task"].id, "topic_strategy", selected.model_dump(mode="json")
        )
        updated = deps.tasks.transition(state["task"].id, TaskStatus.DATA_SYNCED)
        updated = deps.tasks.set_topic(updated.id, selected.topic)
        return {
            "task": updated,
            "status": updated.status,
            "analytics": analytics,
            "selected_topic": selected,
        }

    def choose_start(state: ContentState) -> str:
        if state["task"].mode == TaskMode.DATA_DRIVEN_ARTICLE:
            return "data_prepare"
        if state["task"].mode == TaskMode.WEEKLY_PLAN:
            return "weekly_plan"
        return "plan"

    async def plan(state: ContentState) -> dict:
        task = state["task"]
        deps.artifacts.write_json(task.id, "task", task.model_dump(mode="json"))
        updated = deps.tasks.transition(task.id, TaskStatus.PLANNED)
        return {"task": updated, "status": updated.status}

    async def weekly_plan(state: ContentState) -> dict:
        if deps.weekly is None or deps.analytics is None or deps.metrics_provider is None:
            raise RuntimeError("weekly-plan workflow dependencies are not configured")
        records = deps.metrics_provider()
        metrics = [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            for record in records
        ]
        analytics = await deps.analytics.run(
            metrics, topic_performance=_topic_performance(deps)
        )
        plan = await deps.weekly.run(deps.account_profile, analytics, state["task"].request)
        deps.artifacts.write_json(state["task"].id, "analytics", analytics.model_dump(mode="json"))
        deps.artifacts.write_json(state["task"].id, "weekly_plan", plan.model_dump(mode="json"))
        updated = deps.tasks.transition(state["task"].id, TaskStatus.PLANNED)
        updated = deps.tasks.set_topic(updated.id, plan.items[0].topic)
        _materialize_plan_tasks(deps, state["task"].id, plan)
        return {
            "task": updated,
            "status": updated.status,
            "analytics": analytics,
            "weekly_plan": plan,
        }

    async def research(state: ContentState) -> dict:
        task = state["task"]
        topic = (
            state["selected_topic"].topic
            if "selected_topic" in state
            else task.topic or task.request
        )
        pack = await deps.research.run(topic, deps.source_urls, search=deps.web_search)
        deps.artifacts.write_json(task.id, "research", pack.model_dump(mode="json"))
        updated = deps.tasks.transition(task.id, TaskStatus.RESEARCHED)
        return {"task": updated, "status": updated.status, "research": pack}

    async def write(state: ContentState) -> dict:
        if deps.model_budget is not None:
            deps.model_budget.reserve_token_budget(
                _writing_token_reserve(state["task"]) * deps.max_review_rounds
            )
        if "editorial_blueprint" in state:
            article = await deps.writing.run(
                state["task"], state["research"], state["editorial_blueprint"]
            )
        else:
            article = await deps.writing.run(state["task"], state["research"])
        deps.artifacts.write_json(state["task"].id, "article", article.model_dump(mode="json"))
        updated = deps.tasks.transition(state["task"].id, TaskStatus.WRITTEN)
        return {"task": updated, "status": updated.status, "article": article}

    async def editorial_plan(state: ContentState) -> dict:
        if deps.editorial is None:
            return {}
        blueprint = await deps.editorial.run(state["task"], state["research"])
        deps.artifacts.write_json(
            state["task"].id,
            "editorial_blueprint",
            blueprint.model_dump(mode="json"),
        )
        return {"editorial_blueprint": blueprint}

    async def visual_plan(state: ContentState) -> dict:
        if deps.image_plan_context:
            plan = await deps.visuals.run(state["article"], deps.image_plan_context)
        else:
            plan = await deps.visuals.run(state["article"])
        deps.artifacts.write_json(state["task"].id, "visual_plan", plan.model_dump(mode="json"))
        updated = deps.tasks.transition(state["task"].id, TaskStatus.ASSETS_READY)
        return {"task": updated, "status": updated.status, "visual_plan": plan}

    async def visual_assets(state: ContentState) -> dict:
        """Materialize raster images (AI generation or web search) for figures.

        Image acquisition is best-effort by design: a failed image never blocks
        the article. Every attempt is recorded in the ``assets`` artifact with
        provenance (source, license, author) for human review.
        """
        if deps.asset_materializer is None:
            manifest = AssetManifest(task_id=state["task"].id)
            return {"asset_manifest": manifest}
        manifest, updated_article = await deps.asset_materializer.materialize(
            state["task"].id, state["visual_plan"], state["article"]
        )
        deps.artifacts.write_json(state["task"].id, "assets", manifest.model_dump(mode="json"))
        if updated_article is not state["article"]:
            deps.artifacts.write_json(
                state["task"].id, "article", updated_article.model_dump(mode="json")
            )
        return {"article": updated_article, "asset_manifest": manifest}

    async def review(state: ContentState) -> dict:
        report = await deps.review.run(
            state["article"],
            state["research"],
            revision_round=state["revision_round"],
        )
        deps.artifacts.write_json(state["task"].id, "review", report.model_dump(mode="json"))
        updated = deps.tasks.transition(state["task"].id, TaskStatus.REVIEWED)
        # The article is now safe for a human to review while assets continue
        # through their best-effort path.
        deps.artifacts.write_json(
            state["task"].id,
            "article_ready",
            {"article_version": "latest", "review_score": report.score},
        )
        return {"task": updated, "status": updated.status, "review": report}

    async def quality(state: ContentState) -> dict:
        if deps.article_quality is None or "editorial_blueprint" not in state:
            return {}
        report = deps.article_quality(
            state["article"],
            state["research"],
            state["task"].constraints,
            state["editorial_blueprint"],
        )
        deps.artifacts.write_json(
            state["task"].id,
            "article_quality",
            report.model_dump(mode="json"),
        )
        return {"article_quality": report}

    def after_quality(state: ContentState) -> str:
        quality_passed = "article_quality" not in state or state["article_quality"].passed
        if quality_passed:
            return "review"
        if state["revision_round"] < deps.max_review_rounds:
            return "rewrite"
        return "human"

    def after_review(state: ContentState) -> str:
        if _review_can_format(state["review"]):
            return "visual_plan"
        if state["revision_round"] < deps.max_review_rounds:
            return "rewrite"
        return "human"

    async def rewrite(state: ContentState) -> dict:
        updated = state["task"]
        if updated.status != TaskStatus.WRITTEN:
            updated = deps.tasks.transition(updated.id, TaskStatus.WRITTEN)
        if deps.model_budget is not None:
            remaining_revisions = max(0, deps.max_review_rounds - state["revision_round"] - 1)
            deps.model_budget.reserve_token_budget(
                _writing_token_reserve(updated) * remaining_revisions
            )
        if "editorial_blueprint" in state:
            quality = state.get("article_quality")
            if (
                quality is not None
                and not quality.passed
                and _quality_can_supplement(quality)
                and hasattr(deps.writing, "supplement")
            ):
                article = await deps.writing.supplement(
                    updated,
                    state["research"],
                    state["editorial_blueprint"],
                    previous_article=state["article"],
                    quality=quality,
                )
            else:
                article = await deps.writing.run(
                    updated,
                    state["research"],
                    state["editorial_blueprint"],
                    previous_article=state["article"],
                    review=state.get("review"),
                    quality=quality,
                )
        else:
            article = await deps.writing.run(updated, state["research"])
        deps.artifacts.write_json(updated.id, "article", article.model_dump(mode="json"))
        return {
            "task": updated,
            "status": updated.status,
            "article": article,
            "revision_round": state["revision_round"] + 1,
        }

    async def format_article(state: ContentState) -> dict:
        genui = None
        supplemental_html = ""
        if deps.genui is not None:
            try:
                candidate = await deps.genui.run(
                    state["article"],
                    state["research"],
                    state["review"],
                    state.get("article_quality"),
                )
                validation = validate_genui(candidate)
                deps.artifacts.write_json(
                    state["task"].id,
                    "genui_validation",
                    validation.model_dump(mode="json"),
                )
                if validation.passed:
                    genui = candidate
                    supplemental_html = render_genui_static_html(candidate)
                    deps.artifacts.write_json(
                        state["task"].id,
                        "genui",
                        candidate.model_dump(mode="json"),
                    )
            except Exception as error:
                logger.warning("GenUI generation skipped: %s", error)
        html = render_wechat_html(state["article"], supplemental_html)
        sentinels = check_html_sentinels(state["article"], html)
        if not sentinels.passed:
            raise ValueError(f"HTML sentinel failure: {sentinels.missing}")
        deps.artifacts.write_json(state["task"].id, "wechat_html", {"html": html})
        updated = deps.tasks.transition(state["task"].id, TaskStatus.FORMATTED)
        result = {"task": updated, "status": updated.status, "html": html}
        if genui is not None:
            result["genui"] = genui
        return result

    async def needs_human(state: ContentState) -> dict:
        updated = deps.tasks.transition(state["task"].id, TaskStatus.NEEDS_HUMAN)
        return {"task": updated, "status": updated.status}

    builder = StateGraph(ContentState)
    builder.add_node(
        "data_prepare",
        _tracked(recorder, "data_prepare", "数据分析与选题评分")(
            data_prepare
        ),
    )
    builder.add_node("plan", _tracked(recorder, "plan", "规划任务约束")(plan))
    builder.add_node(
        "weekly_plan",
        _tracked(recorder, "weekly_plan", "生成周度选题计划")(weekly_plan),
    )
    builder.add_node(
        "research",
        _tracked(
            recorder,
            "research",
            "研究权威来源",
            message_for=lambda result: f"提炼 {len(result['research'].claims)} 条事实",
        )(research),
    )
    builder.add_node(
        "editorial_plan",
        _tracked(recorder, "editorial_plan", "设计深度文章结构")(editorial_plan),
    )
    builder.add_node(
        "write",
        _tracked(
            recorder,
            "write",
            "生成文章初稿",
            message_for=lambda result: f"初稿 {len(result['article'].sections)} 个章节",
        )(write),
    )
    builder.add_node(
        "visual_plan",
        _tracked(recorder, "visual_plan", "规划配图与示意图")(visual_plan),
    )
    builder.add_node(
        "visual_assets",
        _tracked(
            recorder,
            "visual_assets",
            "获取文章配图素材",
            message_for=_asset_summary,
        )(visual_assets),
    )
    builder.add_node(
        "review",
        _tracked(
            recorder,
            "review",
            "事实与结构审核",
            message_for=lambda result: f"审核得分 {result['review'].score}/100",
        )(review),
    )
    builder.add_node(
        "quality",
        _tracked(
            recorder,
            "quality",
            "执行文章深度质量门",
            message_for=lambda result: (
                "质量门已通过"
                if not result or result["article_quality"].passed
                else f"发现 {len(result['article_quality'].issues)} 项深度问题"
            ),
        )(quality),
    )
    builder.add_node(
        "rewrite",
        _tracked(recorder, "rewrite", "按评审意见修改")(rewrite),
    )
    builder.add_node(
        "format",
        _tracked(recorder, "format", "排版微信 HTML")(format_article),
    )
    builder.add_node(
        "human",
        _tracked(recorder, "human", "转交人工处理")(needs_human),
    )
    builder.add_conditional_edges(
        START,
        choose_start,
        {
            "data_prepare": "data_prepare",
            "plan": "plan",
            "weekly_plan": "weekly_plan",
        },
    )
    builder.add_edge("data_prepare", "plan")
    builder.add_edge("weekly_plan", "research")
    builder.add_edge("plan", "research")
    builder.add_edge("research", "editorial_plan")
    builder.add_edge("editorial_plan", "write")
    builder.add_edge("write", "quality")
    builder.add_conditional_edges(
        "quality",
        after_quality,
        {"review": "review", "rewrite": "rewrite", "human": "human"},
    )
    builder.add_conditional_edges(
        "review",
        after_review,
        {"visual_plan": "visual_plan", "rewrite": "rewrite", "human": "human"},
    )
    builder.add_edge("visual_plan", "visual_assets")
    builder.add_edge("visual_assets", "format")
    builder.add_edge("rewrite", "quality")
    builder.add_edge("format", END)
    builder.add_edge("human", END)
    return builder.compile(checkpointer=deps.checkpointer)


# Serializes concurrent runs on the same task. Without this, two overlapping
# invocations (e.g. CLI + web console) interleave state transitions on the same
# row and produce random "invalid transition" failures.
_task_locks: dict[str, asyncio.Lock] = {}


async def run_content_task(
    task_id: str,
    deps: WorkflowDependencies,
    *,
    source_urls: list[str] | None = None,
    progress_observer=None,
) -> ContentState:
    lock = _task_locks.setdefault(task_id, asyncio.Lock())
    async with lock:
        if source_urls is not None:
            deps = dataclasses.replace(deps, source_urls=list(source_urls))
        task = deps.tasks.get(task_id)
        task = deps.tasks.reset_for_retry(task_id)
        finished = {
            TaskStatus.FORMATTED,
            TaskStatus.WECHAT_DRAFTED,
            TaskStatus.NEEDS_HUMAN,
            TaskStatus.HUMAN_REVIEWED,
            TaskStatus.PUBLISHED,
            TaskStatus.POST_ANALYZED,
        }
        if task.status in finished:
            raise ValueError(
                f"task {task_id} has reached a finished state ({task.status.value}); "
                "create a new task to run again"
            )
        if deps.model_budget is not None:
            extra_sources = getattr(deps.research, "max_extra_sources", 0)
            deps.model_budget.assert_task_budget(
                target_words=task.constraints.target_words,
                source_count=len(deps.source_urls) + extra_sources,
                revision_rounds=deps.max_review_rounds,
            )
        recorder = StepRecorder(deps.artifacts, task_id, observer=progress_observer)
        budget_token = (
            deps.model_budget.begin_token_budget() if deps.model_budget is not None else None
        )
        if deps.model_budget is not None:
            deps.model_budget.reserve_token_budget(
                _writing_token_reserve(task) * (1 + deps.max_review_rounds)
            )
        try:
            initial_state = {
                "task": task,
                "status": task.status,
                "revision_round": 0,
            }
            config = {"configurable": {"thread_id": task_id}}
            if deps.checkpoint_path is not None:
                import aiosqlite
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                deps.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(str(deps.checkpoint_path))
                # 与内存检查点保持一致：状态里的领域对象（如 ResearchPack）
                # 需要 pickle 兜底，默认序列化器会直接失败。
                saver = AsyncSqliteSaver(conn, serde=JsonPlusSerializer(pickle_fallback=True))
                try:
                    await saver.setup()
                    runtime_deps = dataclasses.replace(deps, checkpointer=saver)
                    graph = build_content_graph(runtime_deps, recorder)
                    result = await graph.ainvoke(initial_state, config=config)
                finally:
                    await conn.close()
            else:
                graph = build_content_graph(deps, recorder)
                result = await graph.ainvoke(initial_state, config=config)
            recorder.mark_succeeded()
        except ModelServiceError as error:
            message = f"{type(error).__name__}: {error}"
            steps = recorder.snapshot().steps
            failed_step = steps[-1].node if steps else "unknown"
            if error.code == "invalid_output" and failed_step == "rewrite":
                deps.artifacts.write_json(
                    task_id,
                    "invalid_model_output",
                    {
                        "stage": failed_step,
                        "raw_output": redact_secrets(error.raw_output or ""),
                    },
                )
                updated = deps.tasks.transition(task_id, TaskStatus.NEEDS_HUMAN)
                recorder.mark_succeeded()
                return {
                    "task": updated,
                    "status": updated.status,
                    "revision_round": 0,
                    "error": message,
                }
            recorder.mark_failed(message)
            try:
                deps.tasks.transition(task_id, TaskStatus.FAILED, last_error=message[:1000])
            except Exception as state_error:
                logger.warning("could not mark task %s as FAILED: %s", task_id, state_error)
            raise
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            recorder.mark_failed(message)
            try:
                deps.tasks.transition(task_id, TaskStatus.FAILED, last_error=message[:1000])
            except Exception as state_error:
                logger.warning("could not mark task %s as FAILED: %s", task_id, state_error)
            raise
        finally:
            if deps.model_budget is not None and budget_token is not None:
                deps.model_budget.end_token_budget(budget_token)
        # Record the final topic (data-driven / weekly modes set it mid-run) so the
        # post-publish feedback loop attributes performance to the real topic.
        if deps.topic_sync is not None:
            try:
                deps.topic_sync(result["task"])
            except Exception as sync_error:
                logger.warning("could not sync topic record for task %s: %s", task_id, sync_error)
        return result
