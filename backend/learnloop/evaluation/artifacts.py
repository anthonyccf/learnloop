import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


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
    temporary = path.with_suffix(".pending")
    temporary.write_text(canonical(value), encoding="utf-8")
    os.replace(temporary, path)


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
    return {key: question[key] for key in ("difficulty", "prompt", "choices")}


def prompt_key(question):
    return "".join(c for c in question["prompt"].casefold() if c.isalnum())


def runtime_hash():
    base = Path(__file__).resolve().parents[1]
    files = (
        list((base / "evaluation").glob("*.py"))
        + [base / "core" / name for name in ("domain.py", "planning.py", "schemas.py")]
        + [base / "agents" / "rubrics.py"]
    )
    return digest(
        {
            str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)
        }
    )
