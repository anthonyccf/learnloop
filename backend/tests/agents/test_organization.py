import copy

import pytest

from learnloop.agents.expert.organization import (
    catalog_signature,
    current_organization,
    normalize_related,
    validate_organization,
)
from learnloop.core.domain import select_concept
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import CourseRelationships
from learnloop.persistence.database import Document, LearnerState, Run
from learnloop.runtime.worker import work_once


def catalog():
    return [
        {"id": id, "title": id, "summary": "A learning goal", "sources": []}
        for id in ("a", "b", "c")
    ]


def organization():
    return (
        [{"id": "one", "conceptIds": ["a", "b"]}, {"id": "two", "conceptIds": ["c"]}],
        {
            "prerequisites": [{"prerequisite": "a", "dependent": "c", "sourceChunkIds": ["s0"]}],
            "related": [
                {"first": "b", "second": "c", "rationale": "A comparison without a requirement."}
            ],
        },
    )


def test_full_partition_cross_section_dag_and_related_links_do_not_gate_practice():
    topics, relationships = organization()
    validate_organization(catalog(), topics, relationships, {"s0"}, relationships)
    graph = {"concepts": catalog(), **relationships}
    assert (
        select_concept({**graph, "concepts": [catalog()[1], catalog()[2], catalog()[0]]}, {})["id"]
        == "b"
    )


@pytest.mark.parametrize(
    "defect",
    ["missing", "duplicate", "unknown", "cycle", "bad-source", "invented", "duplicate-related"],
)
def test_coordinator_rejects_incomplete_or_invalid_organization(defect):
    topics, relationships = organization()
    proposals = copy.deepcopy(relationships)
    if defect == "missing":
        topics[0]["conceptIds"].remove("b")
    if defect == "duplicate":
        topics[1]["conceptIds"].append("a")
    if defect == "unknown":
        topics[1]["conceptIds"] = ["outside"]
    if defect == "cycle":
        relationships["prerequisites"].append(
            {"prerequisite": "c", "dependent": "a", "sourceChunkIds": ["s0"]}
        )
    if defect == "bad-source":
        relationships["prerequisites"][0]["sourceChunkIds"] = ["outside"]
    if defect == "invented":
        relationships["prerequisites"][0]["dependent"] = "b"
    if defect == "duplicate-related":
        relationships["related"] *= 2
    with pytest.raises(ServiceError):
        validate_organization(catalog(), topics, relationships, {"s0"}, proposals)


def test_stale_course_organization_is_not_used():
    class Doc:
        graph = {"organization": {"version": 1, "signature": catalog_signature(catalog())}}

    assert current_organization([Doc()], catalog()) is not None
    changed = catalog()
    changed[0]["summary"] = "Changed goal"
    assert current_organization([Doc()], changed) is None


def test_normalization_removes_reversed_duplicates_and_prerequisite_overlap():
    topics, relationships = organization()
    original = copy.deepcopy(relationships)
    related = relationships["related"][0]
    relationships["related"] += [
        {**related, "first": "c", "second": "b"},
        {**related, "first": "c", "second": "a"},
    ]
    before = copy.deepcopy(relationships)
    cleaned, counts = normalize_related(catalog(), relationships)
    assert relationships == before
    assert cleaned == original
    assert counts == {"duplicateRelated": 1, "prerequisiteOverlap": 1}
    validate_organization(catalog(), topics, cleaned, {"s0"}, original)


@pytest.mark.parametrize("pair", [("a", "a"), ("a", "outside")])
def test_normalization_never_hides_self_links_or_unknown_concepts(pair):
    _, relationships = organization()
    relationships["related"] = [{"first": pair[0], "second": pair[1]}]
    with pytest.raises(ServiceError, match=f"{pair[0]} <-> {pair[1]}"):
        normalize_related(catalog(), relationships)


def test_relationship_retry_keeps_topics_proposals_and_failed_draft(stack):
    from learnloop.core.schemas import TopicOrganization
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        doc.graph = {k: v for k, v in doc.graph.items() if k != "organization"}
        for previous in db.query(Run).filter_by(course_id=course_id):
            previous.input = {k: v for k, v in previous.input.items() if k != "organizationDraft"}
    original = services.generate
    calls = {"topics": 0, "analyst": 0, "reviewer": 0}

    def generate(role, instruction, context, output):
        if output is TopicOrganization:
            calls["topics"] += 1
        if output is CourseRelationships:
            stage = "reviewer" if "proposals" in context else "analyst"
            calls[stage] += 1
            if stage == "reviewer" and calls[stage] == 1:
                return CourseRelationships(
                    related=[
                        {
                            "first": context["concepts"][0]["id"],
                            "second": "unknown",
                            "rationale": "An invalid link to trigger a targeted retry.",
                        }
                    ]
                )
            if stage == "reviewer":
                assert "unknown" in context["validationFeedback"]["message"]
        return original(role, instruction, context, output)

    services.generate = generate
    response = client.post(f"/api/courses/{course_id}/organize").json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{response['runId']}").json()
    assert run["status"] == "failed"
    with factory() as db:
        inputs = db.get(Run, run["id"]).input
        assert "unknown" in inputs["failedOrganizationDrafts"][0]["error"]
        assert (
            "topics" in inputs["organizationDraft"]
            and "relationships" in inputs["organizationDraft"]
        )
        assert "review" not in inputs["organizationDraft"]
    client.post(
        f"/api/agent-activity/runs/{run['id']}/commands",
        json={
            "kind": "retry",
            "operationId": "retry-relationship-review",
            "expectedVersion": run["recordVersion"],
        },
    ).raise_for_status()
    assert work_once(factory, services)
    assert calls == {"topics": 1, "analyst": 1, "reviewer": 2}
    assert client.get(f"/api/agent-activity/runs/{run['id']}").json()["status"] == "completed"


