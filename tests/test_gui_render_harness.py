"""Smoke test for `tests/gui_render_harness.py`'s skeleton (A1 of the
redesign). Proves the harness itself works -- constructs a small widget
styled with the real A1 QSS generator, renders it headless, and checks a
real PNG came out. Per-page fixtures (Overview, Sticks, ...) land in A2-A6
as each page is re-skinned; this file stays the harness's own smoke test,
not a growing page-fixture file.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent,
same as the other g7ctlc test modules.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QLabel
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from g7ctlc.palette import DARK_PALETTE
from g7ctlc.qss import generate_stylesheet

# Deferred past the skip guard, not imported at module top: like
# `g7ctlc.fonts`/`g7ctlc.icon_loader`, `tests.gui_render_harness` imports
# PyQt6 at its own module level. Importing it here unconditionally was
# this file's first version's actual bug -- it crashed test *collection*
# itself on a PyQt6-less environment instead of skipping cleanly, caught
# by actually running this suite under one rather than assuming the
# skip guard alone was enough.


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RenderHarnessSmokeTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_styled_widget_renders_to_a_real_png(self):
        from tests.gui_render_harness import render_widget_to_png

        def make_widget():
            label = QLabel("g7ctlc")
            label.setStyleSheet(generate_stylesheet(DARK_PALETTE))
            label.resize(120, 40)
            return label

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "label.png"
            render_widget_to_png(make_widget, out_path, app=self.app)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_throwaway_home_is_restored_after_the_block(self):
        from tests.gui_render_harness import throwaway_home

        original = os.environ.get("HOME")
        with throwaway_home() as tmp:
            self.assertEqual(os.environ["HOME"], tmp)
            self.assertNotEqual(tmp, original)
        self.assertEqual(os.environ.get("HOME"), original)


if __name__ == "__main__":
    unittest.main()
