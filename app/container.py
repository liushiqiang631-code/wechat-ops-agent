from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config.settings import Settings
from app.db.base import Database
from app.repositories.activity import ActivityLogRepository
from app.repositories.channels import ChannelRepository
from app.repositories.metrics import MetricsRepository
from app.repositories.publications import PublicationRepository
from app.repositories.scripts import ScriptRepository
from app.repositories.skills import SkillStateRepository
from app.repositories.tasks import TaskRepository
from app.repositories.topics import TopicRecordRepository
from app.services.analytics.topic_feedback import sync_topic_record_from
from app.services.channels.seed import seed_demo_data
from app.services.citations.fetcher import SafeSourceFetcher
from app.services.editorial.quality import evaluate_article
from app.services.images.assets import AssetMaterializer
from app.services.images.dashscope import DashScopeImageClient
from app.services.images.siliconflow import SiliconFlowImageClient
from app.services.images.websearch import WikimediaImageSearch
from app.services.knowledge import KnowledgeBaseClient
from app.services.mcp.manager import McpManager
from app.services.models.deepseek import DeepSeekClient
from app.services.storage.artifacts import ArtifactStore
from app.services.websearch.search import WebSearchService
from app.services.wechat.analytics_client import WeChatAnalyticsClient
from app.services.wechat.client import WeChatClient
from app.services.wechat.draft_service import DraftService
from app.services.wechat.media_uploader import MediaUploader
from app.services.wechat.token_manager import TokenManager
from app.skills.analytics import AnalyticsSkill
from app.skills.editorial_planning import EditorialPlanningSkill
from app.skills.genui import GenUiSkill
from app.skills.registry import SkillRegistry
from app.skills.repurpose import RepurposeSkill
from app.skills.research import ResearchSkill
from app.skills.review import ReviewSkill
from app.skills.script_writing import ScriptWritingSkill
from app.skills.titles import TitleSkill
from app.skills.topic_strategy import TopicStrategySkill
from app.skills.visual_planning import VisualPlanningSkill
from app.skills.weekly_planning import WeeklyPlanningSkill
from app.skills.writing import WritingSkill
from app.workflows.graph import WorkflowDependencies


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    database: Database
    tasks: TaskRepository
    publications: PublicationRepository
    metrics: MetricsRepository
    topic_records: TopicRecordRepository
    channels: ChannelRepository
    scripts: ScriptRepository
    activity: ActivityLogRepository
    artifacts: ArtifactStore
    deepseek: DeepSeekClient
    titles: TitleSkill
    repurpose: RepurposeSkill
    script_writing: ScriptWritingSkill
    skills: SkillRegistry
    mcp: McpManager
    wechat: WeChatClient
    token_manager: TokenManager
    wechat_analytics: WeChatAnalyticsClient
    media: MediaUploader
    drafts: DraftService
    workflow: WorkflowDependencies
    workspace_id: str | None = None
    settings_file: Path | None = None


def build_container(settings: Settings) -> ApplicationContainer:
    database = Database(settings.database_url)
    database.create_all()
    tasks = TaskRepository(database.session_factory)
    publications = PublicationRepository(database.session_factory)
    metrics = MetricsRepository(database.session_factory)
    topic_records = TopicRecordRepository(database.session_factory)
    channels = ChannelRepository(database.session_factory)
    scripts = ScriptRepository(database.session_factory)
    activity = ActivityLogRepository(database.session_factory)
    if settings.seed_demo_data and not channels.accounts_seeded():
        seed_demo_data(
            channels,
            scripts,
            activity,
            now=datetime.now().astimezone(),
            wechat_account_name=settings.wechat_account_name,
        )
    artifacts = ArtifactStore(settings.object_storage_path)
    deepseek = DeepSeekClient(settings)
    script_writing = ScriptWritingSkill(deepseek)
    skill_states = SkillStateRepository(database.session_factory)
    skills = SkillRegistry(skill_states)
    knowledge = KnowledgeBaseClient(settings) if settings.knowledge_base_enabled else None
    if settings.ai_image_generation_available and settings.image_model_provider == "dashscope":
        ai_generator = DashScopeImageClient(settings)
    elif settings.ai_image_generation_available:
        ai_generator = SiliconFlowImageClient(settings)
    else:
        ai_generator = None
    image_search = WikimediaImageSearch()
    materializer = AssetMaterializer(
        artifacts,
        settings,
        ai_generator=ai_generator,
        search=image_search if settings.web_image_search_available else None,
        knowledge=knowledge,
    )
    web_search = WebSearchService(settings) if settings.web_search_available else None
    mcp = McpManager(settings)
    titles = TitleSkill(deepseek)
    repurpose = RepurposeSkill(deepseek)
    source_fetcher = SafeSourceFetcher()
    wechat = WeChatClient(settings)
    token_manager = TokenManager(wechat, settings)
    analytics = WeChatAnalyticsClient(wechat, settings.business_timezone)
    media = MediaUploader(wechat)
    drafts = DraftService(wechat, publications)
    workflow = WorkflowDependencies(
        tasks=tasks,
        artifacts=artifacts,
        research=ResearchSkill(
            deepseek,
            source_fetcher,
            max_extra_sources=min(settings.web_search_max_results, settings.max_sources),
            max_sources=settings.max_sources,
            knowledge=knowledge,
        ),
        editorial=EditorialPlanningSkill(deepseek),
        writing=WritingSkill(deepseek, registry=skills),
        visuals=VisualPlanningSkill(deepseek, knowledge=knowledge),
        review=ReviewSkill(deepseek),
        article_quality=evaluate_article,
        genui=GenUiSkill(deepseek),
        model_budget=deepseek,
        analytics=AnalyticsSkill(deepseek),
        topics=TopicStrategySkill(deepseek),
        weekly=WeeklyPlanningSkill(deepseek),
        metrics_provider=metrics.list,
        topic_performance_provider=topic_records.list_published,
        topic_sync=lambda task: sync_topic_record_from(publications, topic_records, task),
        asset_materializer=materializer,
        web_search=web_search,
        image_plan_context={
            "ai_generation_available": settings.ai_image_generation_available,
            "web_search_available": settings.web_image_search_available,
            "cover_count": 1,
            "inline_image_count": 3,
            "knowledge_base_available": knowledge is not None,
        },
        account_profile={
            "account": settings.wechat_account_name,
            "positioning": "面向种植户、农技人员与农业经销商的农业科普和田间管理公众号",
            "content_pillars": [
                "作物栽培、土壤健康与水肥管理",
                "病虫害识别思路、农时管理与农事误区",
                "有依据的产品应用、农业案例与寻山企业内容",
            ],
        },
        max_review_rounds=settings.max_review_rounds,
        checkpoint_path=settings.workflow_checkpoint_path,
    )
    return ApplicationContainer(
        settings=settings,
        database=database,
        tasks=tasks,
        publications=publications,
        metrics=metrics,
        topic_records=topic_records,
        channels=channels,
        scripts=scripts,
        activity=activity,
        artifacts=artifacts,
        deepseek=deepseek,
        titles=titles,
        repurpose=repurpose,
        script_writing=script_writing,
        skills=skills,
        mcp=mcp,
        wechat=wechat,
        token_manager=token_manager,
        wechat_analytics=analytics,
        media=media,
        drafts=drafts,
        workflow=workflow,
    )
