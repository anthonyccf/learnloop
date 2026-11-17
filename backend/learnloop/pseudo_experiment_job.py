"""Detached job entry point; retain safe errors and bounded evaluation artifacts."""

import json
import sys
import traceback
from pathlib import Path

from learnloop.core.config import get_settings
from learnloop.evaluation.artifacts import checkpoint, thaw
from learnloop.pseudo_experiment import run


def main():
    path = Path(sys.argv[1])
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    try:
        data = thaw(path / "input.json")["payload"]
        checkpoint(path / "status.json", {"status": "running", "phase": "Preparing course"})
        report = run(
            data["setup"],
            data["release"],
            path,
            job["config"],
            get_settings(),
            reused=data.get("reused"),
        )
        checkpoint(
            path / "status.json",
            {
                "status": "completed"
                if report["failedOrStopped"] == 0
                else "completed_with_failures",
                "phase": "Finished",
            },
        )
    except Exception as error:
        # Traceback contains only local exception details; do not send it to the browser.
        (path / "process.log").write_text(traceback.format_exc(), encoding="utf-8")
        checkpoint(
            path / "status.json",
            {
                "status": "failed",
                "phase": "Stopped",
                "errorType": type(error).__name__,
                "message": "Run stopped during preparation or execution. Inspect the local process log.",
            },
        )


if __name__ == "__main__":
    main()
