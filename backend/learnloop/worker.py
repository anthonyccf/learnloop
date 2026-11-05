"""Stable CLI: python -m learnloop.worker. Implementation: learnloop.runtime.worker."""

from learnloop.runtime.worker import main, work_once

__all__ = ["main", "work_once"]

if __name__ == "__main__":
    main()