@pytest.mark.parametrize("partial", [False, True])
def test_draft_order_and_partial_generation_do_not_replace_released_lessons(stack, partial):
    from tests.api.test_integration import prepare

    client, factory, _services, _settings = stack
    course_id, uploaded = prepare(stack)
    before = client.get(f"/api/courses/{course_id}/materials").json()
    with factory.begin() as db:
        doc = db.get(Document, uploaded["documentId"])
        graph = copy.deepcopy(doc.graph)
        template = graph["concepts"][0]
        ids = {name: f"{doc.id}:{name}" for name in ("application", "foundation", "method")}
        # Extraction order differs deliberately from the organized sequence.
        graph["concepts"] = [{**template, "id": ids[name], "title": name} for name in ids]
        resource = next(iter(graph["resources"].values()))
        graph["resources"] = {
            id: copy.deepcopy(resource)
            for name, id in ids.items()
            if not (partial and name == "method")
        }
        graph["organization"]["signature"] = catalog_signature(graph["concepts"])
        graph["organization"]["topics"] = [
            {
                "id": "ordered",
                "title": "Foundations to applications",
                "summary": "Teaching sequence",
                "conceptIds": [ids[name] for name in ("foundation", "method", "application")],
            }
        ]
        graph["organization"]["prerequisites"] = []
        graph["organization"]["related"] = []
        doc.graph = graph
        original = copy.deepcopy(graph)
    materials = client.get(f"/api/courses/{course_id}/materials").json()
    assert materials == before
    assert "correctChoiceId" not in str(materials)
    with factory() as db:
        assert db.get(Document, uploaded["documentId"]).graph == original


def test_course_wide_upgrade_is_durable_keeps_evidence_and_reuses_completed_output(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, uploaded = prepare(stack)
    with factory.begin() as db:
        document = db.get(Document, uploaded["documentId"])
        original = copy.deepcopy(document.graph)
        document.graph = {k: v for k, v in original.items() if k != "organization"}
        state = db.query(LearnerState).filter_by(course_id=course_id).one()
        state.evidence = {original["concepts"][0]["id"]: {"intermediate": {"state": "developing"}}}
    before = client.get(f"/api/courses/{course_id}/learner-state").json()
    receipt = client.post(f"/api/courses/{course_id}/organize", json={}).json()
    assert (
        client.post(f"/api/courses/{course_id}/organize", json={}).json()["runId"]
        == receipt["runId"]
    )
    assert work_once(factory, services)
    result = client.get(f"/api/courses/{course_id}").json()["graph"]
    assert result["organization"]["groupedConceptCount"] == len(result["concepts"])
    assert client.get(f"/api/courses/{course_id}/learner-state").json() == before
    assert client.post(f"/api/courses/{course_id}/organize", json={}).json() == {"status": "ready"}
    with factory() as db:
        after = db.get(Document, uploaded["documentId"]).graph
        for key in ("concepts", "resources", "prerequisites"):
            assert after[key] == original[key]


def test_new_document_organizes_all_documents_and_reviewer_can_downgrade_dependency(stack):
    from tests.api.test_integration import prepare

    client, factory, services, _ = stack
    course_id, first = prepare(stack)
    original_generate = services.generate
    calls = []

    def generate(role, instruction, context, output):
        if output is CourseRelationships:
            calls.append(context)
            assert len(context["concepts"]) == 2
            a, b = (c["id"] for c in context["concepts"])
            if "proposals" in context:
                # The independent reviewer identifies a comparison rather than a prerequisite.
                return CourseRelationships(
                    prerequisites=[],
                    related=[
                        {
                            "first": a,
                            "second": b,
                            "rationale": "Compare the two learning goals without requiring prior mastery.",
                        }
                    ],
                )
            source = context["concepts"][0]["sources"][0]["id"]
            return CourseRelationships(
                prerequisites=[
                    {
                        "prerequisite": a,
                        "dependent": b,
                        "rationale": "A candidate cross-document prerequisite to review.",
                        "sourceChunkIds": [source],
                    }
                ],
                related=[],
            )
        from learnloop.core.schemas import CurriculumPlan

        if output is CurriculumPlan:
            result = original_generate(role, instruction, context, output)
            for item in result.objectives:
                item.teaches += " (" + item.conceptId + ")"
            return result
        return original_generate(role, instruction, context, output)

    services.generate = generate
    second = client.post(
        f"/api/courses/{course_id}/documents",
        files={
            "file": (
                "second.txt",
                b"A second document explaining how a learning rate controls the size of a gradient descent update.",
            )
        },
    ).json()
    assert work_once(factory, services)
    finished = client.get(f"/api/agent-activity/runs/{second['runId']}").json()
    assert finished["status"] == "completed", finished.get("error")
    graph = client.get(f"/api/courses/{course_id}").json()["graph"]
    assert len(calls) == 2 and "proposals" not in calls[0] and "passages" in calls[1]
    assert graph["organization"]["documentCount"] == 2
    assert graph["organization"]["groupedConceptCount"] == 2
    assert graph["prerequisites"] == [] and len(graph["related"]) == 1
    assert {c["id"].split(":")[0] for c in graph["concepts"]} == {
        first["documentId"],
        second["documentId"],
    }
