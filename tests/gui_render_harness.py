"""Offscreen render harness, A1 of the redesign (`IMPLEMENTATION-PLAN.md`:
"the offscreen render harness (skeleton first, fixtures added as pages
arrive)"). This is the skeleton: a reusable way to construct a widget
headless and grab a PNG of it, with a throwaway `HOME` so geometry/
settings never touch the real config. Not collected as a test module
itself (no `test_` prefix) -- `tests/test_gui_render_harness.py` is the
smoke test proving this file works; per-page fixtures land in A2-A6 as
each page is re-skinned, using this same `render_widget_to_png`.

Needs PyQt6 -- importing this module without it raises ImportError, same
as every other g7ctlc GUI test module; callers guard with the project's
usual `QApplication is None` skip pattern (see `tests/test_gui_main_window.py`).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QWidget


@contextmanager
def throwaway_home() -> Iterator[str]:
    """`QSettings`/geometry restore reads `HOME`; swap it for a fresh
    tempdir for the duration of the block so a render never reads or
    writes the real user's config."""
    with tempfile.TemporaryDirectory(prefix="g7ctlc-render-home-") as tmp:
        original = os.environ.get("HOME")
        os.environ["HOME"] = tmp
        try:
            yield tmp
        finally:
            if original is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original


def render_widget_to_png(
    make_widget: Callable[[], QWidget],
    out_path: Path,
    *,
    app: QApplication,
) -> None:
    """Construct `make_widget()`, show it, pump the event loop, and grab
    a PNG to `out_path`. `app` is the caller's `QApplication.instance()
    or QApplication([])` -- not created here, so callers keep the same
    one-`QApplication`-per-process discipline the rest of the suite uses.
    """
    with throwaway_home():
        widget = make_widget()
        try:
            widget.show()
            app.processEvents()
            pixmap = widget.grab()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not pixmap.save(str(out_path), "PNG"):
                raise RuntimeError(f"QPixmap.save failed for {out_path}")
        finally:
            widget.close()
            widget.deleteLater()
            app.processEvents()
