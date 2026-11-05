from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

from learnloop.core.config import get_settings


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """SQLite drops offsets; restore UTC on reads just as PostgreSQL does."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Database timestamps must be timezone-aware")
            value = value.astimezone(UTC)
            if dialect.name == "sqlite":
                value = value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class TransactionalSessionMaker(sessionmaker):
    @contextmanager
    def begin(self):
        with self() as session, session.begin():
            if self.kw["bind"].dialect.name == "sqlite":
                # Reserve the writer before any read/modify/write decision. SQLite
                # ignores FOR UPDATE; this supplies the equivalent coarse lock.
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                session.connection().exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            yield session


class Course(Base):
    __tablename__ = "ll_courses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Document(Base):
    __tablename__ = "ll_documents"
    __table_args__ = (UniqueConstraint("course_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"), index=True)
    filename: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    # Candidate output is retained for review; only published graphs enter the course map.
    graph: Mapped[dict] = mapped_column(JSON, default=dict)


class Chunk(Base):
    __tablename__ = "ll_chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("ll_documents.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class CourseRelease(Base):
    __tablename__ = "ll_course_releases"
    __table_args__ = (
        UniqueConstraint("course_id", "version"),
        UniqueConstraint("course_id", "sha256"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ll_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class LearnerState(Base):
    __tablename__ = "ll_learner_states"
    __table_args__ = (UniqueConstraint("course_id", "owner_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"))
    owner_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class StudySession(Base):
    __tablename__ = "ll_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="active")
    release_id: Mapped[str | None] = mapped_column(
        ForeignKey("ll_course_releases.id"), nullable=True
    )
    current_activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Activity(Base):
    __tablename__ = "ll_activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("ll_sessions.id"), index=True)
    concept_id: Mapped[str] = mapped_column(String(100))
    difficulty: Mapped[str] = mapped_column(String(20), default="intermediate")
    public: Mapped[dict] = mapped_column(JSON)
    private: Mapped[dict] = mapped_column(JSON)
    hinted: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")


class Submission(Base):
    __tablename__ = "ll_submissions"
    __table_args__ = (
        UniqueConstraint("activity_id"),
        UniqueConstraint("owner_id", "operation_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    activity_id: Mapped[str] = mapped_column(ForeignKey("ll_activities.id"))
    owner_id: Mapped[str] = mapped_column(String(100))
    operation_id: Mapped[str] = mapped_column(String(100))
    expected_version: Mapped[int] = mapped_column(Integer)
    choice_id: Mapped[str] = mapped_column(String(20))
    assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Run(Base):
    __tablename__ = "ll_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(100))
    snapshot: Mapped[dict] = mapped_column(JSON)
    input: Mapped[dict] = mapped_column(JSON)


class LearningPlan(Base):
    __tablename__ = "ll_learning_plans"
    __table_args__ = (UniqueConstraint("course_id", "owner_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"))
    owner_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=0)
    goal: Mapped[dict] = mapped_column(JSON)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PlanRevision(Base):
    __tablename__ = "ll_plan_revisions"
    __table_args__ = (
        UniqueConstraint("owner_id", "operation_id"),
        UniqueConstraint("plan_id", "version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("ll_learning_plans.id"))
    owner_id: Mapped[str] = mapped_column(String(100))
    operation_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    request: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class ResponseDetail(Base):
    __tablename__ = "ll_response_details"
    submission_id: Mapped[str] = mapped_column(ForeignKey("ll_submissions.id"), primary_key=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    timing: Mapped[dict] = mapped_column(JSON)


class RunEvent(Base):
    __tablename__ = "ll_run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("ll_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "ll_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("ll_runs.id"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Command(Base):
    __tablename__ = "ll_commands"
    __table_args__ = (UniqueConstraint("owner_id", "operation_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(String(100))
    operation_id: Mapped[str] = mapped_column(String(100))
    run_id: Mapped[str] = mapped_column(ForeignKey("ll_runs.id"))
    body: Mapped[dict] = mapped_column(JSON)
    receipt: Mapped[dict] = mapped_column(JSON)


class ChunkEmbedding(Base):
    __tablename__ = "ll_chunk_embeddings"
    chunk_id: Mapped[str] = mapped_column(ForeignKey("ll_chunks.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("ll_courses.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("ll_documents.id"), index=True)
    model: Mapped[str] = mapped_column(String(200))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


def make_engine(url: str):
    parsed = make_url(url)
    options = {}
    if parsed.get_backend_name() == "sqlite":
        if parsed.database not in (None, "", ":memory:"):
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, record):
            import sqlite_vec

            connection.enable_load_extension(True)
            try:
                sqlite_vec.load(connection)
            finally:
                connection.enable_load_extension(False)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine


def session_factory(settings=None):
    settings = settings or get_settings()
    return TransactionalSessionMaker(
        make_engine(settings.database_url.get_secret_value()), expire_on_commit=False
    )
