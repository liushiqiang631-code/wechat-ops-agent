from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskRow(Base):
    __tablename__ = "content_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str | None] = mapped_column(String(300))
    title_hint: Mapped[str | None] = mapped_column(String(100))
    plan_id: Mapped[str | None] = mapped_column(String(36), index=True)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class TopicRecordRow(Base):
    __tablename__ = "topic_records"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    article_url: Mapped[str | None] = mapped_column(Text)
    reads: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    favorites: Mapped[int | None] = mapped_column(Integer)
    followers_gained: Mapped[int | None] = mapped_column(Integer)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DraftReceiptRow(Base):
    __tablename__ = "draft_receipts"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    media_id: Mapped[str] = mapped_column(String(300), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationRow(Base):
    __tablename__ = "publication_records"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    article_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    draft_media_id: Mapped[str] = mapped_column(String(300), nullable=False)
    final_content_hash: Mapped[str | None] = mapped_column(String(64))


class RawMetricRow(Base):
    __tablename__ = "raw_metrics"
    __table_args__ = (
        UniqueConstraint("source_type", "source_record_id", "metric_date", "metric_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_value: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapabilityReportRow(Base):
    __tablename__ = "capability_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)


class SkillStateRow(Base):
    __tablename__ = "skill_states"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelAccountRow(Base):
    __tablename__ = "channel_accounts"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    handle: Mapped[str] = mapped_column(String(80), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    followers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelPostRow(Base):
    __tablename__ = "channel_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    cover_seed: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    script_id: Mapped[str | None] = mapped_column(String(36), index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    favorites: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoScriptRow(Base):
    __tablename__ = "video_scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    audience: Mapped[str] = mapped_column(String(120), nullable=False)
    hook: Mapped[str] = mapped_column(Text, nullable=False)
    beats_json: Mapped[str] = mapped_column(Text, nullable=False)
    ending: Mapped[str] = mapped_column(Text, nullable=False)
    cover_idea: Mapped[str | None] = mapped_column(Text)
    hashtags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    article_angle: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="model")
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivityLogRow(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
