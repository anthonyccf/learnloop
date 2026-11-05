from learnloop.core.schemas import ConceptMatches, LessonScopeReview
from learnloop.persistence.database import Document
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare
from tests.conftest import COURSE_TEXT


def test_repeated_goals_across_uploads_keep_one_primary_home(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, first = prepare(stack)
    primary = client.get(f'/api/courses/{course_id}').json()['graph']['concepts'][0]['id']
    original = services.generate
    def generate(role, instruction, context, output):
        if output is ConceptMatches:
            return ConceptMatches(matches=[{'candidateId': c['id'], 'existingId': primary} for c in context['candidates'] if c['title'] == 'Gradient descent'])
        return original(role, instruction, context, output)
    monkeypatch.setattr(services, 'generate', generate)
    receipt = client.post(f'/api/courses/{course_id}/documents', files={'file': ('more.txt', (COURSE_TEXT + ' Additional supporting reading.').encode(), 'text/plain')}).json()
    assert work_once(factory, services)
    course = client.get(f'/api/courses/{course_id}').json()
    assert [c['id'] for c in course['graph']['concepts']] == [primary]
    with factory() as db:
        doc = db.get(Document, receipt['documentId'])
        assert list(doc.graph['conceptAliases'].values()) == [primary]
    lessons = client.get(f'/api/courses/{course_id}/materials').json()['materials']
    assert len(lessons) == 1 and lessons[0]['conceptId'] == primary


def test_scope_review_repairs_reteaching_before_acceptance(stack, monkeypatch):
    client, factory, services, _ = stack
    original = services.generate
    reviews = []
    def generate(role, instruction, context, output):
        if output is LessonScopeReview:
            reviews.append(context)
            return LessonScopeReview(accepted=len(reviews) > 1, feedback='Reference prerequisite definitions instead of teaching them again.')
        return original(role, instruction, context, output)
    monkeypatch.setattr(services, 'generate', generate)
    course_id, _ = prepare(stack)
    assert len(reviews) == 2
    assert len(client.get(f'/api/courses/{course_id}/materials').json()['materials']) == 1


def test_parallel_preparation_keeps_every_completed_pack(stack, monkeypatch):
    import copy
    from threading import Barrier
    from learnloop.core.schemas import LessonScopeReview
    client, factory, services, _ = stack
    course_id, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = copy.deepcopy(doc.graph)
        for index in range(6):
            graph["concepts"].append({**graph["concepts"][0], "id": f"{doc.id}:goal-{index}", "title": f"Distinct mechanism {index}"})
        doc.graph = graph
    barrier, original = Barrier(6), services.generate
    def generate(role, instruction, context, output):
        result = original(role, instruction, context, output)
        if output is LessonScopeReview:
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(services, "generate", generate)
    client.post(f"/api/documents/{upload['documentId']}/materials").raise_for_status()
    assert work_once(factory, services)
    lessons = client.get(f"/api/courses/{course_id}/materials").json()["materials"]
    assert len(lessons) == 7
    assert len({m["conceptId"] for m in lessons}) == 7


def test_scope_and_source_feedback_survive_the_same_repair(stack, monkeypatch):
    from learnloop.core.schemas import PyramidMaterials, GroundingReview
    client, factory, services, _ = stack
    original, drafts = services.generate, []
    def generate(role, instruction, context, output):
        if output is PyramidMaterials:
            drafts.append(context)
        result = original(role, instruction, context, output)
        if output is LessonScopeReview and len(drafts) == 1:
            result.accepted = False
            result.feedback = "Avoid repeating a prerequisite definition in this lesson."
        if output is GroundingReview and "lesson" in context["item"] and len(drafts) == 2:
            result.status = "unsupported"
            result.summary = "Remove an unsupported numerical claim from the example."
        return result
    monkeypatch.setattr(services, "generate", generate)
    prepare(stack)
    assert len(drafts) == 3
    feedback = str(drafts[2]["sourceReviewFeedback"])
    assert "prerequisite definition" in feedback
    assert "unsupported numerical claim" in feedback
