"""MainWindow's Triggers draft wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the third S6 slice, and the first
per-SIDE one; still per-profile scope like Vibration's (a profile switch
discards it, unlike Dock's). Mirrors test_gui_main_window_fast_path.py
for the write/revert/reconnect/profile-switch mechanics, over Triggers'
nested `("triggers", side, ...)` paths instead of Vibration's flat
`("vibration", key)` ones -- the thing this file's own tests exist to
confirm `_apply_path()`'s generalization actually handles.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import TRIGGER_FIELDS
from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, read_back


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class TriggersFastPathTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["triggers"]["left"]["deadzone"] = {"initial": 0, "max": 100}
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_triggers_draft()
        window.triggers_view.load_state(window._state)
        return window

    def test_touching_a_field_updates_the_rail_count_and_shows_the_write_button(self):
        window = self._window()
        self.assertTrue(window.triggers_write_btn.isHidden())

        window.triggers_view.sides["left"].dz_initial.setValue(10)

        self.assertEqual(window._triggers_draft.edit_count, 1)
        self.assertEqual(window.rail._nav_buttons["triggers"].text(), "Triggers (1)")
        self.assertFalse(window.triggers_write_btn.isHidden())
        self.assertEqual(window.triggers_write_btn.text(), "Write 1 change")
        self.assertTrue(window.vibration_write_btn.isHidden())  # unrelated scope, untouched

    def test_reverting_drops_the_count_and_hides_the_button_again(self):
        window = self._window()
        side = window.triggers_view.sides["left"]
        side.dz_initial.setValue(10)
        side._revert_setting("deadzone_initial")

        self.assertEqual(window._triggers_draft.edit_count, 0)
        self.assertEqual(window.rail._nav_buttons["triggers"].text(), "Triggers")
        self.assertTrue(window.triggers_write_btn.isHidden())

    def test_clicking_write_emits_execute_requested_with_the_right_nested_payload(self):
        window = self._window()
        window.triggers_view.sides["left"].dz_initial.setValue(10)
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._connection_generation = 7

        window._on_write_triggers_clicked()

        self.assertTrue(window._syncing)
        self.assertEqual(len(calls), 1)
        intents, baseline, gen = calls[0]
        self.assertEqual(len(intents), 1)
        self.assertIsInstance(intents[0], ApprovedIntent)
        self.assertEqual(intents[0].path, ("triggers", "left", "deadzone", "initial"))
        self.assertEqual(intents[0].desired, 10)
        self.assertEqual(baseline["triggers"]["left"]["deadzone"]["initial"], 0)  # baseline, not edited
        self.assertEqual(gen, 7)

    def test_clicking_write_with_nothing_touched_is_a_no_op(self):
        window = self._window()
        calls = []
        window.execute_requested.connect(lambda *a: calls.append(a))
        window._on_write_triggers_clicked()
        self.assertEqual(calls, [])
        self.assertFalse(window._syncing)

    def _real_read_back(self, path, field, desired, profile, fresh_value, post_write_state):
        outcome = FieldOutcome(
            ApprovedIntent(path, desired, field, profile), Classification.CLEAN,
            baseline_value=None, fresh_value=fresh_value)
        result = ExecutionResult(job_id="t", executed=(outcome,))
        return read_back(result, post_write_state)

    def test_successful_execute_finished_clears_the_draft_and_updates_state_and_view(self):
        window = self._window()
        window.triggers_view.sides["left"].dz_initial.setValue(10)
        window._on_write_triggers_clicked()

        rb = self._real_read_back(
            ("triggers", "left", "deadzone", "initial"), TRIGGER_FIELDS["left"]["deadzone_initial"], 10, 2,
            fresh_value=0, post_write_state={"triggers": {"left": {"deadzone": {"initial": 10}}}})
        window.set_execute_finished(True, "Written.", rb)

        self.assertFalse(window._syncing)
        self.assertEqual(window._triggers_draft.edit_count, 0)
        self.assertTrue(window.triggers_write_btn.isHidden())
        self.assertEqual(window._state["triggers"]["left"]["deadzone"]["initial"], 10)
        self.assertEqual(window.triggers_view.sides["left"].dz_initial.value(), 10)

    def test_readback_mismatch_keeps_the_field_touched_not_silently_accepted(self):
        """FEASIBILITY.md M1: "read-back mismatch => draft retained"."""
        window = self._window()
        window.triggers_view.sides["left"].dz_initial.setValue(10)
        window._on_write_triggers_clicked()

        rb = self._real_read_back(
            ("triggers", "left", "deadzone", "initial"), TRIGGER_FIELDS["left"]["deadzone_initial"], 10, 2,
            fresh_value=0, post_write_state={"triggers": {"left": {"deadzone": {"initial": 0}}}})  # didn't take
        self.assertEqual(rb.ok, ())
        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window.set_execute_finished(False, "1 field(s) read back differently than written.", rb)

        self.assertEqual(window._triggers_draft.edit_count, 1)
        self.assertFalse(window.triggers_write_btn.isHidden())

    def test_set_connection_generation_discards_a_stale_triggers_draft(self):
        window = self._window()
        window.triggers_view.sides["left"].dz_initial.setValue(10)
        self.assertEqual(window._triggers_draft.edit_count, 1)

        window.set_connection_generation(2)

        self.assertEqual(window._triggers_draft.edit_count, 0)

    def test_sync_now_success_also_clears_the_triggers_draft(self):
        window = self._window()
        window.triggers_view.sides["left"].dz_initial.setValue(10)
        self.assertEqual(window._triggers_draft.edit_count, 1)

        window.set_sync_finished(True, "State applied (0 binding(s) already matched, skipped).")

        self.assertEqual(window._triggers_draft.edit_count, 0)

    def test_profile_switch_discards_the_per_profile_triggers_draft(self):
        window = self._window()
        window.triggers_view.sides["left"].dz_initial.setValue(10)
        self.assertEqual(window._triggers_draft.edit_count, 1)

        with mock.patch.object(window, "request_read_from_device"):
            window._on_profile_changed(3)

        self.assertEqual(window._triggers_draft.edit_count, 0)


if __name__ == "__main__":
    unittest.main()
