"""Persist isolated named Tutor workbench learners."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ll_workbench_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("ll_courses.id"), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ll_workbench_memories_course_id", "ll_workbench_memories", ["course_id"])
    op.create_index("ix_ll_workbench_memories_owner_id", "ll_workbench_memories", ["owner_id"])


def downgrade():
    op.drop_table("ll_workbench_memories")
