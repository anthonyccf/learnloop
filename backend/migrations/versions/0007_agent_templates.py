"""Persist shared agent templates and defaults."""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("ll_agent_templates", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(100), nullable=False), sa.Column("agent", sa.String(20), nullable=False), sa.Column("data", sa.JSON(), nullable=False))
    op.create_index("ix_ll_agent_templates_owner_id", "ll_agent_templates", ["owner_id"])
    op.create_table("ll_agent_template_defaults", sa.Column("owner_id", sa.String(100), primary_key=True), sa.Column("agent", sa.String(20), primary_key=True), sa.Column("template_id", sa.String(36), sa.ForeignKey("ll_agent_templates.id"), nullable=False))

def downgrade():
    op.drop_table("ll_agent_template_defaults")
    op.drop_table("ll_agent_templates")
