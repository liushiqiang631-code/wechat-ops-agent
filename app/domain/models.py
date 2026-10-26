from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.domain.enums import (
    Channel,
    ChannelPostStatus,
    EvidenceType,
    ProbeStatus,
    TaskMode,
    TaskStatus,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class TaskConstraints(DomainModel):
    target_words: int = Field(default=2500, ge=300, le=20_000)
    audience: str = "种植户、农技人员与农业经销商"
    cover_count: int = Field(default=1, ge=0, le=1)
    inline_image_count: int = Field(default=3, ge=0, le=8)
    need_code: bool = False
    auto_push_to_draft: bool = True
    auto_publish: bool = False


class TaskSpec(DomainModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$",
    )
    mode: TaskMode
    request: str = Field(min_length=3)
    topic: str | None = None
    title_hint: str | None = Field(default=None, max_length=100)
    plan_id: str | None = Field(default=None, max_length=36)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    created_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def reject_formal_publish(self) -> TaskSpec:
        if self.constraints.auto_publish:
            raise ValueError("formal publishing is never allowed")
        return self


class TitleCandidate(DomainModel):
    title: str = Field(min_length=3, max_length=100)
    rationale: str


class TitleProposal(DomainModel):
    topic: str
    candidates: list[TitleCandidate] = Field(min_length=3, max_length=6)
    generated_at: datetime = Field(default_factory=datetime.now)


class RepurposedContent(DomainModel):
    task_id: str
    video_script: str
    xiaohongshu_post: str
    moments_blurb: str
    generated_at: datetime = Field(default_factory=datetime.now)


class TopicRecord(DomainModel):
    task_id: str
    topic: str
    mode: TaskMode
    created_at: datetime
    published_at: datetime | None = None
    article_url: str | None = None
    reads: int | None = None
    shares: int | None = None
    favorites: int | None = None
    followers_gained: int | None = None
    measured_at: datetime | None = None


class TaskRecord(TaskSpec):
    status: TaskStatus = TaskStatus.CREATED
    updated_at: datetime = Field(default_factory=datetime.now)
    last_error: str | None = None


class ResearchClaim(DomainModel):
    claim: str = Field(min_length=3)
    source_url: HttpUrl
    source_title: str
    publisher: str
    published_at: datetime | None = None
    retrieved_at: datetime
    source_type: Literal[
        "official_doc", "official_blog", "official_repo", "paper", "standard", "media", "community",
        "knowledge_base",
    ]
    confidence: float = Field(ge=0, le=1)
    quote_or_evidence: str | None = None
    freshness_expires_at: datetime | None = None
    source_snapshot_hash: str | None = None
    prompt_injection_flags: list[str] = Field(default_factory=list)


class SourceSnapshot(DomainModel):
    url: HttpUrl
    title: str
    content_excerpt: str
    retrieved_at: datetime
    content_hash: str
    content_type: str
    trust: Literal["untrusted"] = "untrusted"
    prompt_injection_flags: list[str] = Field(default_factory=list)


class ResearchPack(DomainModel):
    topic: str
    claims: list[ResearchClaim]
    sources: list[HttpUrl]
    limitations: list[str] = Field(default_factory=list)
    search_hits: list[WebSearchHit] = Field(default_factory=list)
    supplemental_queries: list[str] = Field(default_factory=list, max_length=3)
    # Only the retrieval service populates this field; never ask a model to recreate originals.
    source_snapshots: SkipJsonSchema[list[SourceSnapshot]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_claims(self) -> ResearchPack:
        if not self.claims:
            raise ValueError("at least one claim is required")
        return self


class WebSearchHit(DomainModel):
    url: HttpUrl
    title: str
    snippet: str = ""


class WebSearchResult(DomainModel):
    query: str
    hits: list[WebSearchHit] = Field(default_factory=list)
    provider: str = "jina_bing"
    error: str | None = None


class AnalyticsFinding(DomainModel):
    finding: str
    evidence: list[str] = Field(default_factory=list)


class AnalyticsReport(DomainModel):
    period: str
    key_findings: list[AnalyticsFinding] = Field(default_factory=list)
    winning_topics: list[str] = Field(default_factory=list)
    weak_topics: list[str] = Field(default_factory=list)
    reader_signals: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


class TopicScoreBreakdown(DomainModel):
    historical_performance: float = Field(ge=0, le=30)
    positioning_fit: float = Field(ge=0, le=35)
    timeliness: float = Field(ge=0, le=25)
    content_gap: float = Field(ge=0, le=20)
    executability: float = Field(ge=0, le=10)

    @property
    def total(self) -> float:
        return sum(self.model_dump().values())


class TopicCandidate(DomainModel):
    topic: str
    score: float = Field(ge=0, le=100)
    score_breakdown: TopicScoreBreakdown
    reasons: list[str]
    evidence: list[str]
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def score_matches_breakdown(self) -> TopicCandidate:
        if abs(self.score - self.score_breakdown.total) > 5:
            raise ValueError("topic score must match the score breakdown")
        return self


class EditorialSectionPlan(DomainModel):
    heading: str = Field(min_length=3, max_length=80)
    purpose: str = Field(min_length=3)
    key_question: str = Field(min_length=3)
    claim_refs: list[str] = Field(default_factory=list)
    example_or_code: str | None = None
    takeaway: str = Field(min_length=3)
    kind: Literal["context", "mechanism", "practice", "boundary", "action"]


class EditorialBlueprint(DomainModel):
    version: Literal["1.0"] = "1.0"
    topic: str = Field(min_length=3)
    reader_problem: str = Field(min_length=10)
    reader_outcome: str = Field(min_length=10)
    thesis: str = Field(min_length=10)
    opening_hook: str = Field(min_length=10, max_length=180)
    structure: Literal["问题-方案-行动", "结论-证据-实战", "对比-决策", "源码拆解"]
    sections: list[EditorialSectionPlan] = Field(min_length=5, max_length=8)
    boundaries: list[str] = Field(min_length=1)
    action_checklist: list[str] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def require_depth_sections(self) -> EditorialBlueprint:
        kinds = {section.kind for section in self.sections}
        required = {"mechanism", "practice", "boundary", "action"}
        if not required <= kinds:
            raise ValueError(
                "editorial blueprint requires mechanism, practice, boundary and action"
            )
        return self


class ArticleSection(DomainModel):
    type: Literal[
        "paragraph",
        "heading",
        "code",
        "figure",
        "table",
        "list",
        "callout",
        "steps",
        "quote",
    ]
    content: str | None = None
    level: int | None = Field(default=None, ge=1, le=3)
    language: str | None = None
    asset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    caption: str | None = None
    rows: list[list[str]] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    code_status: Literal["verified", "pseudocode"] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_style_section(cls, value: Any) -> Any:
        # Normalize only the known, lossless legacy style form; keep other types strict.
        if isinstance(value, dict) and value.get("type") == "pill":
            content = value.get("content")
            if isinstance(content, str):
                body = content.strip().removeprefix("%pill ").strip()
                parts = body.rsplit(maxsplit=1)
                if len(parts) == 2 and parts[1] in {"orange", "green", "purple", "blue", "red"}:
                    return {**value, "type": "paragraph", "content": "%pill " + body}
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> ArticleSection:
        if self.type == "heading" and self.level is None:
            raise ValueError("heading level is required")
        if self.type in {"paragraph", "heading", "code", "callout", "quote"} and not self.content:
            raise ValueError(f"{self.type} content is required")
        if self.type == "steps" and not self.items:
            raise ValueError("steps items are required")
        return self


class ArticleDocument(DomainModel):
    titles: list[str] = Field(min_length=1, max_length=10)
    selected_title: str
    digest: str
    audience: str
    sections: list[ArticleSection] = Field(min_length=1)
    references: list[HttpUrl] = Field(default_factory=list)
    ending: str
    intentional_error_count: Literal[0] = 0
    blueprint_version: str | None = None
    quality_summary: str | None = None


class ArticleSupplement(DomainModel):
    """Only the sections needed to remedy deterministic quality gaps."""

    sections: list[ArticleSection] = Field(min_length=1, max_length=8)
    ending: str | None = None
    quality_summary: str | None = Field(default=None, max_length=300)


class ArticleQualityIssue(DomainModel):
    code: str
    message: str
    section_index: int | None = None


class ArticleQualityReport(DomainModel):
    passed: bool
    word_count: int
    minimum_word_count: int
    heading_count: int
    invalid_claim_refs: list[str] = Field(default_factory=list)
    issues: list[ArticleQualityIssue] = Field(default_factory=list)


class GenUiNode(DomainModel):
    """A declarative, non-executable UI node produced by the model."""

    type: Literal[
        "group",
        "text",
        "callout",
        "metric_row",
        "metric",
        "checklist",
        "check",
        "action",
        "divider",
    ]
    title: str | None = Field(default=None, max_length=120)
    label: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, max_length=1_500)
    value: str | None = Field(default=None, max_length=80)
    tone: Literal["neutral", "good", "warning", "danger"] = "neutral"
    checked: bool | None = None
    action: str | None = Field(default=None, max_length=60)
    items: list[GenUiNode] = Field(default_factory=list, max_length=30)


class GenUiDocument(DomainModel):
    version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=2, max_length=120)
    summary: str | None = Field(default=None, max_length=300)
    nodes: list[GenUiNode] = Field(min_length=1, max_length=40)


