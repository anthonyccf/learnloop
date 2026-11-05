import copy

import pytest
from sqlalchemy import delete, select

from learnloop.persistence.database import CourseRelease, Document, LearnerState
from learnloop.persistence.releases import get_release
from scripts.development import validate_legacy_releases as repair
from tests.api.test_integration import prepare


@pytest.mark.parametrize("accepted", [True, False])
def test_legacy_publication_requires_fresh_review_and_preserves_lessons_and_evidence(
    stack, tmp_path, monkeypatch, accepted
):
    _, factory, services, _ = stack
    course_id, upload = prepare(stack)
    with factory.begin() as db:
        db.execute(delete(CourseRelease).where(CourseRelease.course_id == course_id))
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        graph["curriculum"]["signature"] = "legacy-signature"
        for pack in graph["resources"].values():
            pack.pop("scopeFingerprint")
        doc.graph = graph
        original_content = [(p["lesson"], p["tests"]) for p in graph["resources"].values()]
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id))
        evidence_before = copy.deepcopy(state.evidence)
        version_before = state.version
    monkeypatch.setattr(repair, "ARTIFACT_ROOT", tmp_path)
    original_generate = services.generate

    def generate(role, instruction, context, output):
        if output is repair.BatchReview:
            return output(
                reviews=[
                    {
                        "conceptId": item["conceptId"],
                        "accepted": accepted,
                        "feedback": "Controlled review.",
                    }
                    for item in context["lessons"]
                ]
            )
        return original_generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", generate)
    if accepted:
        repair.repair_course(factory, services, course_id)
    else:
        with pytest.raises(ValueError, match="content repair"):
            repair.repair_course(factory, services, course_id)
    with factory() as db:
        release = get_release(db, course_id)
        assert bool(release) == accepted
        doc = db.get(Document, upload["documentId"])
        assert [
            (p["lesson"], p["tests"]) for p in doc.graph["resources"].values()
        ] == original_content
        state = db.scalar(select(LearnerState).where(LearnerState.course_id == course_id))
        assert state.evidence == evidence_before and state.version == version_before
