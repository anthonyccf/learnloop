"""Store local embeddings alongside application data."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ll_chunk_embeddings",
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("ll_chunks.id"), primary_key=True),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("ll_courses.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("ll_documents.id"), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
    )
    for column in ("owner_id", "course_id", "document_id"):
        op.create_index(f"ix_ll_chunk_embeddings_{column}", "ll_chunk_embeddings", [column])


def downgrade():
    op.drop_table("ll_chunk_embeddings")
