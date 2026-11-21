"""Stop a detached pseudo-student test without touching other Python processes."""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from learnloop.evaluation.artifacts import checkpoint


class StopRequested(RuntimeError):
    """The owner asked this test to stop."""


def mark_process(path):
    checkpoint(Path(path) / "process.json", {"pid": os.getpid()})


def stop_requested(path):
    return (Path(path) / "stop.request").is_file()


def raise_if_stopped(path):
    if stop_requested(path):
        raise StopRequested("You stopped this test.")


def request_stop(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    (Path(path) / "stop.request").write_text("stop", encoding="utf-8")


def command_pids(token):
    """Process ids whose command line contains this run id."""
    if len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
        return []
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{token}') }} | "
            "ForEach-Object { $_.ProcessId }"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        lines = completed.stdout.splitlines()
    else:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="], capture_output=True, text=True, check=False
        )
        lines = []
        for line in completed.stdout.splitlines():
            pid, _, command = line.strip().partition(" ")
            if pid.isdigit() and token in command:
                lines.append(pid)
    return [int(line) for line in lines if line.strip().isdigit()]


def _recorded_pid(path):
    record = Path(path) / "process.json"
    if not record.is_file():
        return None
    try:
        pid = json.loads(record.read_text(encoding="utf-8")).get("pid")
    except (OSError, json.JSONDecodeError):
        return None
    return pid if isinstance(pid, int) and pid > 0 else None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate(path):
    """End the test process. The API process is never a candidate."""
    path = Path(path)
    pids = set(command_pids(path.name))
    recorded = _recorded_pid(path)
    if recorded:
        pids.add(recorded)
    pids.discard(os.getpid())
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
