"""Python-only workspace using the sibling backend's real agents."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if not (BACKEND / "learnloop").is_dir():
    raise RuntimeError("Keep agent_lab/ beside backend/ in the LearnLoop checkout.")
sys.path.insert(0, str(BACKEND))

from .workspace import Workspace

__all__ = ["Workspace"]