class GenUiValidationIssue(DomainModel):
    code: str
    message: str
    path: str


class GenUiValidationReport(DomainModel):
    passed: bool
    node_count: int
    max_depth_seen: int
    issues: list[GenUiValidationIssue] = Field(default_factory=list)


class WeeklyPlanItem(DomainModel):
    day: str
    topic: str = Field(min_length=3)
    format: Literal["深度长文", "案例拆解", "框架对比", "源码实战", "热点解读"]
    purpose: str
    source_notes: str = Field(default="")


class WeeklyPlan(DomainModel):
    week_start: str
    items: list[WeeklyPlanItem] = Field(min_length=3, max_length=7)
    rationale: list[str] = Field(default_factory=list)


class VisualItem(DomainModel):
    kind: Literal["cover", "mermaid", "graphviz", "code", "concept"]
    placement: str
    purpose: str
    prompt_or_source: str
    # A plan can reserve an acquisition path without claiming it is the
    # provider that ultimately produced the asset. The materialized asset
    # manifest records the actual provider.
    provider: Literal["deterministic", "planned", "disabled"] = "disabled"
    # How the raster image should be obtained: AI generation (SiliconFlow) or a
    # web image search. Deterministic diagrams (mermaid/graphviz/code) keep
    # provider="deterministic" and leave source unset.
    source: Literal["ai_generated", "web_search", "knowledge_base"] | None = None
    knowledge_image_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    caption: str | None = None


