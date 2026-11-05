from sqlalchemy import select

from learnloop.persistence.database import (
    Base,
    Chunk,
    ChunkEmbedding,
    Course,
    Document,
    session_factory,
)
from learnloop.services.clients import Services


def test_local_cosine_search_is_persistent_scoped_and_idempotent(isolated_settings, monkeypatch):
    from learnloop.core.config import get_settings

    settings = get_settings().model_copy(update={"embedding_dimensions": 2})
    factory = session_factory(settings)
    Base.metadata.create_all(factory.kw["bind"])
    with factory.begin() as db:
        db.add_all(
            [
                Course(id="c1", owner_id="o1", title="One"),
                Course(id="c2", owner_id="o2", title="Two"),
            ]
        )
        for id, course in [("d1", "c1"), ("d2", "c1"), ("d3", "c2")]:
            db.add(
                Document(
                    id=id,
                    course_id=course,
                    filename=id,
                    sha256=id,
                    content_type="text/plain",
                    content=b"test",
                )
            )
        chunks = [
            {"id": "a", "course_id": "c1", "document_id": "d1", "text": "near"},
            {"id": "b", "course_id": "c1", "document_id": "d1", "text": "far"},
            {"id": "c", "course_id": "c1", "document_id": "d2", "text": "near"},
            {"id": "d", "course_id": "c2", "document_id": "d3", "text": "near"},
        ]
        for ordinal, chunk in enumerate(chunks):
            db.add(Chunk(**chunk, ordinal=ordinal, page=1))
    services = Services(settings)
    monkeypatch.setattr(services, "embed", lambda text: [1.0, 0.0] if text != "far" else [0.0, 1.0])
    services.index(chunks[:3], "o1")
    services.index(chunks[3:], "o2")
    services.index(chunks[:1], "o1")
    with factory() as db:
        assert len(list(db.scalars(select(ChunkEmbedding)))) == 4
    assert services.search("query", "o1", "c1", ["d1"], 1) == ["a"]
    assert services.search("query", "o1", "c1", ["d1"], 2) == ["a", "b"]
    assert services.search("query", "o2", "c1", ["d1"], 2) == []
    assert services.search("query", "o1", "c2", ["d3"], 2) == []
    assert services.search("query", "o1", "c1", [], 2) == []
    reopened = Services(settings)
    assert reopened.vectors.search([1.0, 0.0], "o1", "c1", ["d1"], 2) == ["a", "b"]
    assert reopened.check_collection()["extension"].startswith("v0.1.")
    services.vectors.engine.dispose()
    reopened.vectors.engine.dispose()
    factory.kw["bind"].dispose()
