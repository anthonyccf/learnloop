"""Copy the configured PostgreSQL/Qdrant workspace to a NEW SQLite file.

No source writes, embedding requests, or generation calls are made. Activate the
new DATABASE_URL only after this command succeeds. Stop API/worker writes first.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import inspect, select, text

from learnloop.core.config import ROOT, get_settings
from learnloop.persistence.database import Base, Chunk, Course, Job, make_engine
from learnloop.services.clients import Services
from learnloop.services.vectors import SQLiteVectors


def fingerprint(rows):
    def encode(value):
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        if isinstance(value, (bytes, memoryview)):
            return {"sha256": hashlib.sha256(value).hexdigest()}
        raise TypeError(type(value).__name__)

    encoded = sorted(json.dumps(dict(row), sort_keys=True, default=encode) for row in rows)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def migrate(settings, destination):
    destination = Path(destination).resolve()
    if settings.uses_sqlite:
        raise ValueError("Source must be the original PostgreSQL configuration")
    if destination.exists():
        raise FileExistsError("Destination exists; choose a NEW SQLite file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f"{destination.stem}.import-{uuid4().hex}.db")
    local = settings.model_copy(
        update={"database_url": SecretStr("sqlite:///" + staging.as_posix())}
    )
    source = make_engine(settings.database_url.get_secret_value())
    target = make_engine(local.database_url.get_secret_value())
    vectors = SQLiteVectors(local)
    report = {"tables": {}, "vectors": 0}
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        with target.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with source.connect().execution_options(isolation_level="REPEATABLE READ") as reader:
            reader.execute(text("SET TRANSACTION READ ONLY"))
            active = reader.scalar(
                select(Job.id).where(Job.status.in_(["running", "queued"])).limit(1)
            )
            if active:
                raise ValueError(
                    "Finish or pause active jobs and stop API/worker writes before copying"
                )
            available = set(inspect(reader).get_table_names())
            with target.begin() as writer:
                writer.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
                for table in Base.metadata.sorted_tables:
                    if table.name == "ll_chunk_embeddings":
                        continue
                    if table.name not in available:
                        if table.name == "ll_course_releases":
                            report["tables"][table.name] = 0
                            continue
                        raise ValueError(
                            "Source schema is missing a required table; apply old migrations first"
                        )
                    columns = {c["name"] for c in inspect(reader).get_columns(table.name)}
                    selected = [c for c in table.columns if c.name in columns]
                    missing = set(table.columns.keys()) - columns
                    if missing and (table.name != "ll_sessions" or missing != {"release_id"}):
                        raise ValueError("Source schema has unsupported missing columns")
                    rows = list(reader.execute(select(*selected)).mappings())
                    if rows:
                        writer.execute(table.insert(), [dict(row) for row in rows])
                    copied = list(writer.execute(select(*selected)).mappings())
                    if fingerprint(rows) != fingerprint(copied):
                        raise ValueError(f"Copy verification failed for {table.name}")
                    report["tables"][table.name] = len(rows)
                if writer.exec_driver_sql("PRAGMA foreign_key_check").first():
                    raise ValueError("Copied database failed foreign-key validation")
            chunks = list(
                reader.execute(
                    select(Chunk.__table__, Course.owner_id).join(
                        Course, Course.id == Chunk.course_id
                    )
                ).mappings()
            )
            remote = Services(settings)
            remote.check_collection()
            for start in range(0, len(chunks), 100):
                batch = chunks[start : start + 100]
                points = remote.qdrant(
                    "POST",
                    f"/collections/{settings.qdrant_collection}/points",
                    {"ids": [c["id"] for c in batch], "with_vector": True, "with_payload": True},
                )
                by_id = {str(point["id"]): point for point in points}
                for chunk in batch:
                    point = by_id.get(chunk["id"])
                    if point is None:
                        raise ValueError(
                            "A passage has no stored vector; finish original indexing first"
                        )
                    payload = point.get("payload", {})
                    if any(
                        payload.get(key) != chunk[key]
                        for key in ("owner_id", "course_id", "document_id")
                    ):
                        raise ValueError("Vector ownership does not match the SQL passage")
                    vectors.upsert(chunk, chunk["owner_id"], point["vector"])
                    report["vectors"] += 1
        vectors.check()
        with target.connect() as connection:
            if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                raise ValueError("SQLite integrity check failed")
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        vectors.engine.dispose()
        target.dispose()
        # Publish only a completely verified copy. The source is never modified.
        if destination.exists():
            raise FileExistsError("Destination appeared during migration")
        staging.rename(destination)
        destination.with_suffix(".migration.json").write_text(json.dumps(report, indent=2))
        return report
    finally:
        source.dispose()
        vectors.engine.dispose()
        target.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        report = migrate(get_settings(), args.destination)
    except Exception as exc:
        # Provider/SQL exception text can expose credentials or private records.
        raise SystemExit(
            f"Migration did not complete ({type(exc).__name__}). Source unchanged."
        ) from None
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
