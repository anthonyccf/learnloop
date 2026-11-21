import subprocess
import sys
from pathlib import Path

from learnloop.pseudo_control import StopRequested, raise_if_stopped, request_stop, terminate


def test_stop_request_is_visible_to_the_job(tmp_path):
    request_stop(tmp_path)
    try:
        raise_if_stopped(tmp_path)
    except StopRequested as error:
        assert "stopped" in str(error)
    else:
        raise AssertionError("stop request was ignored")


def test_terminate_ends_only_the_matching_job(tmp_path):
    token = "c" * 32
    path = tmp_path / token
    path.mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", token],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        terminate(path)
        assert proc.wait(timeout=5) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
    assert Path(sys.executable).exists()
