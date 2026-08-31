from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.db.base import Database
from app.repositories.metrics import MetricsRepository
from app.repositories.publications import PublicationRepository
from app.repositories.skills import SkillStateRepository
from app.repositories.tasks import TaskRepository
from app.repositories.topics import TopicRecordRepository
from app.services.analytics.topic_feedback import sync_topic_record_from
from app.services.citations.fetcher import SafeSourceFetcher
from app.services.editorial.quality import evaluate_article
from app.services.images.assets import AssetMaterializer
from app.services.images.dashscope import DashScopeImageClient
from app.services.images.siliconflow import SiliconFlowImageClient
from app.services.images.websearch import WikimediaImageSearch
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
    artifacts: ArtifactStore
    deepseek: DeepSeekClient
    titles: TitleSkill
    repurpose: RepurposeSkill
    skills: SkillRegistry
    mcp: McpManager
    wechat: WeChatClient
    token_manager: TokenManager
    wechat_analytics: WeChatAnalyticsClient
    media: MediaUploader
    drafts: DraftService
    workflow: WorkflowDependencies


def build_container(settings: Settings) -> ApplicationContainer:
    database = Database(settings.database_url)
    database.create_all()
    tasks = TaskRepository(database.session_factory)
    publications = PublicationRepository(database.session_factory)
    metrics = MetricsRepository(database.session_factory)
    topic_records = TopicRecordRepository(database.session_factory)
    artifacts = ArtifactStore(settings.object_storage_path)
    deepseek = DeepSeekClient(settings)
    skill_states = SkillStateRepository(database.session_factory)
    skills = SkillRegistry(skill_states)
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
        ),
        editorial=EditorialPlanningSkill(deepseek),
        writing=WritingSkill(deepseek, registry=skills),
        visuals=VisualPlanningSkill(deepseek),
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
        },
        account_profile={
            "account": settings.wechat_account_name,
            "positioning": "虚构示例账号：面向初学者的软件工程与工具使用教程",
            "content_pillars": [
                "编程入门",
                "开发工具体验",
                "可复现的小型示例",
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
        artifacts=artifacts,
        deepseek=deepseek,
        titles=titles,
        repurpose=repurpose,
        skills=skills,
        mcp=mcp,
        wechat=wechat,
        token_manager=token_manager,
        wechat_analytics=analytics,
        media=media,
        drafts=drafts,
        workflow=workflow,
    )