class VisualPlan(DomainModel):
    items: list[VisualItem] = Field(default_factory=list)
    concept_image_generation_enabled: bool = False


class WebImageCandidate(DomainModel):
    title: str
    thumb_url: str
    original_url: str
    license_name: str
    author: str | None = None
    source_page: str
    width: int | None = None
    height: int | None = None


class AssetRecord(DomainModel):
    asset_id: str
    kind: str
    caption: str | None = None
    source: Literal["ai_generated", "web_search", "knowledge_base"] | None = None
    provider: str | None = None
    query_or_prompt: str | None = None
    local_path: str | None = None
    file_name: str | None = None
    content_type: str | None = None
    sha256: str | None = None
    source_url: str | None = None
    license_name: str | None = None
    author: str | None = None
    status: Literal["ready", "failed", "skipped"] = "ready"
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AssetManifest(DomainModel):
    task_id: str
    items: list[AssetRecord] = Field(default_factory=list)
    ai_generation_configured: bool = False
    web_search_configured: bool = False


class StepLog(DomainModel):
    node: str
    label: str
    status: Literal["running", "done", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    message: str | None = None


class StepRunReport(DomainModel):
    task_id: str
    status: Literal["running", "succeeded", "failed"]
    run_started_at: datetime
    run_finished_at: datetime | None = None
    total_duration_ms: int | None = None
    steps: list[StepLog] = Field(default_factory=list)


class ReviewIssue(DomainModel):
    severity: Literal["blocker", "major", "minor"]
    code: str
    message: str
    section_index: int | None = None
    suggested_fix: str | None = None


class ReviewReport(DomainModel):
    score: int = Field(ge=0, le=100)
    fact_source_score: int = Field(ge=0, le=25)
    author_voice_score: int = Field(ge=0, le=15)
    passed: bool
    issues: list[ReviewIssue] = Field(default_factory=list)
    revision_round: int = Field(default=0, ge=0, le=2)
    intentional_error_count: Literal[0] = 0


class CapabilityCheck(DomainModel):
    name: str
    status: ProbeStatus
    evidence_type: EvidenceType
    error_code: int | str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CapabilityReport(DomainModel):
    account_name: str
    account_app_id_suffix: str | None = None
    generated_at: datetime = Field(default_factory=datetime.now)
    checks: list[CapabilityCheck]
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class DraftReceipt(DomainModel):
    idempotency_key: str
    task_id: str
    media_id: str
    content_hash: str
    evidence_type: EvidenceType
    created_at: datetime = Field(default_factory=datetime.now)


class PublicationRecord(DomainModel):
    task_id: str
    article_url: HttpUrl
    published_at: datetime
    draft_media_id: str
    final_content_hash: str | None = None


class MetricRecord(DomainModel):
    metric_date: datetime
    article_id: str
    article_title: str
    reads: int = Field(ge=-1)
    shares: int = Field(ge=0)
    favorites: int = Field(ge=0)
    followers_gained: int = Field(ge=0)
    source_type: Literal["api", "csv", "xlsx", "manual"]
    source_record_id: str
    imported_at: datetime = Field(default_factory=datetime.now)


class MetricImportResult(DomainModel):
    records: list[MetricRecord]
    field_mapping: dict[str, str]
    source_file: str
    skipped_rows: int = 0


class DataQualityReport(DomainModel):
    total_records: int
    missing_rates: dict[str, float]
    duplicate_count: int
    anomaly_count: int
    delay_days: float | None
    source_types: list[str]
    confidence: float = Field(ge=0, le=1)
    limitations: list[str]


class HtmlSentinelReport(DomainModel):
    passed: bool
    checks: dict[str, bool]
    missing: list[str] = Field(default_factory=list)


class EditDiffReport(DomainModel):
    title_changed: bool
    deleted_paragraph_count: int
    added_paragraph_count: int
    replacement_rate: float = Field(ge=0, le=1)
    structural_changes: list[str] = Field(default_factory=list)
    reusable_rules: list[str] = Field(default_factory=list)


class MetricWindow(DomainModel):
    period: str
    article_count: int
    reads: int
    shares: int
    favorites: int
    followers_gained: int
    read_per_article: float


class ArtifactRef(DomainModel):
    task_id: str
    name: str
    version: int
    path: str
    sha256: str
    created_at: datetime = Field(default_factory=datetime.now)


class SkillRecord(DomainModel):
    name: str
    title: str
    description: str
    category: str
    version: str
    builtin: bool = False
    locked: bool = False
    enabled: bool = True


class McpServerConfig(DomainModel):
    name: str = Field(min_length=1, max_length=60)
    url: HttpUrl
    transport: Literal["streamable_http"] = "streamable_http"
    description: str = ""
    enabled: bool = True


class McpToolInfo(DomainModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpServerStatus(DomainModel):
    name: str
    url: str
    transport: str
    enabled: bool
    status: ProbeStatus
    message: str | None = None
    tools: list[McpToolInfo] = Field(default_factory=list)
    latency_ms: int | None = None
    probed_at: datetime | None = None


class ChannelAccount(DomainModel):
    key: Channel
    display_name: str = Field(min_length=1, max_length=60)
    handle: str = Field(min_length=1, max_length=80)
    account_type: str = Field(min_length=1, max_length=40)
    status: Literal["active", "paused"] = "active"
    followers: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=datetime.now)


class ChannelPost(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    channel: Channel
    content_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    excerpt: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=40)
    status: ChannelPostStatus = ChannelPostStatus.DRAFT
    cover_seed: str = Field(default="", max_length=80)
    task_id: str | None = None
    script_id: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    favorites: int = Field(default=0, ge=0)
    source: Literal["manual", "agent", "demo"] = "manual"
    last_error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ScriptBeat(DomainModel):
    time_range: str = Field(min_length=1, max_length=20)
    shot: str = Field(min_length=1, max_length=200)
    voiceover: str = Field(min_length=1, max_length=1_000)
    on_screen_text: str | None = Field(default=None, max_length=200)


class VideoScript(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(min_length=2, max_length=120)
    topic: str = Field(min_length=2, max_length=200)
    channel: Channel
    duration_seconds: int = Field(ge=15, le=600)
    audience: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=2, max_length=300)
    beats: list[ScriptBeat] = Field(min_length=1, max_length=12)
    ending: str = Field(min_length=1, max_length=400)
    cover_idea: str | None = Field(default=None, max_length=300)
    hashtags: list[str] = Field(default_factory=list, max_length=10)
    article_angle: str | None = Field(default=None, max_length=400)
    status: Literal["draft", "converted"] = "draft"
    source: Literal["model", "manual", "demo"] = "model"
    task_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def voiceover_text(self) -> str:
        parts = [self.hook]
        parts.extend(beat.voiceover for beat in self.beats)
        parts.append(self.ending)
        return "\n".join(parts)


class ScriptGenerateRequest(DomainModel):
    topic: str = Field(min_length=2, max_length=120)
    channel: Channel = Channel.SHIPINHAO
    duration_seconds: int = Field(default=60, ge=15, le=600)
    audience: str = Field(default="关注 AI 效率的职场人", max_length=120)
    key_points: list[str] = Field(default_factory=list, max_length=6)
    tone: str = Field(default="专业但口语化", max_length=60)


class ChannelPostCreate(DomainModel):
    channel: Channel
    content_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    excerpt: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=40)
    status: ChannelPostStatus = ChannelPostStatus.DRAFT
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    favorites: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_dates(self) -> ChannelPostCreate:
        if self.status == ChannelPostStatus.PUBLISHED and self.published_at is None:
            self.published_at = datetime.now()
        if self.status == ChannelPostStatus.SCHEDULED and self.scheduled_at is None:
            raise ValueError("待发布内容需要 scheduled_at")
        return self


class ActivityLog(DomainModel):
    id: int | None = None
    kind: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=500)
    channel: Channel | None = None
    ref_id: str | None = Field(default=None, max_length=80)
    created_at: datetime = Field(default_factory=datetime.now)
