"""Initial WeChat operations schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(300)),
        sa.Column("constraints_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
    )
    op.create_table(
        "draft_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("media_id", sa.String(300), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("evidence_type", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_draft_receipts_task_id", "draft_receipts", ["task_id"])
    op.create_table(
        "publication_records",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("article_url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_media_id", sa.String(300), nullable=False),
        sa.Column("final_content_hash", sa.String(64)),
    )
    op.create_table(
        "raw_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_record_id", sa.String(200), nullable=False),
        sa.Column("metric_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("metric_value", sa.String(100), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_type",
            "source_record_id",
            "metric_date",
            "metric_name",
            name="uq_raw_metric_identity",
        ),
    )
    op.create_table(
        "capability_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_type", sa.String(20), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("capability_reports")
    op.drop_table("raw_metrics")
    op.drop_table("publication_records")
    op.drop_index("ix_draft_receipts_task_id", table_name="draft_receipts")
    op.drop_table("draft_receipts")
    op.drop_table("content_tasks")
