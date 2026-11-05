"""Project known source anchors into public references without exposing private keys."""

from learnloop.core.grounding import validate_sources


def refs(sources, chunks, concept_id=None):
    validate_sources([source.model_dump() for source in sources], chunks)
    result = []
    for source in sources:
        c = chunks.get(source.chunkId)
        ref = {
            "documentId": c["document_id"],
            "page": c["page"],
            "label": c.get("label", "Course material"),
        }
        if concept_id:
            ref["conceptId"] = concept_id
        if ref not in result:
            result.append(ref)
    return result
