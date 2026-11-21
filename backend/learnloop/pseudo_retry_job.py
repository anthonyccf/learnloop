"""Background entry point for one bounded episode retry."""

import sys
from pathlib import Path

from learnloop.core.config import get_settings
from learnloop.evaluation.artifacts import checkpoint, digest, freeze
from learnloop.pseudo_retry import run_retry


def main():
    path, learner_id, condition, attempt = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    allow_runtime_change = "--allow-runtime-change" in sys.argv[5:]
    root = path / "episodes" / digest([learner_id, condition])[:16]
    destination = root / "retries" / attempt
    try:
        checkpoint(destination / "retry-status.json", {"status": "running"})
        result = run_retry(
            path,
            learner_id,
            condition,
            destination,
            get_settings(),
            allow_runtime_change=allow_runtime_change,
        )
        checkpoint(
            destination / "retry-status.json",
            {"status": result["status"], "errorType": result.get("errorType")},
        )
    except Exception as error:
        if not (destination / "result.json").exists():
            freeze(
                destination / "result.json", {"status": "failed", "errorType": type(error).__name__}
            )
        checkpoint(
            destination / "retry-status.json",
            {"status": "failed", "errorType": type(error).__name__},
        )
    finally:
        (root / "retry.lock").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
