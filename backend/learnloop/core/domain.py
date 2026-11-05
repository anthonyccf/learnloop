import copy
import io
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

from learnloop.core.errors import ServiceError
from learnloop.core.schemas import Graph

DIFFICULTIES = ("basic", "intermediate", "advanced")
WEAKNESS_FAILURE_THRESHOLD = 2


def target_difficulty(concept):
    layer = (concept.get("curriculum") or {}).get("layer")
    if layer in DIFFICULTIES:
        return layer
    return concept.get("targetDifficulty", "intermediate")


def concept_state(concept, evidence):
    return effective_state(evidence.get(concept["id"], {}).get(target_difficulty(concept)))


def select_difficulty(concept, evidence):
    target = target_difficulty(concept)
    levels = evidence.get(concept["id"], {})
    if effective_state(levels.get(target)) == "review_due":
        return target
    attempts = [
        (level, record)
        for level, record in levels.items()
        if level in DIFFICULTIES and record.get("lastAssessedAt") and record.get("lastOutcome")
    ]
    if not attempts:
        return target
    level, record = max(attempts, key=lambda pair: pair[1]["lastAssessedAt"])
    index = min(DIFFICULTIES.index(level), DIFFICULTIES.index(target))
    outcome = record["lastOutcome"]
    if not outcome["correct"] or outcome["hinted"] or outcome["uncertain"]:
        return DIFFICULTIES[max(0, index - 1)]
    if effective_state(record) == "demonstrated":
        index = min(index + 1, DIFFICULTIES.index(target))
    return DIFFICULTIES[index]


def extract(content: bytes, filename: str, max_pages: int, max_chunks: int):
    try:
        if filename.lower().endswith(".pdf"):
            if not content.startswith(b"%PDF-"):
                raise ValueError("Not a PDF")
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted or len(reader.pages) > max_pages:
                raise ValueError("Encrypted or too many pages")
            pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
        elif filename.lower().endswith(".txt"):
            pages = [(1, content.decode("utf-8-sig"))]
        else:
            raise ValueError("Unsupported format")
    except Exception as exc:
        raise ServiceError(
            "document_not_readable",
            "Upload a readable, unencrypted text PDF or UTF-8 .txt file within the page limit. OCR is not available yet.",
            False,
        ) from exc
    chunks = []
    for page, text in pages:
        text = text.replace("\x00", "").strip()
        for offset in range(0, len(text), 1400):
            passage = text[offset : offset + 1600].strip()
            if passage:
                chunks.append({"page": page, "text": passage})
                if len(chunks) > max_chunks:
                    raise ServiceError(
                        "too_many_chunks",
                        "This document exceeds the configured passage limit.",
                        False,
                    )
    if not chunks or sum(len(c["text"]) for c in chunks) < 40:
        raise ServiceError(
            "no_extractable_text",
            "The document has insufficient readable text. OCR is not available yet.",
            False,
        )
    return len(pages), chunks


def chunk_id(document_id: str, ordinal: int):
    return str(uuid5(NAMESPACE_URL, f"learnloop:{document_id}:{ordinal}"))


def validate_graph(graph: Graph | dict):
    data = graph.model_dump() if isinstance(graph, Graph) else graph
    concepts, prerequisites = data["concepts"], data["prerequisites"]
    ids = {concept["id"] for concept in concepts}
    if any(target_difficulty(c) not in DIFFICULTIES for c in concepts):
        raise ServiceError("invalid_difficulty", "Concept target difficulty is invalid.", False)
    if len(ids) != len(concepts):
        raise ServiceError("invalid_graph", "Concept identifiers must be unique.", False)
    children, indegree, seen = {key: [] for key in ids}, {key: 0 for key in ids}, set()
    for edge in prerequisites:
        parent, child = edge["prerequisite"], edge["dependent"]
        if (parent, child) in seen or parent not in ids or child not in ids:
            raise ServiceError(
                "invalid_graph",
                "Prerequisite relationships must be distinct and refer to known concepts.",
                False,
            )
        seen.add((parent, child))
        children[parent].append(child)
        indegree[child] += 1
    ready = [key for key in ids if not indegree[key]]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for child in children[key]:
            indegree[child] -= 1
            if not indegree[child]:
                ready.append(child)
    if visited != len(ids):
        raise ServiceError("cyclic_graph", "Prerequisite relationships contain a cycle.", False)


def effective_state(record: dict | None, at: datetime | None = None):
    record = record or {}
    state = record.get("state", "unassessed")
    due = record.get("reviewAt")
    if state == "demonstrated" and due and datetime.fromisoformat(due) <= (at or datetime.now(UTC)):
        return "review_due"
    return state


