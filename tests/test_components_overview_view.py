"""OverviewView tests, D2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.

Minimal page, minimal tests to match -- see the view's own module
docstring for exactly what this first slice does and deliberately
doesn't include yet (callouts, live status, report rate).
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from g7ctlc.palette import DARK_PALETTE, LIGHT_PALETTE


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class OverviewViewTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.views.overview_view import OverviewView

        self.view = OverviewView(DARK_PALETTE)

    def test_shows_the_controller_diagram(self):
        from g7ctlc.controller_diagram import ControllerDiagram

        self.assertIsInstance(self.view.diagram, ControllerDiagram)

    def test_starts_with_no_highlight(self):
        # Nothing on this page drives a highlight yet -- a stray non-None
        # default would be a silent leftover from whatever ControllerDiagram
        # happened to default to, not a deliberate choice for this page.
        self.assertIsNone(self.view.diagram._highlighted)

    def test_set_palette_reaches_the_diagram(self):
        self.view.set_palette(LIGHT_PALETTE)
        self.assertIs(self.view.diagram._palette, LIGHT_PALETTE)

    def test_has_a_changed_signal_for_main_windows_uniform_wiring(self):
        # MainWindow._build_pages() connects every page's `changed` to
        # _on_dirty in one loop with no per-page special case (except
        # buttons_view/profile_settings_page, which wire it elsewhere) --
        # this page must have the signal even though nothing emits it yet.
        self.assertTrue(hasattr(self.view, "changed"))


if __name__ == "__main__":
    unittest.main()
