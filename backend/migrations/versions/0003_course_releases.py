"""Add immutable course releases and nullable session pins; preserve all old data."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ll_course_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("ll_courses.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("ll_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "version"),
        sa.UniqueConstraint("course_id", "sha256"),
    )
    op.create_index("ix_ll_course_releases_course_id", "ll_course_releases", ["course_id"])
    with op.batch_alter_table("ll_sessions") as batch:
        batch.add_column(sa.Column("release_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_ll_sessions_release", "ll_course_releases", ["release_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("ll_sessions") as batch:
        batch.drop_constraint("fk_ll_sessions_release", type_="foreignkey")
        batch.drop_column("release_id")
    op.drop_index("ix_ll_course_releases_course_id", table_name="ll_course_releases")
    op.drop_table("ll_course_releases")
