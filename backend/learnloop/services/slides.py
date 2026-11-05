"""Render original PDF pages, preserving diagrams, formulas, and layout."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from learnloop.core.errors import ServiceError

_render_slots = BoundedSemaphore(2)


def render_slide(content: bytes, page: int) -> bytes:
    renderer = os.environ.get("PDFTOPPM_PATH") or shutil.which("pdftoppm")
    if not renderer:
        raise ServiceError(
            "slide_renderer_unavailable",
            "Slide preview is unavailable. Extracted text is still available.",
        )
    if not _render_slots.acquire(timeout=5):
        raise ServiceError("slide_renderer_busy", "Slide previews are busy. Please try again.")
    try:
        with TemporaryDirectory(prefix="learnloop-slide-") as temporary:
            root = Path(temporary)
            source, target = root / "source.pdf", root / "slide"
            source.write_bytes(content)
            try:
                subprocess.run(
                    [
                        renderer,
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-singlefile",
                        "-scale-to",
                        "1800",
                        "-png",
                        str(source),
                        str(target),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return target.with_suffix(".png").read_bytes()
            except (OSError, subprocess.SubprocessError) as exc:
                raise ServiceError(
                    "slide_render_failed",
                    "Could not render this slide. Try again or read the extracted text.",
                ) from exc
    finally:
        _render_slots.release()
