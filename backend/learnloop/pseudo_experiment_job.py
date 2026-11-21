"""Detached job entry point; retain safe errors and bounded evaluation artifacts."""

import json
import sys
import traceback
from pathlib import Path

from fastapi import HTTPException

from learnloop.core.config import get_settings
from learnloop.evaluation.artifacts import checkpoint, thaw
from learnloop.pseudo_control import StopRequested, mark_process, raise_if_stopped


def main():
    path = Path(sys.argv[1])
    mark_process(path)
    try:
        raise_if_stopped(path)
        checkpoint(path / "status.json", {"status": "running", "phase": "Starting"})
        from learnloop.pseudo_experiment import run

        job = json.loads((path / "job.json").read_text(encoding="utf-8"))
        if (path / "generation.json").is_file():
            from learnloop.persistence.database import session_factory
            from learnloop.pseudo_generation import prepare_generated_input

            checkpoint(path / "status.json", {"status": "running", "phase": "Generating course materials"})
            pending = thaw(path / "generation.json")["payload"]
            data = prepare_generated_input(path, pending, session_factory())
            raise_if_stopped(path)
        else:
            data = thaw(path / "input.json")["payload"]
        checkpoint(path / "status.json", {"status": "running", "phase": "Loading course materials"})
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
    except StopRequested:
        checkpoint(
            path / "status.json",
            {
                "status": "stopped",
                "phase": "Stopped",
                "message": "You stopped this test. Finished learners are kept.",
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
                "message": error.detail if isinstance(error, HTTPException) else "Run stopped during preparation or execution. Inspect the local process log.",
            },
        )


if __name__ == "__main__":
    main()
