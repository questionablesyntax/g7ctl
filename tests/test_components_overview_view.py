"""OverviewView tests, D2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.

Minimal page -- see the view's own module docstring for exactly what
this slice does (a read-only diagram with callouts, via `load_state()`)
and what's still deliberately missing (live status, report rate, a
Front/Back toggle, the scope line).
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

    def test_the_diagram_is_not_interactive(self):
        # This page isn't a remapping surface (Buttons is the only one,
        # per D2's rework) -- builds no hotspots at all, not just inert-
        # looking ones (the real gap found once Buttons' own diagram
        # started doing real work; see HANDOFF.md).
        self.assertEqual(self.view.diagram._hotspots, {})
        self.assertIsNone(self.view.diagram.hotspot_for("a"))

    def test_load_state_feeds_remapped_default_bindings_as_callouts(self):
        from g7ctlc.widgets import keycode_display_text

        self.view.load_state({"buttons": {"default": {"b": "r"}, "shift": {"a": "e"}}})
        self.assertEqual(self.view.diagram._bindings, {"b": keycode_display_text("r")})

    def test_load_state_ignores_shift_bindings(self):
        # The drawing mirrors the Base layer only -- Shift is shared
        # device-wide and gets its own summary line in the full mockup,
        # not a callout on the part itself (module docstring).
        self.view.load_state({"buttons": {"default": {}, "shift": {"a": "e"}}})
        self.assertEqual(self.view.diagram._bindings, {})

    def test_load_state_skips_unremapped_buttons(self):
        self.view.load_state({"buttons": {"default": {"a": None, "b": "r"}, "shift": {}}})
        self.assertNotIn("a", self.view.diagram._bindings)

    def test_load_state_uses_the_read_only_wording_not_the_editable_fields(self):
        # Same convention BindingRow.set_shift_reference() already uses for
        # its own read-only column -- keycode_display_text(), not
        # BindingField's "Raw: ..." phrasing, which is specifically for an
        # editable field.
        self.view.load_state({"buttons": {"default": {"a": "0xab"}, "shift": {}}})
        self.assertEqual(self.view.diagram._bindings["a"], "Unrecognised code 0xab (kept as read)")


if __name__ == "__main__":
    unittest.main()
