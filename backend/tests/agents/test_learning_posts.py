import copy

from learnloop.agents.expert.materials import MATERIALS_VERSION
from learnloop.core.schemas import GroundingReview, PyramidMaterials, LessonScopeReview
from learnloop.persistence.database import Document
from learnloop.runtime.worker import work_once


def test_legacy_example_upgrades_to_one_scoped_lesson_and_full_question_bank(stack):
    from learnloop.core.schemas import PyramidMaterials
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        for resource in graph["resources"].values():
            resource["version"] = 2
            resource["lesson"]["workedExample"]["steps"] = [
                "Start with weight 4 and gradient 2.",
                "Subtract 0.2 to get 3.8.",
            ]
        doc.graph = graph
        original = copy.deepcopy(graph)
    before = client.get(f"/api/courses/{course_id}/learner-state").json()
    called, generate = [], services.generate

    def tracked(role, instruction, context, output):
        if output in (PyramidMaterials, GroundingReview):
            called.append(output)
        if output not in (GroundingReview, LessonScopeReview):
            assert context["curriculum"]["layer"] == "basic"
            assert "tests" not in context and "correctChoiceId" not in str(context)
        return generate(role, instruction, context, output)

    services.generate = tracked
    client.post(f"/api/documents/{uploaded['documentId']}/materials", json={}).raise_for_status()
    assert work_once(factory, services)
    assert called == [PyramidMaterials, GroundingReview]
    with factory() as db:
        updated = db.get(Document, uploaded["documentId"]).graph
        for id, resource in updated["resources"].items():
            previous = original["resources"][id]
            assert len(resource["tests"]) == 6
            assert not resource.get("lessonsByDifficulty")
            assert {k: v for k, v in resource["lesson"].items() if k != "workedExample"} == {
                k: v for k, v in previous["lesson"].items() if k != "workedExample"
            }
            assert resource["lesson"]["workedExample"]["steps"][1]["equations"]
        assert updated["concepts"] == original["concepts"]
    assert client.get(f"/api/courses/{course_id}/learner-state").json() == before


def test_legacy_rewrite_uses_curriculum_scope_and_preserves_progress(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        original = copy.deepcopy(doc.graph)
        graph = copy.deepcopy(original)
        for resource in graph["resources"].values():
            resource["version"] = 1
            resource["lesson"]["explanation"] = "A long original paragraph. " * 40
        doc.graph = graph
    before = client.get(f"/api/courses/{course_id}/learner-state").json()
    questions_before = services.questions
    called = []
    generate = services.generate

    def tracked(role, instruction, context, output):
        if output in (PyramidMaterials, GroundingReview):
            called.append(output)
        if output not in (GroundingReview, LessonScopeReview):
            assert context["curriculum"]["layer"] == "basic"
            assert "tests" not in context and "correctChoiceId" not in str(context)
        return generate(role, instruction, context, output)

    services.generate = tracked
    receipt = client.post(f"/api/documents/{uploaded['documentId']}/materials").json()
    assert (
        client.post(f"/api/documents/{uploaded['documentId']}/materials").json()["runId"]
        == receipt["runId"]
    )
    assert work_once(factory, services)
    assert called == [PyramidMaterials, GroundingReview] and services.questions == questions_before + 6
    assert client.get(f"/api/courses/{course_id}/learner-state").json() == before
    with factory() as db:
        updated = db.get(Document, uploaded["documentId"]).graph
        assert updated["concepts"] == original["concepts"]
        assert updated["organization"] == original["organization"]
        for id, resource in updated["resources"].items():
            assert len(resource["tests"]) == 6
            assert not resource.get("lessonsByDifficulty")
            assert resource["version"] == MATERIALS_VERSION
            assert resource["lesson"]["explanation"].count("\n- ") >= 3
            assert "hook" not in resource["lesson"] and "points" not in resource["lesson"]
    assert client.post(f"/api/documents/{uploaded['documentId']}/materials").json() == {
        "status": "ready"
    }
    assert client.get(f"/api/courses/{course_id}").json()["documents"][0]["postLessonCount"] == 1
