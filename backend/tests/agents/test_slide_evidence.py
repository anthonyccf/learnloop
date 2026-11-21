import io

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from learnloop.agents.expert.slide_evidence import candidate_pages
from learnloop.core.schemas import (
    AdditionalQuestions,
    GroundingReview,
    LessonScopeReview,
    PyramidMaterials,
    QuestionKeyCheck,
    SlideTranscription,
)
from learnloop.persistence.database import Chunk, Document, Run, RunMaterial, SlideEvidence
from learnloop.runtime.worker import work_once
from tests.conftest import COURSE_TEXT


def test_page_selection_prefers_a_sparse_neighbor():
    chunks = [
        {"id": str(p), "page": p, "ordinal": p, "text": "x" * (60 if p == 3 else 350)}
        for p in range(1, 9)
    ]
    sources = [{"chunkId": "2"}, {"chunkId": "4"}]
    assert candidate_pages({"sources": sources}, {"sources": sources}, chunks) == [2, 3, 4]


@pytest.mark.parametrize("case", ["visual", "unreadable", "quiz"])
def test_pdf_review_repair_and_publication(stack, monkeypatch, case):
    client, factory, services, _ = stack
    course = client.post("/api/courses", json={"title": "Slide review"}).json()["id"]
    writer = PdfWriter()
    writer.add_blank_page(width=160, height=90)
    pdf = io.BytesIO()
    writer.write(pdf)
    doc_id = client.post(
        f"/api/courses/{course}/documents",
        data={"defer_processing": "true"},
        files={"file": ("slides.pdf", pdf.getvalue(), "application/pdf")},
    ).json()["documentId"]
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        doc.pages, doc.status = 1, "indexed"
        db.add(
            Chunk(
                id="source-A",
                document_id=doc_id,
                course_id=course,
                ordinal=0,
                page=1,
                text=COURSE_TEXT,
            )
        )

    marker = "The visible equation is w_new = w - eta * g."
    generate = services.generate
    images, lessons, quiz_repairs = [], [], []
    grounding_inputs, scope_inputs, key_inputs = [], [], []

    def simulate(role, instruction, context, output, **kwargs):
        if output is SlideTranscription:
            images.append(kwargs["image_png"])
            return SlideTranscription(
                visibleText=marker if case == "visual" else "",
                unreadable="" if case == "visual" else "Equation illegible.",
            )
        if output is PyramidMaterials:
            lessons.append(context)
        if output is AdditionalQuestions:
            quiz_repairs.append(context["questionNumbers"])
        result = generate(role, instruction, context, output)
        if output is GroundingReview and "lesson" in context["item"]:
            grounding_inputs.append(context["passages"])
            if case == "quiz" and not quiz_repairs:
                result.status, result.repairKind, result.questionNumbers = (
                    "unsupported",
                    "questions_only",
                    [2],
                )
            elif case != "quiz" and marker not in str(context["passages"]):
                result.status, result.repairKind = "uncertain", "visual_evidence"
        if output is LessonScopeReview:
            scope_inputs.append(context["passages"])
        if output is QuestionKeyCheck:
            key_inputs.append(context)
        return result

    monkeypatch.setattr(services, "supports_slide_images", True, raising=False)
    monkeypatch.setattr(services, "generate", simulate)
    path = f"/api/courses/{course}/hierarchy-runs"

    def run():
        response = client.post(path, json={"documentIds": [doc_id]})
        assert response.status_code == 202
        run_id = response.json()["runId"]
        assert work_once(factory, services)
        return run_id

    run_id = run()
    with factory() as db:
        saved = db.get(Run, run_id)
        graph = db.get(RunMaterial, (run_id, doc_id)).graph
        assert saved.snapshot["status"] == (
            "needs_review" if case == "unreadable" else "completed"
        ), saved.snapshot["summary"]
        assert bool(db.scalar(select(SlideEvidence))) == (case != "quiz")
    if case == "quiz":
        assert not images and len(lessons) == 1 and quiz_repairs == [[2]]
    else:
        assert len(images) == 1 and images[0].startswith(b"\x89PNG")
        if case == "unreadable":
            assert graph["sourceIssues"] and not graph.get("resources")
            return
        assert marker in str(lessons[-1]["passages"])
        assert marker in str(grounding_inputs[-1]) and scope_inputs[-1] == grounding_inputs[-1]
        assert marker in str(key_inputs[-1])
        pack = next(iter(graph["resources"].values()))
        assert pack["slideEvidence"] == {"source-A": marker}
    published = client.post(f"{path}/{run_id}/publish")
    assert published.status_code == 200, published.text
    assert len(client.get(f"/api/courses/{course}/materials").json()["materials"]) == 1
    if case == "visual":
        run()
        assert len(images) == 1


def test_template_retry_forwards_slide_images_and_keeps_transcription_clean(monkeypatch):
    from learnloop.core.schemas import GroundingReview, PyramidMaterials
    from learnloop.runtime.workflows import PromptConfiguredServices

    calls = []

    class FakeBase:
        settings = None
        supports_slide_images = True

        def generate(self, role, instruction, context, output, **kwargs):
            calls.append((output.__name__, instruction, context, kwargs))
            return "ok"

    template = {
        "id": "builtin-org-rules-expert",
        "agent": "expert",
        "name": "Expert Rules",
        "prompts": {"analysis": "", "lesson": "", "questions": ""},
        "organizationVariant": "rules",
        "model": "configured",
        "temperature": None,
    }
    wrapped = PromptConfiguredServices(
        FakeBase(), template, retry_feedback={"code": "unsupported_content", "message": "old failure"}
    )
    assert wrapped.supports_slide_images is True

    wrapped.generate("Expert", "read slide", {"page": 1}, SlideTranscription, image_png=b"\x89PNGdata")
    wrapped.generate("Expert", "check grounding", {"item": {}}, GroundingReview)
    wrapped.generate("Expert", "write lesson", {"concept": {}}, PyramidMaterials)

    assert calls[0][0] == "SlideTranscription"
    assert calls[0][3]["image_png"] == b"\x89PNGdata"
    assert "previousRunFailure" not in calls[0][2]
    assert "previousRunFailure" not in calls[1][2]
    assert calls[2][2]["previousRunFailure"]["code"] == "unsupported_content"


