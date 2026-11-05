"""Persist learning plans, immutable revisions and response diagnostics."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ll_learning_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("ll_courses.id"), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("goal", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("course_id", "owner_id"),
    )
    op.create_table(
        "ll_plan_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("ll_learning_plans.id"), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("operation_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "operation_id"),
        sa.UniqueConstraint("plan_id", "version"),
    )
    op.create_table(
        "ll_response_details",
        sa.Column(
            "submission_id", sa.String(36), sa.ForeignKey("ll_submissions.id"), primary_key=True
        ),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("timing", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("ll_response_details")
    op.drop_table("ll_plan_revisions")
    op.drop_table("ll_learning_plans")
