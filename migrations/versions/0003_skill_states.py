"""Skill enable/disable state for the operator console.

Adds the `skill_states` table so user-installed skills (e.g. human_writing)
can be toggled from the Agent capability page and the choice persists.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_skill_states"
down_revision = "0002_topic_records_and_plan_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_states",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("skill_states")
