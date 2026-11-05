"""Temporary real-service API + worker for browser acceptance checks.

Start with python -m scripts.development.journey_sandbox. Create tmp/journey-stop to stop.
Only the generated SQLite sandbox file and its vectors are removed on exit.
"""

import json
import threading
from contextlib import ExitStack

import uvicorn

from learnloop.api import create_app
from learnloop.core.config import get_settings
from learnloop.runtime.worker import work_once
from scripts.development.local_sandbox import local_stack
from scripts.paths import ARTIFACT_ROOT


def main():
    settings = get_settings()
    root = ARTIFACT_ROOT
    root.mkdir(exist_ok=True)
    stop_path = root / "journey-stop"
    stop_path.unlink(missing_ok=True)
    resources = ExitStack()
    settings, factory, services = resources.enter_context(local_stack(settings))
    database = factory.kw["bind"].url.database
    (root / "journey-sandbox.json").write_text(json.dumps({"database": database, "port": 8011}))
    stop = threading.Event()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, factory, services),
            host="127.0.0.1",
            port=8011,
            log_level="warning",
        )
    )

    def worker():
        while not stop.is_set():
            if not work_once(factory, services):
                stop.wait(0.5)

    def shutdown_watch():
        while not stop.wait(0.5):
            if stop_path.exists():
                server.should_exit = True
                return

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    threading.Thread(target=shutdown_watch, daemon=True).start()
    print(
        "Isolated journey API on 127.0.0.1:8011; real embedding, retrieval and model services enabled.",
        flush=True,
    )
    try:
        server.run()
    finally:
        stop.set()
        # Let an active generation checkpoint finish before touching its schema.
        worker_thread.join()
        resources.close()
        stop_path.unlink(missing_ok=True)
        (root / "journey-sandbox.json").unlink(missing_ok=True)
        print("Isolated journey SQLite file and local vectors cleaned up.", flush=True)


if __name__ == "__main__":
    main()
