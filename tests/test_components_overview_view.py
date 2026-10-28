"""OverviewView tests, D2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.

See the view's own module docstring for exactly what this page does
(read-only diagram callouts, a scope line, report rate) and what's
deliberately still cut (Front/Back toggle, live connection status).
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

    def test_the_diagram_uses_the_same_control_names_as_buttons(self):
        # Overview once fell back to the raw ids ("DPAD_UP"), because only
        # the Buttons page passed the display names in.
        from g7ctlc.views.buttons_view import ButtonsView

        buttons = ButtonsView(DARK_PALETTE)
        for button_id in ("dpad_up", "dpad_right", "l3", "view", "share"):
            self.assertEqual(
                self.view.diagram._label_for(button_id), buttons.diagram._label_for(button_id))
        self.assertEqual(self.view.diagram._label_for("dpad_up"), "D-Pad Up")

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

    # -- scope line and report rate, 2026-10-22 owner decision ------------

    def test_starts_on_profile_1_with_no_active_profile_claim(self):
        self.assertEqual(
            self.view.scope_line.text_label.text(), "Applies to Profile 1.")

    def test_set_profile_scope_updates_the_sentence(self):
        self.view.set_profile_scope(3, None)
        self.assertEqual(
            self.view.scope_line.text_label.text(), "Applies to Profile 3.")

    def test_set_profile_scope_notes_the_active_profile_when_it_matches(self):
        self.view.set_profile_scope(2, 2)
        self.assertEqual(
            self.view.scope_line.text_label.text(),
            "Applies to Profile 2. The controller is using this profile right now.")

    def test_set_profile_scope_says_nothing_extra_when_a_different_profile_is_active(self):
        self.view.set_profile_scope(2, 3)
        self.assertEqual(
            self.view.scope_line.text_label.text(), "Applies to Profile 2.")

    def test_a_palette_change_also_reaches_the_scope_lines_icon(self):
        # Real finding from the diagram's own history (2026-10-22): a
        # QPainter-rendered pixmap baked at construction time doesn't
        # follow a later palette swap on its own -- confirmed here the
        # same way, not assumed because ControllerDiagram already got it
        # right once.
        before = self.view.scope_line.icon_label.pixmap().toImage()
        self.view.set_palette(LIGHT_PALETTE)
        after = self.view.scope_line.icon_label.pixmap().toImage()
        self.assertNotEqual(before, after)

    def test_report_rate_defaults_to_1000(self):
        self.assertEqual(self.view.report_rate_combo.value(), "1000")

    def test_set_report_rate_updates_the_combo_without_emitting(self):
        received = []
        self.view.reportRateChanged.connect(received.append)
        self.view.set_report_rate(500)
        self.assertEqual(self.view.report_rate_combo.value(), "500")
        self.assertEqual(received, [])

    def test_set_report_rate_falls_back_to_1000_for_an_unknown_value(self):
        # Mirrors MainWindow._sync_report_rate_combo()'s own fallback --
        # default_state_dict()'s confirmed default, not "whatever's last".
        self.view.set_report_rate(333)
        self.assertEqual(self.view.report_rate_combo.value(), "1000")

    def test_choosing_a_report_rate_segment_emits_reportratechanged(self):
        # SegmentedControl's underlying QButtonGroup fires buttonToggled
        # twice for an exclusive-selection change (old button unchecked,
        # new one checked) -- both carry the settled value, not a stray
        # None or the old one, so >=1 occurrence of "250" is the real
        # invariant, not an exact count this widget doesn't promise.
        received = []
        self.view.reportRateChanged.connect(received.append)
        self.view.report_rate_combo.set_value("250")
        self.assertTrue(received and all(v == "250" for v in received))


if __name__ == "__main__":
    unittest.main()
