"""Run an evaluation outside the web process and retain a small status projection."""

import json
import os
import subprocess
import sys
from pathlib import Path

from learnloop.evaluation.artifacts import checkpoint


def main():
    path = Path(sys.argv[1])
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    settings = job["settings"]
    bundle = Path(__file__).resolve().parents[1] / "evaluation" / settings["bundle"]
    args = [
        sys.executable,
        "-m",
        "learnloop.evaluation",
        "run",
        "--bundle",
        str(bundle),
        "--output",
        str(path / "output"),
        "--selected",
        settings["expert"],
        settings["tutor"],
        settings["assessor"],
        "--repeats",
        str(settings["repeats"]),
        "--activities",
        str(settings["activities"]),
        "--max-calls",
        str(settings["maxCalls"]),
        "--max-tokens",
        str(settings["maxTokens"]),
    ]
    if settings["baselines"]:
        args.append("--baselines")
    checkpoint(path / "status.json", {"status": "running"})
    try:
        with (path / "process.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                args,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                env={**os.environ, "OPENROUTER_MODEL": job["model"]},
            )
        status = (
            {"status": "completed"}
            if result.returncode == 0
            else {
                "status": "failed",
                "message": "Evaluation process failed; inspect the local process log.",
            }
        )
    except OSError:
        status = {"status": "failed", "message": "Evaluation process could not be started."}
    checkpoint(path / "status.json", status)


if __name__ == "__main__":
    main()
