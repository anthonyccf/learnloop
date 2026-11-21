"""Cooperative cancellation for Expert runs."""

from learnloop.persistence.database import Run


class RunStopped(Exception):
    """The user requested that the current Expert run stop."""


def check_stopped(factory, run_id):
    with factory() as db:
        run = db.get(Run, run_id)
        if run and run.input.get("_stop_requested"):
            raise RunStopped()
