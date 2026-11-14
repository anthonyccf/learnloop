"""Persist responses for questions with multiple options, blanks, or open answers."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ll_response_details", sa.Column("answer", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("ll_response_details") as batch:
        batch.drop_column("answer")
