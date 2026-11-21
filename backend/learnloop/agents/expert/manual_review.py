"""Human review of lessons that failed automatic expert review after all repairs."""

import copy
import re

from learnloop.agents.expert.materials import (
    MATERIALS_VERSION,
    material_content,
    question_counts,
)
from learnloop.agents.expert.slide_evidence import with_slide_evidence
from learnloop.core.errors import ServiceError
from learnloop.core.grounding import grounding_fingerprint, validate_sources
from learnloop.core.schemas import Lesson, Question
from learnloop.persistence.releases import scope_fingerprint

FEEDBACK_KEYS = ("summary", "scopeFeedback", "message")


def feedback_notes(value):
    """Readable reviewer notes only; answer letters and raw checks stay private."""
    notes = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FEEDBACK_KEYS and isinstance(child, str):
                notes.append(child)
            else:
                notes.extend(feedback_notes(child))
    elif isinstance(value, list):
        for child in value:
            notes.extend(feedback_notes(child))
    return list(dict.fromkeys(notes))


def approval_blocker(draft, chunks, objective):
    if not draft:
        return "No draft was saved for this lesson. Regenerate it with reviewer notes."
    if not objective:
        return "This concept has no curriculum objective. Regenerate the course materials."
    try:
        Lesson.model_validate(draft["lesson"])
        questions = [Question.model_validate(q) for q in draft["tests"]]
        validate_sources(material_content(draft), chunks)
    except (KeyError, TypeError, ValueError, ServiceError):
        return "The draft has an invalid structure or cites passages outside this document."
    if any(not q.rubric or not q.referenceAnswer for q in questions):
        return "The draft questions are missing private reference answers or rubrics."
    if question_counts(draft)["basic"] < 2:
        return "The draft needs at least two Basic starter questions."
    prompts = [re.sub(r"\W+", "", q.prompt.casefold()) for q in questions]
    if len(prompts) != len(set(prompts)):
        return "The draft contains duplicate questions."
    return None


def public_draft(draft):
    """The lesson and question wording; keys, hints and rubrics never leave the server."""
    if not draft:
        return None
    return {
        "lesson": copy.deepcopy(draft.get("lesson")),
        "questions": [
            {
                "difficulty": q.get("difficulty", "intermediate"),
                "prompt": q.get("prompt"),
                "choices": q.get("choices", []),
            }
            for q in draft.get("tests", [])
        ],
    }


def flagged_lessons(graph, chunks):
    concepts = {c["id"]: c for c in graph.get("concepts", [])}
    objectives = graph.get("curriculum", {}).get("objectives", {})
    result = []
    for concept_id, issue in graph.get("sourceIssues", {}).items():
        if concept_id not in concepts:
            continue
        saved = graph.get("reviewDrafts", {}).get(concept_id, {})
        draft = saved.get("draft")
        blocker = approval_blocker(draft, chunks, objectives.get(concept_id))
        result.append(
            {
                "conceptId": concept_id,
                "title": issue.get("title") or concepts[concept_id]["title"],
                "code": issue.get("code"),
                "message": issue.get("message"),
                "reviewNotes": feedback_notes(saved.get("feedback")) or [issue.get("message")],
                "draft": public_draft(draft),
                "canApprove": blocker is None,
                "approvalBlocker": blocker,
            }
        )
    return result


def approve_draft(graph, concept_id, chunks, reviewer):
    """Return an updated graph with the reviewed draft saved as the concept's lesson."""
    if concept_id not in graph.get("sourceIssues", {}):
        raise ServiceError("not_flagged", "This lesson is not waiting for manual review.", False)
    draft = graph.get("reviewDrafts", {}).get(concept_id, {}).get("draft")
    objective = graph.get("curriculum", {}).get("objectives", {}).get(concept_id)
    blocker = approval_blocker(draft, chunks, objective)
    if blocker:
        raise ServiceError("draft_not_approvable", blocker, False)
    content = material_content(draft)
    transcripts = draft.get("slideEvidence", {})
    resource = {
        "version": MATERIALS_VERSION,
        **content,
        **({"slideEvidence": transcripts} if transcripts else {}),
        "grounding": {
            "status": "supported",
            "fingerprint": grounding_fingerprint(content, with_slide_evidence(chunks, transcripts)),
            "reviewedBy": "human",
        },
        "scopeReview": {"accepted": True, "feedback": "Approved by a human reviewer."},
        "scopeFingerprint": scope_fingerprint(draft["lesson"], objective),
        "humanApproval": {
            "reviewer": reviewer,
            "overriddenIssue": copy.deepcopy(graph["sourceIssues"][concept_id]),
        },
    }
    if draft.get("promptVersion"):
        resource["promptVersion"] = draft["promptVersion"]
    updated = copy.deepcopy(graph)
    updated.setdefault("resources", {})[concept_id] = resource
    updated["sourceIssues"].pop(concept_id)
    updated.get("reviewDrafts", {}).pop(concept_id, None)
    return updated
