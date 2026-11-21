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
