"""Read-only research preflight; never creates reviews or dispatches providers."""

from pathlib import Path

from learnloop.evaluation.artifacts import thaw
from learnloop.evaluation.prepare import load_bundle, research_gate, research_review_requirements
from learnloop.evaluation.schema import EXPERTS


def readiness(bundle, *, model=None, temperature=0.2):
    bundle = Path(bundle)
    result = {
        "ready": False,
        "blockers": [],
        "reviews": {},
        "modelSettings": [],
        "modelChecked": model is not None,
    }
    missing = [
        name
        for name in (
            "unit.json",
            "exams.json",
            *[f"expert-{v}.json" for v in EXPERTS],
            "screening.json",
        )
        if not (bundle / name).is_file()
    ]
    if missing:
        result["blockers"] = [f"Missing artifact: {name}" for name in missing]
        return result
    try:
        unit, exams, artifacts = load_bundle(bundle)
        screening = thaw(bundle / "screening.json")["payload"]
        required = research_review_requirements(unit, exams, artifacts, screening)
        reviews = (
            thaw(bundle / "reviews.json")["payload"] if (bundle / "reviews.json").exists() else {}
        )
        for key, fingerprint in required.items():
            review = reviews.get(key)
            if review is None:
                status = "pending"
            elif review.get("hash") != fingerprint:
                status = "stale"
            elif review.get("decision") == "rejected":
                status = "rejected"
            elif (
                review.get("decision") != "approved"
                or not review.get("reviewer", "").strip()
                or not review.get("notes", "").strip()
            ):
                status = "incomplete"
            else:
                status = "approved"
            result["reviews"][key] = status
            if status != "approved":
                result["blockers"].append(f"Human review {status}: {key}")
        for variant, artifact in artifacts.items():
            result["modelSettings"].append(
                {
                    "variant": variant,
                    "model": artifact["model"],
                    "temperature": artifact["temperature"],
                }
            )
            if model is not None and (
                artifact["model"] != model or artifact["temperature"] != temperature
            ):
                result["blockers"].append(f"Model/temperature mismatch: {variant}")
        if not result["blockers"]:
            research_gate(unit, exams, artifacts, screening, reviews)
            result["ready"] = True
    except (ValueError, KeyError, TypeError, OSError) as error:
        result["blockers"].append(f"Invalid research bundle: {error}")
    return result
