"""Read every passage in bounded sections, then merge repeated learning goals."""

import copy
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from learnloop.agents.expert.prompts import MERGE_PROMPT, SECTION_PROMPT
from learnloop.agents.grounding import generate_grounded
from learnloop.core.domain import validate_graph
from learnloop.core.grounding import (
    grounding_fingerprint,
    grounding_valid,
    remap_sources,
    validate_sources,
)
from learnloop.core.schemas import ConceptMatches, SectionGraph
from learnloop.persistence.database import Course, Document, Run
from learnloop.runtime.events import accept, pending, run_status, step

ANALYSIS_VERSION = 2
SECTION_CHARS = 10000
SECTION_PASSAGES = 8


def section_passages(chunks):
    """Contiguous, exhaustive partitions; no passage sampling or truncation."""
    sections, current, size = [], [], 0
    for chunk in chunks:
        if current and (
            size + len(chunk["text"]) > SECTION_CHARS or len(current) >= SECTION_PASSAGES
        ):
            sections.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(chunk["text"])
    if current:
        sections.append(current)
    return sections


def _title(value):
    return re.sub(r"[\W_]+", "", value.casefold())


def _unique_id(document_id, slug, existing):
    candidate, suffix = f"{document_id}:{slug}", 1
    while candidate in existing:
        suffix += 1
        ending = f"-{suffix}"
        candidate = f"{document_id}:{slug[: 63 - len(ending)]}{ending}"
    return candidate


def _merge_section(services, section, catalog, document_id, saved_mapping=None):
    mapping = dict(saved_mapping or {})
    known_ids = {c["id"] for c in catalog}
    titles = {_title(c["title"]): c["id"] for c in catalog}
    unmatched = []
    for candidate in section["concepts"]:
        if candidate["id"] in mapping:
            continue
        exact = titles.get(_title(candidate["title"]))
        if exact:
            mapping[candidate["id"]] = exact
        else:
            unmatched.append(candidate)
    if unmatched and catalog:
        result = services.generate(
            "Expert",
            MERGE_PROMPT,
            {
                "existing": [
                    {"id": c["id"], "title": c["title"], "summary": c["summary"]} for c in catalog
                ],
                "candidates": unmatched,
            },
            ConceptMatches,
        )
        candidates = {c["id"] for c in unmatched}
        for match in result.matches:
            if match.candidateId in candidates and match.existingId in known_ids:
                mapping.setdefault(match.candidateId, match.existingId)
    by_id = {c["id"]: c for c in catalog}
    for candidate in section["concepts"]:
        key = mapping.get(candidate["id"])
        if key not in by_id:
            key = _unique_id(document_id, candidate["id"], by_id)
            mapping[candidate["id"]] = key
            concept = {
                **copy.deepcopy(candidate),
                "id": key,
                "targetDifficulty": candidate.get("targetDifficulty", "intermediate"),
            }
            catalog.append(concept)
            by_id[key] = concept
        concept = by_id[key]
        sources = {s["chunkId"]: s for s in concept["sources"]}
        sources.update({s["chunkId"]: s for s in candidate["sources"]})
        concept["sourceChunkIds"] = sorted(set(concept.get("sourceChunkIds", [])) | set(sources))
        concept["sources"] = list(sources.values())[:4]
    return mapping