def test_pdf_fallback_slide_recovery_and_flagged_draft_reload(stack, monkeypatch):
    from learnloop.agents.expert import slide_evidence

    client, factory, services, _ = stack
    course = client.post("/api/courses", json={"title": "Template slide retry"}).json()["id"]
    writer = PdfWriter()
    writer.add_blank_page(width=160, height=90)
    pdf = io.BytesIO()
    writer.write(pdf)
    doc_id = client.post(
        f"/api/courses/{course}/documents",
        data={"defer_processing": "true"},
        files={"file": ("slides.pdf", pdf.getvalue(), "application/pdf")},
    ).json()["documentId"]
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        doc.pages, doc.status = 1, "indexed"
        db.add(
            Chunk(
                id="source-A",
                document_id=doc_id,
                course_id=course,
                ordinal=0,
                page=1,
                text=COURSE_TEXT,
            )
        )

    marker = "Visible diagram label: alpha = 0.01"
    monkeypatch.setattr(slide_evidence, "render_slide", lambda content, page: b"\x89PNGfake")
    generate = services.generate
    images, lesson_passages = [], []

    def simulate(role, instruction, context, output, **kwargs):
        if output is SlideTranscription:
            images.append(kwargs["image_png"])
            return SlideTranscription(visibleText=marker, unreadable="")
        if output is PyramidMaterials:
            lesson_passages.append(str(context["passages"]))
        result = generate(role, instruction, context, output)
        if output is GroundingReview and "lesson" in context["item"]:
            if marker not in str(context["passages"]):
                result.status, result.repairKind = "unsupported", "other"
        return result

    monkeypatch.setattr(services, "supports_slide_images", True, raising=False)
    monkeypatch.setattr(services, "generate", simulate)
    response = client.post(
        f"/api/courses/{course}/hierarchy-runs",
        json={
            "documentIds": [doc_id],
            "promptTemplate": {
                "id": "builtin-org-procedural-expert",
                "agent": "expert",
                "name": "Expert Procedural",
                "prompts": {"analysis": "", "lesson": "", "questions": ""},
                "enabledTools": [],
                "model": "configured",
                "temperature": None,
                "basePrompts": "v2",
                "organizationVariant": "procedural",
            },
        },
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]
    assert work_once(factory, services)
    with factory() as db:
        saved = db.get(Run, run_id)
        assert saved.snapshot["status"] == "completed", saved.snapshot["summary"]
    assert len(images) == 1 and images[0] == b"\x89PNGfake"
    assert marker in lesson_passages[-1]


def test_flagged_lesson_retry_reloads_saved_slide_evidence(stack, monkeypatch):
    from learnloop.agents.expert import slide_evidence

    client, factory, services, _ = stack
    course = client.post("/api/courses", json={"title": "Flagged slide reload"}).json()["id"]
    writer = PdfWriter()
    writer.add_blank_page(width=160, height=90)
    pdf = io.BytesIO()
    writer.write(pdf)
    doc_id = client.post(
        f"/api/courses/{course}/documents",
        data={"defer_processing": "true"},
        files={"file": ("slides.pdf", pdf.getvalue(), "application/pdf")},
    ).json()["documentId"]
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        doc.pages, doc.status = 1, "indexed"
        db.add(
            Chunk(
                id="source-A",
                document_id=doc_id,
                course_id=course,
                ordinal=0,
                page=1,
                text=COURSE_TEXT,
            )
        )

    marker = "Saved slide transcript: beta = 0.5"
    monkeypatch.setattr(slide_evidence, "render_slide", lambda content, page: b"\x89PNGfake")
    generate = services.generate
    first_pass_fail = True
    seen_on_retry = []

    def simulate(role, instruction, context, output, **kwargs):
        if output is SlideTranscription:
            return SlideTranscription(visibleText=marker, unreadable="")
        if output is PyramidMaterials and not first_pass_fail:
            seen_on_retry.append(str(context["passages"]))
        result = generate(role, instruction, context, output)
        if output is GroundingReview and "lesson" in context["item"] and first_pass_fail:
            result.status, result.repairKind = "unsupported", "visual_evidence"
        return result

    monkeypatch.setattr(services, "supports_slide_images", True, raising=False)
    monkeypatch.setattr(services, "generate", simulate)
    response = client.post(f"/api/documents/{doc_id}/analyze", json={})
    assert response.status_code == 202
    assert work_once(factory, services)
    with factory() as db:
        doc = db.get(Document, doc_id)
        cid = next(iter(doc.graph["sourceIssues"]))
        assert doc.graph["reviewDrafts"][cid]["draft"]["slideEvidence"] == {"source-A": marker}

    first_pass_fail = False
    regen = client.post(
        f"/api/documents/{doc_id}/flagged-lessons/{cid}/regenerate",
        json={"notes": "Retry with saved slide evidence."},
    )
    assert regen.status_code == 202
    assert work_once(factory, services)
    assert seen_on_retry and marker in seen_on_retry[0]


