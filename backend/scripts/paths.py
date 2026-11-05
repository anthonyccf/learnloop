"""Stable paths shared by operational commands, independent of nesting or cwd."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
ARTIFACT_ROOT = PROJECT_ROOT / "tmp"
