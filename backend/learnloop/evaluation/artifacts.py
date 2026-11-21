import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def storage_name(key):
    """File name for an artifact key. Concept ids may contain characters Windows rejects."""
    text = str(key)
    if text and not any(char in text for char in '<>:"/\\|?*') and not text.endswith((" ", ".")):
        return text
    return digest(text)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    """Immutable completed artifacts; a failed write cannot replace prior results."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".pending")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(
            temporary, path
        )  # Atomic create-if-absent on NTFS/POSIX, never replace a prior result.
    finally:
        temporary.unlink(missing_ok=True)


def checkpoint(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.pending")
    try:
        temporary.write_text(canonical(value), encoding="utf-8")
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as error:
                # A Windows reader may briefly hold the destination open.
                if getattr(error, "winerror", None) not in (5, 32) or attempt == 5:
                    raise
                time.sleep(0.01 * 2**attempt)
    finally:
        temporary.unlink(missing_ok=True)


def freeze(path, payload):
    result = {"sha256": digest(payload), "payload": payload}
    write(path, result)
    return result


def thaw(path):
    artifact = read(path)
    if digest(artifact["payload"]) != artifact["sha256"]:
        raise ValueError(f"Artifact hash mismatch: {Path(path).name}")
    return artifact


def public_question(question):
    result = {key: question[key] for key in ("difficulty", "prompt", "choices")}
    if question.get("format") and question["format"] != "single_answer":
        result["format"] = question["format"]
    if question.get("blankIds"):
        result["blankIds"] = list(question["blankIds"])
    return result


def prompt_key(question):
    return "".join(c for c in question["prompt"].casefold() if c.isalnum())


def runtime_hash():
    base = Path(__file__).resolve().parents[1]
    files = (
        list((base / "evaluation").glob("*.py"))
        + [base / "core" / name for name in ("domain.py", "planning.py", "schemas.py")]
        + [
            base / "agents" / name
            for name in (
                "rubrics.py",
                "grounding.py",
                "question_review.py",
                "tutoring/agent.py",
                "tutoring/prompts.py",
                "assessing/agent.py",
                "assessing/prompts.py",
                "expert/questions.py",
                "expert/prompts.py",
                "tutoring/workbench.py",
            )
        ]
        + [
            base / "pseudo_experiment.py",
            base / "pseudo_workbench.py",
            base / "runtime" / "workflows.py",
            base / "api" / "routes" / "workbench_tutor.py",
        ]
    )
    return digest(
        {
            str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)
        }
    )
