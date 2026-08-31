"""Topic feedback records, title hints and weekly-plan links.

Adds the `topic_records` table for post-publish metric feedback, and extends
`content_tasks` with a `title_hint` (human-selected title) and a `plan_id`
(link to the weekly plan that produced the task).
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_topic_records_and_plan_id"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_tasks", sa.Column("title_hint", sa.String(100), nullable=True))
    op.add_column("content_tasks", sa.Column("plan_id", sa.String(36), nullable=True))
    op.create_index("ix_content_tasks_plan_id", "content_tasks", ["plan_id"])
    op.create_table(
        "topic_records",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("article_url", sa.Text()),
        sa.Column("reads", sa.Integer()),
        sa.Column("shares", sa.Integer()),
        sa.Column("favorites", sa.Integer()),
        sa.Column("followers_gained", sa.Integer()),
        sa.Column("measured_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("topic_records")
    op.drop_index("ix_content_tasks_plan_id", table_name="content_tasks")
    op.drop_column("content_tasks", "plan_id")
    op.drop_column("content_tasks", "title_hint")
