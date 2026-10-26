"""Omni-channel tables: accounts, posts, video scripts and activity logs."""

import sqlalchemy as sa
from alembic import op

revision = "0004_omni_channel"
down_revision = "0003_skill_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_accounts",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("display_name", sa.String(60), nullable=False),
        sa.Column("handle", sa.String(80), nullable=False),
        sa.Column("account_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("followers", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "channel_posts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel", sa.String(40), nullable=False, index=True),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, index=True),
        sa.Column("cover_seed", sa.String(80), nullable=False),
        sa.Column("task_id", sa.String(36), index=True),
        sa.Column("script_id", sa.String(36), index=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True), index=True),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("likes", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Integer(), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("favorites", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "video_scripts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("audience", sa.String(120), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("beats_json", sa.Text(), nullable=False),
        sa.Column("ending", sa.Text(), nullable=False),
        sa.Column("cover_idea", sa.Text()),
        sa.Column("hashtags_json", sa.Text(), nullable=False),
        sa.Column("article_angle", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("task_id", sa.String(36), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("channel", sa.String(40)),
        sa.Column("ref_id", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("activity_logs")
    op.drop_table("video_scripts")
    op.drop_table("channel_posts")
    op.drop_table("channel_accounts")
