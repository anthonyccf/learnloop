"""Evidence lookup for bounded Expert repairs; never authorizes publication."""

import copy
import json
import re


def repair_citations(value, chunks):
    """Correct a near-miss ID only when its quote identifies one matching passage.

    All candidates must belong to the supplied document. Semantic review must
    still approve the repaired content; an ID correction is not a receipt.
    """
    result = copy.deepcopy(value)
    corrections = []

    def normalize(text):
        return " ".join(text.casefold().split())

    def visit(item):
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            source_id = item.get("chunkId")
            quote = normalize(item.get("quote", ""))
            if isinstance(source_id, str) and source_id not in chunks and len(quote) >= 20:
                matches = [
                    id
                    for id, chunk in chunks.items()
                    if len(id) == len(source_id)
                    and sum(a != b for a, b in zip(id, source_id)) <= 2
                    and quote in normalize(chunk["text"])
                ]
                if len(matches) == 1:
                    item["chunkId"] = matches[0]
                    corrections.append((source_id, matches[0]))
            for child in item.values():
                visit(child)

    visit(result)
    return result, corrections


def repair_context(concept, chunks, initial, draft, feedback, attempt):
    """Expand document evidence with cited passages and rejection-specific terms."""
    cited = set()

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if isinstance(value.get("chunkId"), str):
                cited.add(value["chunkId"])
            for child in value.values():
                visit(child)

    visit(draft)
    terms = set(
        re.findall(
            r"[a-z0-9]{4,}",
            json.dumps(
                {
                    "concept": concept,
                    "feedback": feedback,
                    "lesson": (draft or {}).get("lesson", {}),
                }
            ).lower(),
        )
    )
    ranked = sorted(
        chunks,
        key=lambda c: (
            c["id"] in cited,
            len(terms & set(re.findall(r"[a-z0-9]{4,}", c["text"].lower()))),
            -c["ordinal"],
        ),
        reverse=True,
    )
    # Preserve the initial evidence boundary while adding up to 12 passages.
    selected = {c["id"]: c for c in initial}
    for chunk in ranked:
        if len(selected) >= 6 + 6 * attempt:
            break
        selected.setdefault(chunk["id"], chunk)
    return list(selected.values())
