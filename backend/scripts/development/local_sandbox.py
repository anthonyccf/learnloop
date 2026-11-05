"""Disposable SQLite services for opt-in live checks; never use the main database."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import SecretStr

from learnloop.persistence.database import Base, session_factory
from learnloop.services.clients import Services


@contextmanager
def local_stack(settings, services_type=Services):
    with TemporaryDirectory(prefix="learnloop_sandbox_") as directory:
        path = Path(directory) / "workspace.db"
        settings = settings.model_copy(
            update={"database_url": SecretStr("sqlite:///" + path.as_posix())}
        )
        factory = session_factory(settings)
        services = services_type(settings)
        try:
            Base.metadata.create_all(factory.kw["bind"])
            yield settings, factory, services
        finally:
            services.vectors.engine.dispose()
            factory.kw["bind"].dispose()