def assess_evidence(
    record: dict | None,
    activity_id: str,
    correct: bool,
    hinted: bool,
    uncertain: bool,
    at: datetime,
):
    result = copy.deepcopy(
        record
        or {
            "state": "unassessed",
            "independentActivityIds": [],
            "assisted": 0,
            "attempts": 0,
        }
    )
    before = effective_state(result, at)
    # Keep lifetime evidence separate from the active demonstration/recovery window.
    history = list(result.get("independentHistoryActivityIds", []))
    for id in result["independentActivityIds"]:
        if id not in history:
            history.append(id)
    result["independentHistoryActivityIds"] = history
    result["hasDemonstrated"] = result.get("hasDemonstrated", False) or before in (
        "demonstrated",
        "review_due",
    )
    failures = list(result.get("consecutiveFailureActivityIds", []))
    weakness = copy.deepcopy(result.get("confirmedWeakness"))
    active_weakness = bool(weakness and weakness["status"] == "active")
    result["attempts"] += 1
    result["lastAssessedAt"] = at.isoformat()
    result["lastOutcome"] = {"correct": correct, "hinted": hinted, "uncertain": uncertain}
    if hinted:
        result["assisted"] += 1
    qualifying = result["independentActivityIds"]
    if uncertain:
        # Ambiguity is not confirmed weakness, and cannot extend a failure streak.
        result["consecutiveFailureActivityIds"] = []
        result["independentActivityIds"] = []
        result["state"] = "review_due" if before in ("demonstrated", "review_due") else "developing"
        result.pop("reviewAt", None)
        outcome = "uncertain_evidence"
    elif not correct:
        if hinted:
            failures = []
        elif activity_id not in failures:
            failures.append(activity_id)
        result["consecutiveFailureActivityIds"] = failures
        result["independentActivityIds"] = []
        confirmed = result["hasDemonstrated"] and len(failures) >= WEAKNESS_FAILURE_THRESHOLD
        result["state"] = (
            "developing"
            if confirmed or active_weakness
            else "review_due"
            if before in ("demonstrated", "review_due")
            else "developing"
        )
        result.pop("reviewAt", None)
        outcome = (
            "confirmed_weakness"
            if confirmed or active_weakness
            else "contradiction"
            if before in ("demonstrated", "review_due")
            else "assisted_response"
            if hinted
            else "incorrect"
        )
        if confirmed and not active_weakness:
            weakness = {
                "status": "active",
                "activityIds": failures[:WEAKNESS_FAILURE_THRESHOLD],
                "confirmedAt": at.isoformat(),
            }
            result["confirmedWeakness"] = weakness
            result["weaknessHistory"] = [
                *result.get("weaknessHistory", []),
                copy.deepcopy(weakness),
            ]
    elif not hinted:
        result["consecutiveFailureActivityIds"] = []
        if before == "review_due" and result.get("reviewAt"):
            qualifying = []
            result.pop("reviewAt", None)
        if activity_id not in qualifying:
            qualifying.append(activity_id)
        if activity_id not in history:
            history.append(activity_id)
        result["independentActivityIds"] = qualifying
        result["state"] = "demonstrated" if len(qualifying) >= 2 else "developing"
        if result["state"] == "demonstrated":
            result["hasDemonstrated"] = True
            result["reviewAt"] = (at + timedelta(days=7)).isoformat()
            if active_weakness:
                resolved = {
                    **weakness,
                    "status": "resolved",
                    "resolvedAt": at.isoformat(),
                    "resolvedBy": activity_id,
                }
                result["confirmedWeakness"] = resolved
                result["weaknessHistory"] = [
                    resolved
                    if item.get("confirmedAt") == weakness["confirmedAt"]
                    and item.get("activityIds") == weakness["activityIds"]
                    and item.get("status") == "active"
                    else item
                    for item in result.get("weaknessHistory", [])
                ]
        outcome = (
            "demonstration"
            if result["state"] == "demonstrated"
            else "recovery_progress"
            if active_weakness
            else "independent_success"
        )
    else:
        result["consecutiveFailureActivityIds"] = []
        result["state"] = before if before != "unassessed" else "developing"
        outcome = "assisted_response"
    result["lastTransition"] = {
        "outcome": outcome,
        "before": before,
        "after": result["state"],
        "activityId": activity_id,
        "at": at.isoformat(),
    }
    return before, result


def select_concept(graph: dict, evidence: dict, target_id: str | None = None):
    eligible = []
    by_id = {c["id"]: c for c in graph.get("concepts", [])}
    for concept in graph.get("concepts", []):
        if target_id and concept["id"] != target_id:
            continue
        parents = [
            edge["prerequisite"]
            for edge in graph.get("prerequisites", [])
            if edge["dependent"] == concept["id"]
        ]
        if all(
            parent in by_id and concept_state(by_id[parent], evidence) == "demonstrated"
            for parent in parents
        ):
            state = concept_state(concept, evidence)
            if target_id or state != "demonstrated":
                eligible.append((state != "review_due", concept))
    return min(eligible, key=lambda item: item[0])[1] if eligible else None
