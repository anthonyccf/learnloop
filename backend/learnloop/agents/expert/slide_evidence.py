"""Recover page-linked evidence for a lesson whose text review found a visual gap."""

from threading import Lock

import httpx
from sqlalchemy import select

from learnloop.core.errors import ServiceError
from learnloop.core.grounding import source_ids
from learnloop.core.schemas import SlideTranscription
from learnloop.persistence.database import Document, SlideEvidence
from learnloop.runtime.events import step
from learnloop.services.slides import render_slide


def with_slide_evidence(chunks, transcripts):
    if not transcripts:
        return chunks
    enriched = dict(chunks)
    for chunk_id, text in transcripts.items():
        if chunk_id in chunks:
            chunk = chunks[chunk_id]
            enriched[chunk_id] = {
                **chunk,
                "text": chunk["text"] + "\n\nVisible on this slide:\n" + text,
            }
    return enriched


def candidate_pages(concept, draft, chunks):
    """Inspect a cited anchor, a sparse adjacent slide, then another cited page."""
    cited = source_ids(draft)
    anchors = {s["chunkId"] for s in concept["sources"]}
    ordered = sorted(chunks, key=lambda c: (c["id"] not in anchors, c["ordinal"]))
    pages = list(dict.fromkeys(c["page"] for c in ordered if c["id"] in cited))
    if not pages:
        return []
    lengths = {}
    for chunk in chunks:
        lengths[chunk["page"]] = lengths.get(chunk["page"], 0) + len(chunk["text"])
    nearby = sorted(
        (
            p
            for p, n in lengths.items()
            if n < 160 and p not in pages and any(abs(p - anchor) == 1 for anchor in pages)
        ),
        key=lambda p: (lengths[p], p),
    )
    return list(dict.fromkeys([pages[0], *nearby[:1], *pages[1:]]))[:3]


class SlideEvidenceRecovery:
    def __init__(self, factory, services, run_id, document_id, sha256):
        self.factory = factory
        self.services = services
        self.run_id = run_id
        self.document_id = document_id
        self.sha256 = sha256
        # Lesson threads can report a gap on the same page simultaneously.
        self.lock = Lock()

    def read_page(self, page, concept, finding):
        key = (self.document_id, self.sha256, page)
        with self.lock:
            with self.factory() as db:
                cached = db.get(SlideEvidence, key)
                if cached:
                    return cached.transcription, "reused"
                content = db.scalar(
                    select(Document.content).where(
                        Document.id == self.document_id, Document.sha256 == self.sha256
                    )
                )
            if content is None:
                raise ServiceError(
                    "source_changed", "The selected PDF version is unavailable.", False
                )
            png = render_slide(content, page)
            result = self.services.generate(
                "Expert",
                "Read this slide as source material. Transcribe visible equations, variable definitions, "
                "diagram labels, connections and worked values for the full page. Preserve subscripts, "
                "sums, axes and units. Pay particular attention to the reported evidence gap. Only "
                "record what is visible. Do not infer a missing formula, derive an answer, or accept "
                "the reviewer's suggested claim as fact. Put ambiguous or illegible details in "
                "unreadable, separately from visibleText. Use empty strings where appropriate.",
                {"page": page, "lesson": concept["title"], "reviewFinding": finding},
                SlideTranscription,
                image_png=png,
            ).model_dump()
            with self.factory.begin() as db:
                # Recheck under the document lock if another worker transcribed it.
                db.scalar(
                    select(Document.id).where(Document.id == self.document_id).with_for_update()
                )
                cached = db.get(SlideEvidence, key)
                if cached:
                    return cached.transcription, "reused"
                db.add(
                    SlideEvidence(
                        document_id=self.document_id,
                        sha256=self.sha256,
                        page=page,
                        transcription=result,
                    )
                )
            return result, "read"

    def recover(self, concept, draft, finding, chunks):
        transcripts = {}
        for page in candidate_pages(concept, draft, chunks):
            try:
                result, action = self.read_page(page, concept, finding)
                visible = result["visibleText"].strip()
                if visible:
                    # Use an existing passage ID on this exact page for provenance.
                    anchor = min(
                        (c for c in chunks if c["page"] == page), key=lambda c: c["ordinal"]
                    )
                    transcripts[anchor["id"]] = visible
                detail = f"Page {page}: {action} the slide for {concept['title']}. "
                detail += (
                    "Page transcription available." if visible else "No legible evidence recovered."
                )
                if result["unreadable"]:
                    detail += " Some slide details were unreadable."
            except (ServiceError, httpx.HTTPError) as exc:
                reason = (
                    exc.message if isinstance(exc, ServiceError) else "Vision service unavailable."
                )
                detail = f"Page {page}: could not recover slide evidence. {reason}"
                with self.factory.begin() as db:
                    step(
                        db,
                        self.run_id,
                        "expert",
                        "Slide evidence unavailable",
                        detail,
                        "retrieve_evidence",
                    )
                break
            with self.factory.begin() as db:
                step(
                    db, self.run_id, "expert", "Review original slide", detail, "retrieve_evidence"
                )
        return transcripts
