from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Immutable PostgreSQL DDL generated at revision creation, independent of future ORM changes.
    ddl = Path(__file__).parents[1] / "0001_initial.sql"
    sql = ddl.read_text()
    if op.get_bind().dialect.name == "sqlite":
        sql = sql.replace("TIMESTAMP WITH TIME ZONE", "DATETIME").replace("BYTEA", "BLOB")
        for statement in sql.split(";"):
            if statement.strip():
                op.execute(statement)
    else:
        op.execute(sql)


def downgrade():
    for name in (
        "ll_commands",
        "ll_jobs",
        "ll_run_events",
        "ll_submissions",
        "ll_runs",
        "ll_activities",
        "ll_sessions",
        "ll_learner_states",
        "ll_chunks",
        "ll_documents",
        "ll_courses",
    ):
        op.drop_table(name)
