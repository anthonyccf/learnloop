"""Deterministic citation checks and content-bound grounding receipts."""

import hashlib
import json

from pydantic import BaseModel

from learnloop.core.errors import ServiceError

GROUNDING_VERSION = 1


def remap_sources(value, mapping):
    """Translate citation IDs only; concept IDs and factual text are untouched."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, list):
        return [remap_sources(child, mapping) for child in value]
    if isinstance(value, dict):
        return {
            key: mapping.get(child, child)
            if key == "chunkId"
            else [mapping.get(id, id) for id in child]
            if key == "sourceChunkIds"
            else remap_sources(child, mapping)
            for key, child in value.items()
        }
    return value


def source_ids(value):
    """Check every citation, including nested lessons, tests and graph edges."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    ids = set()
    if isinstance(value, dict):
        if "chunkId" in value:
            ids.add(value["chunkId"])
        for key, child in value.items():
            if key in ("sources", "sourceChunkIds") and not child:
                raise ServiceError(
                    "no_grounding", "Source evidence is missing. Review this item.", False
                )
            if key == "sourceChunkIds":
                ids.update(child)
            else:
                ids.update(source_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.update(source_ids(child))
    return ids


def validate_sources(value, chunks):
    ids = source_ids(value)
    unknown = ids - chunks.keys()
    if not ids or unknown or any(not chunks[id]["text"].strip() for id in ids):
        raise ServiceError(
            "invalid_source",
            "Source references are missing or outside the supplied course passages. Review this item.",
            False,
            details={"unknownSourceIds": sorted(unknown), "providedSourceIds": sorted(chunks)},
        )
    return ids


def grounding_fingerprint(value, chunks):
    if isinstance(value, BaseModel):
        value = value.model_dump()
    ids = validate_sources(value, chunks)
    evidence = [{"id": id, "text": chunks[id]["text"]} for id in sorted(ids)]
    encoded = json.dumps(
        {"version": GROUNDING_VERSION, "item": value, "evidence": evidence}, sort_keys=True
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def grounding_valid(value, chunks, receipt):
    try:
        return bool(
            receipt
            and receipt.get("status") == "supported"
            and receipt.get("fingerprint") == grounding_fingerprint(value, chunks)
        )
    except ServiceError:
        return False
