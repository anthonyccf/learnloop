"""Run-owned Expert hierarchy regressions using the actual worker and test provider."""

from sqlalchemy import select

from learnloop.persistence.database import CourseRelease, Run
from learnloop.runtime.worker import work_once
from tests.conftest import COURSE_TEXT


def test_run_snapshot_continuation_and_publication(stack, monkeypatch):
    client, factory, services, _ = stack
    course = client.post("/api/courses", json={"title": "Branching course"}).json()["id"]
    path = f"/api/courses/{course}/hierarchy-runs"

    def upload(name, text):
        return client.post(
            f"/api/courses/{course}/documents",
            data={"defer_processing": "true"},
            files={"file": (name, text.encode(), "text/plain")},
        ).json()["documentId"]

    def execute(ids, parent=None, **options):
        response = client.post(path, json={"documentIds": ids, "parentRunId": parent, **options})
        assert response.status_code == 202, response.text
        run_id = response.json()["runId"]
        assert work_once(factory, services)
        with factory() as db:
            run = db.get(Run, run_id)
            assert run.snapshot["status"] == "completed", run.snapshot["summary"]
        return run_id

    first = upload("first.txt", COURSE_TEXT)
    second = upload("second.txt", COURSE_TEXT + "This is a second handout.")
    original = execute([first])
    original_graph = client.get(f"{path}/{original}").json()
    assert original_graph["topics"]
    assert {c["document_id"] for c in services.chunks.values()} == {first}
    assert client.post(f"{path}/{original}/publish").status_code == 200
    child = execute([second], original)
    child_graph = client.get(f"{path}/{child}").json()
    assert [c["id"] for c in child_graph["concepts"]] == [
        c["id"] for c in original_graph["concepts"]
    ]
    assert len(child_graph["concepts"][0]["sources"]) == 2
    assert client.get(f"{path}/{original}").json() == original_graph
    assert set(client.get(path).json()[0]["filenames"]) == {"first.txt", "second.txt"}
    with factory() as db:
        assert db.scalar(select(CourseRelease)) is not None
    publication = client.post(f"{path}/{child}/publish")
    assert publication.status_code == 200, publication.text
    # Reanalyzing the duplicate may now produce a different objective. Its
    # previous citation must then disappear from the inherited concept.
    from learnloop.core.schemas import SectionGraph

    original_generate = services.generate

    def change_selected(role, instruction, context, output):
        result = original_generate(role, instruction, context, output)
        if output is SectionGraph:
            result.concepts[0].title = "Another objective"
        return result

    monkeypatch.setattr(services, "generate", change_selected)
    revised = execute([second], child, reanalyze=True)
    revised_graph = client.get(f"{path}/{revised}").json()
    assert len(revised_graph["concepts"]) == 2
    assert all(len(c["sources"]) == 1 for c in revised_graph["concepts"])
    assert client.get(f"{path}/{child}").json() == child_graph
    monkeypatch.setattr(
        services,
        "generate",
        lambda *args: (_ for _ in ()).throw(AssertionError("Unexpected provider call")),
    )
    reused = execute([second], child)
    assert client.get(f"{path}/{reused}").json() == child_graph


def test_distinct_materials_extend_parent_and_retry_without_rereading(stack, monkeypatch):
    from learnloop.agents.expert import run_hierarchy
    from learnloop.core.errors import ServiceError
    from learnloop.core.schemas import SectionGraph, TopicOrganization
    from tests.api.test_integration import prepare, release_retry

    client, factory, services, _ = stack
    course, legacy = prepare(stack)
    path = f"/api/courses/{course}/hierarchy-runs"
    original = client.get(f"{path}/{legacy['runId']}").json()

    def upload(name):
        return client.post(
            f"/api/courses/{course}/documents",
            data={"defer_processing": "true"},
            files={
                "file": (
                    name + ".txt",
                    (name + " concepts from a separate lecture.").encode(),
                    "text/plain",
                )
            },
        ).json()["documentId"]

    second, third = upload("Probability"), upload("Statistics")
    reads = []
    generate = services.generate

    def scoped_generate(role, instruction, context, output):
        result = generate(role, instruction, context, output)
        if output is SectionGraph:
            text = context["passages"][0]["text"]
            reads.append(text.split()[0])
            result.concepts[0].title = text.split()[0]
        if output is TopicOrganization and context["existingTopicMap"]:
            result.topics[0].id = context["existingTopicMap"][0]["id"]
        return result

    monkeypatch.setattr(services, "generate", scoped_generate)
    response = client.post(
        path, json={"documentIds": [second, third], "parentRunId": legacy["runId"]}
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["runId"]
    assert client.post(path, json={"documentIds": [third]}).status_code == 409
    prepare_lessons = run_hierarchy.prepare_materials

    def interrupted(*args, **kwargs):
        raise ServiceError("test_timeout", "Interrupted before lessons.", True)

    monkeypatch.setattr(run_hierarchy, "prepare_materials", interrupted)
    assert work_once(factory, services)
    graph = client.get(f"{path}/{run_id}").json()
    assert {c["title"] for c in graph["concepts"]} == {
        "Gradient descent",
        "Statistics",
        "Probability",
    }
    assert [topic["id"] for topic in graph["topics"]] == [
        topic["id"] for topic in original["topics"]
    ]
    assert sorted(reads) == ["Probability", "Statistics"]
    assert client.post(f"{path}/{run_id}/publish").status_code == 409
    monkeypatch.setattr(run_hierarchy, "prepare_materials", prepare_lessons)
    release_retry(factory, run_id)
    assert work_once(factory, services)
    assert sorted(reads) == ["Probability", "Statistics"]
    publication = client.post(f"{path}/{run_id}/publish")
    assert publication.status_code == 200, publication.text
    assert client.get(f"{path}/{legacy['runId']}").json() == original
    fresh = client.post(path, json={"documentIds": [third]}).json()["runId"]
    assert work_once(factory, services)
    assert [c["title"] for c in client.get(f"{path}/{fresh}").json()["concepts"]] == ["Statistics"]
    assert reads[-1] == "Statistics"