def analyze_document(factory, services, run_id, document_id, chunks):
    sections = section_passages(chunks)
    chunk_map = {c["id"]: c for c in chunks}
    aliases = {c["id"]: f"s{i}" for i, c in enumerate(chunks)}
    original_ids = {alias: id for id, alias in aliases.items()}
    signature = hashlib.sha256("|".join(c["id"] for c in chunks).encode()).hexdigest()
    with factory.begin() as db:
        doc = db.get(Document, document_id)
        graph = copy.deepcopy(doc.graph)
        review_feedback = (
            db.get(Run, run_id).input.get("sectionReviewFeedback", {}).get(document_id)
        )
        analysis = graph.get("analysis", {})
        if analysis.get("version") != ANALYSIS_VERSION or analysis.get("signature") != signature:
            analysis = {
                "version": ANALYSIS_VERSION,
                "signature": signature,
                "sections": {},
                "complete": False,
            }
            graph["analysis"] = analysis
            doc.graph = graph
        complete = analysis.get("complete", False)
        saved_sections = copy.deepcopy(analysis["sections"])
        receipts = copy.deepcopy(analysis.get("grounding", {}))
        if complete:
            validate_sources(
                {"concepts": graph["concepts"], "prerequisites": graph["prerequisites"]}, chunk_map
            )

    def inspect(index):
        passages = sections[index]
        result = saved_sections.get(str(index))
        if result is not None:
            result = {k: v for k, v in result.items() if k != "mapping"}
            result = remap_sources(result, aliases)
        else:
            result = None
        payload = {
            "section": index + 1,
            "totalSections": len(sections),
            "pages": sorted({c["page"] for c in passages}),
            "passages": [
                {"chunkId": aliases[c["id"]], "page": c["page"], "text": c["text"]}
                for c in passages
            ],
        }
        if review_feedback:
            payload["sourceReviewFeedback"] = review_feedback
            payload["revisionInstruction"] = (
                "An earlier attempt failed source review. Use this feedback when producing a fresh grounded section. If passages only list names, do not invent capabilities, features or comparisons for them. Omit unsupported details, retaining the supported learning goal."
            )
        # A section may legitimately contain no teaching claims (e.g. title/Q&A).
        if result is None:
            result = services.generate("Expert", SECTION_PROMPT, payload, SectionGraph).model_dump()
        validate_graph(result)
        receipt = None
        if result["concepts"]:
            result, receipt = generate_grounded(
                services,
                "Expert",
                SECTION_PROMPT,
                payload,
                SectionGraph,
                {aliases[c["id"]]: c for c in passages},
                candidate=result,
                receipt=receipts.get(str(index)),
            )
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            validate_graph(result)
        result = remap_sources(result, original_ids)
        if result["concepts"]:
            receipt = {
                "status": "supported",
                "fingerprint": grounding_fingerprint(result, {c["id"]: c for c in passages}),
            }
        return result, receipt

    failures = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(inspect, i): i
            for i in range(len(sections))
            if str(i) not in saved_sections
            or saved_sections[str(i)]["concepts"]
            and not grounding_valid(
                {k: v for k, v in saved_sections[str(i)].items() if k != "mapping"},
                {c["id"]: c for c in sections[i]},
                receipts.get(str(i)),
            )
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                result, receipt = future.result()
                with factory.begin() as db:
                    doc = db.get(Document, document_id)
                    graph = copy.deepcopy(doc.graph)
                    graph["analysis"]["sections"][str(index)] = result
                    graph["analysis"].setdefault("grounding", {})[str(index)] = receipt
                    doc.graph = graph
                    saved_sections[str(index)] = result
                    step(
                        db,
                        run_id,
                        "expert",
                        "Review all material sections",
                        f"Reviewed {len(saved_sections)}/{len(sections)} sections. Every passage is included; section {index + 1} contributed {len(result['concepts'])} candidate learning goals.",
                        "retrieve_evidence",
                    )
            except Exception as exc:
                failures.append(exc)
    if failures:
        raise failures[0]
    if complete:
        return
    with factory() as db:
        doc = db.get(Document, document_id)
        # Existing concepts and IDs anchor upgrades, retaining all saved evidence.
        catalog = (
            copy.deepcopy(doc.graph.get("concepts", []))
            if doc.status in ("prepared", "published")
            else []
        )
        edges = (
            copy.deepcopy(doc.graph.get("prerequisites", []))
            if doc.status in ("prepared", "published")
            else []
        )
    for index in range(len(sections)):
        section = saved_sections[str(index)]
        mapping = _merge_section(services, section, catalog, document_id, section.get("mapping"))
        edge_pairs = {(e["prerequisite"], e["dependent"]) for e in edges}
        for edge in section["prerequisites"]:
            prerequisite, dependent = mapping[edge["prerequisite"]], mapping[edge["dependent"]]
            if prerequisite != dependent and (prerequisite, dependent) not in edge_pairs:
                edges.append({**edge, "prerequisite": prerequisite, "dependent": dependent})
                edge_pairs.add((prerequisite, dependent))
        with factory.begin() as db:
            doc = db.get(Document, document_id)
            graph = copy.deepcopy(doc.graph)
            graph["analysis"]["sections"][str(index)]["mapping"] = mapping
            doc.graph = graph
            step(
                db,
                run_id,
                "expert",
                "Merge repeated learning goals",
                f"Merged section {index + 1}/{len(sections)}. Catalog now contains {len(catalog)} distinct concepts; concept count follows the content.",
                "publish_resources",
            )
    assembled = {"concepts": catalog, "prerequisites": edges}
    validate_graph(assembled)
    validate_sources(assembled, chunk_map)
    with factory.begin() as db:
        doc = db.get(Document, document_id)
        db.scalar(select(Course).where(Course.id == doc.course_id).with_for_update())
        graph = copy.deepcopy(doc.graph)
        graph.update(assembled)
        graph["coverage"] = {
            "method": "all-sections",
            "analysisVersion": ANALYSIS_VERSION,
            "selectedPassages": len(chunks),
            "processedPassages": len(chunks),
            "totalPassages": len(chunks),
            "reviewedSections": len(sections),
            "totalSections": len(sections),
            "conceptCount": len(catalog),
        }
        graph["analysis"]["complete"] = True
        pending(db, run_id, "course_resources")
        doc.graph, doc.status = graph, "prepared"
        accept(db, run_id, "course_resources")
        step(
            db,
            run_id,
            "expert",
            "Full material review complete",
            f"Reviewed all {len(chunks)} passages across {len(sections)} sections and staged {len(catalog)} concepts. Preparing lessons and tests for newly discovered goals.",
            "publish_resources",
        )
        run_status(
            db,
            run_id,
            "running",
            "All sections reviewed. Preparing lessons and tests for the expanded concept catalog.",
        )
