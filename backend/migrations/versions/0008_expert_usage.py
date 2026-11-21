"""Record provider-reported usage for Expert runs."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ll_expert_usage_calls", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("run_id", sa.String(36), sa.ForeignKey("ll_runs.id"), nullable=False),
                    sa.Column("data", sa.JSON(), nullable=False))
    op.create_index("ix_ll_expert_usage_calls_run_id", "ll_expert_usage_calls", ["run_id"])


def downgrade():
    op.drop_index("ix_ll_expert_usage_calls_run_id", table_name="ll_expert_usage_calls")
    op.drop_table("ll_expert_usage_calls")
