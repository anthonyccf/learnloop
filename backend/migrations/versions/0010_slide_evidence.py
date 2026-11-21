"""Cache slide transcriptions by source document version and page."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ll_slide_evidence",
        sa.Column("document_id", sa.String(36), sa.ForeignKey("ll_documents.id"), primary_key=True),
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("transcription", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("ll_slide_evidence")
