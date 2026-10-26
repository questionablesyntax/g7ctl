"""MainWindow's Dock draft wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S/DESIGN-SPEC.md 10.1 #5) -- the first
SHARED-scope draft, which must survive a profile switch unlike
Vibration's per-profile one. Mirrors tests/test_gui_main_window_fast_path.py
for the write/revert/reconnect mechanics; this file's own focus is the
shared-scope-specific behavior: profile switch survival and the
switch-triggered-read clobber guard.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import DOCK_FIELDS
from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, read_back


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class DockDraftTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["dock_led_brightness"] = 25
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_dock_draft()
        window.settings_view.load_state(window._state)
        return window

    def test_touching_dock_brightness_updates_rail_count_and_write_button(self):
        window = self._window()
        window.settings_view.brightness.set_value("100")

        self.assertEqual(window._dock_draft.edit_count, 1)
        self.assertEqual(window.rail._nav_buttons["dock"].text(), "Dock (1)")
        self.assertFalse(window.dock_write_btn.isHidden())
        self.assertEqual(window.dock_write_btn.text(), "Write 1 change")
        self.assertTrue(window.vibration_write_btn.isHidden())  # unrelated scope, untouched

    def test_clicking_write_emits_execute_requested_and_sets_pending_scope(self):
        window = self._window()
        window.settings_view.brightness.set_value("100")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))

        window._on_write_dock_clicked()

        self.assertEqual(window._pending_execute_scope, "dock")
        self.assertEqual(len(calls), 1)
        intents, baseline, _gen = calls[0]
        self.assertEqual(intents[0].path, ("dock_led_brightness",))
        self.assertEqual(baseline["dock_led_brightness"], 25)

    def _real_read_back(self, path, field, desired, fresh_value, post_write_state):
        outcome = FieldOutcome(
            ApprovedIntent(path, desired, field, profile=1), Classification.CLEAN,
            baseline_value=None, fresh_value=fresh_value)
        result = ExecutionResult(job_id="t", executed=(outcome,))
        return read_back(result, post_write_state)

    def test_successful_write_clears_the_dock_draft_and_updates_state(self):
        window = self._window()
        window.settings_view.brightness.set_value("100")
        window._on_write_dock_clicked()

        rb = self._real_read_back(
            ("dock_led_brightness",), DOCK_FIELDS["dock_led_brightness"], 100,
            fresh_value=25, post_write_state={"dock_led_brightness": 100})
        window.set_execute_finished(True, "Written.", rb)

        self.assertEqual(window._dock_draft.edit_count, 0)
        self.assertEqual(window._state["dock_led_brightness"], 100)
        self.assertTrue(window.dock_write_btn.isHidden())

    def test_a_profile_switch_does_not_discard_the_dock_draft(self):
        """The actual point of this slice: Dock is shared scope, so
        switching the viewed profile must leave a pending Dock edit alone
        -- unlike Vibration's per-profile draft, which does get discarded
        (covered by test_gui_main_window_fast_path.py)."""
        window = self._window()
        window.settings_view.brightness.set_value("100")
        self.assertEqual(window._dock_draft.edit_count, 1)

        with mock.patch.object(window, "request_read_from_device"):
            window._on_profile_changed(3)

        self.assertEqual(window._dock_draft.edit_count, 1, "Dock's draft must survive a profile switch")

    def test_a_switch_triggered_read_does_not_clobber_a_pending_dock_edit(self):
        """The other half of the fix: set_read_finished()'s own dock merge
        must not silently overwrite self._state (and thus the drafted
        value on screen) with a fresh read while Dock has an outstanding
        touch -- B2's own class of bug, at the GUI layer this time."""
        window = self._window()
        window.settings_view.brightness.set_value("100")  # drafted, not written

        device_state = {
            "buttons": {"default": {}, "shift": {}}, "dpad_diagonal_lock": False,
            "swap_stick_dpad": False, "continuous_trigger": {}, "sticks": window._state["sticks"],
            "triggers": window._state["triggers"], "motion": window._state["motion"],
            "vibration": window._state["vibration"], "report_rate_hz": 1000,
            "dock_led_brightness": 50,  # something external supposedly reading back as 50
            "dock_auto_on_off": None,
        }
        window.set_read_finished(True, "Read current bindings from Profile 3.", device_state)

        # self._state already holds 100 -- the user's own edit, via the
        # still-active old write path -- before this read ever runs. The
        # guard's job is only to stop the READ's value (50) from stomping
        # that; it never claims to preserve the pre-edit baseline (25).
        self.assertEqual(window._state["dock_led_brightness"], 100,
                          "the drafted value must survive, not get overwritten by the fresh read's 50")
        self.assertEqual(window._dock_draft.edit_count, 1, "the touch itself must survive too")
        self.assertFalse(window.settings_view._brightness_was_label.isHidden(),
                          "the view's own mark must not be wiped by this read either")

    def test_a_switch_triggered_read_still_applies_when_nothing_is_touched(self):
        """The guard must not accidentally freeze Dock forever -- with no
        outstanding touch, a read refreshes it exactly as before."""
        window = self._window()
        device_state = {
            "buttons": {"default": {}, "shift": {}}, "dpad_diagonal_lock": False,
            "swap_stick_dpad": False, "continuous_trigger": {}, "sticks": window._state["sticks"],
            "triggers": window._state["triggers"], "motion": window._state["motion"],
            "vibration": window._state["vibration"], "report_rate_hz": 1000,
            "dock_led_brightness": 50, "dock_auto_on_off": None,
        }
        window.set_read_finished(True, "Read current bindings from Profile 3.", device_state)
        self.assertEqual(window._state["dock_led_brightness"], 50)

    def test_set_connection_generation_discards_the_dock_draft_too(self):
        window = self._window()
        window.settings_view.brightness.set_value("100")
        self.assertEqual(window._dock_draft.edit_count, 1)

        window.set_connection_generation(2)

        self.assertEqual(window._dock_draft.edit_count, 0)

    def test_sync_now_success_clears_both_drafts(self):
        window = self._window()
        window.settings_view.brightness.set_value("100")
        window._reset_vibration_draft()  # baseline for the assertion below
        self.assertEqual(window._dock_draft.edit_count, 1)

        window.set_sync_finished(True, "State applied (0 binding(s) already matched, skipped).")

        self.assertEqual(window._dock_draft.edit_count, 0)
        self.assertEqual(window._vibration_draft.edit_count, 0)


if __name__ == "__main__":
    unittest.main()
