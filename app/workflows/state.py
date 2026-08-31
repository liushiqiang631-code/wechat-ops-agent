from __future__ import annotations

from typing import NotRequired, TypedDict

from app.domain.enums import TaskStatus
from app.domain.models import (
    AnalyticsReport,
    ArticleDocument,
    ArticleQualityReport,
    AssetManifest,
    EditorialBlueprint,
    GenUiDocument,
    ResearchPack,
    ReviewReport,
    TaskRecord,
    TopicCandidate,
    VisualPlan,
    WeeklyPlan,
)


class ContentState(TypedDict):
    task: TaskRecord
    status: TaskStatus
    revision_round: int
    analytics: NotRequired[AnalyticsReport]
    selected_topic: NotRequired[TopicCandidate]
    research: NotRequired[ResearchPack]
    editorial_blueprint: NotRequired[EditorialBlueprint]
    article: NotRequired[ArticleDocument]
    article_quality: NotRequired[ArticleQualityReport]
    genui: NotRequired[GenUiDocument]
    visual_plan: NotRequired[VisualPlan]
    asset_manifest: NotRequired[AssetManifest]
    weekly_plan: NotRequired[WeeklyPlan]
    review: NotRequired[ReviewReport]
    html: NotRequired[str]
    error: NotRequired[str]
