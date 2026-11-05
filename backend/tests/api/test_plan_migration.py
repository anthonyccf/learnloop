from pathlib import Path

from sqlalchemy import inspect, text

from learnloop.persistence.database import make_engine


def test_additive_migration_keeps_existing_course_records(tmp_path):
    from alembic import command
    from alembic.config import Config

    engine = make_engine("sqlite:///" + (tmp_path / "migration.db").as_posix())
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            connection.execute(
                text(
                    "INSERT INTO ll_courses (id, owner_id, title, created_at) "
                    "VALUES ('kept','owner','Preserved course',CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ll_sessions (id, course_id, owner_id, status) "
                    "VALUES ('saved-session','kept','owner','active')"
                )
            )
            command.upgrade(config, "head")
            assert (
                connection.scalar(text("SELECT title FROM ll_courses WHERE id='kept'"))
                == "Preserved course"
            )
            assert (
                connection.scalar(text("SELECT status FROM ll_sessions WHERE id='saved-session'"))
                == "active"
            )
            assert (
                connection.scalar(
                    text("SELECT release_id FROM ll_sessions WHERE id='saved-session'")
                )
                is None
            )
            assert connection.scalar(text("PRAGMA foreign_key_check")) is None
            assert {
                "ll_learning_plans",
                "ll_plan_revisions",
                "ll_response_details",
                "ll_chunk_embeddings",
            } <= set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
