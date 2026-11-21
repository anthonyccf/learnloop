"""Isolate Expert material checkpoints by run."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ll_run_materials",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("ll_runs.id"), primary_key=True),
        sa.Column("id", sa.String(36), sa.ForeignKey("ll_documents.id"), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("ll_courses.id"), nullable=False),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
    )

    op.create_table(
        "ll_run_hierarchies",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("ll_runs.id"), primary_key=True),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("documents", sa.JSON(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("ll_run_hierarchies")
    op.drop_table("ll_run_materials")
