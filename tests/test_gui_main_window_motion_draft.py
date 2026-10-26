"""MainWindow's Motion draft wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the sixth S6 slice. Mirrors
test_gui_main_window_sticks_draft.py's shape exactly; Motion is the same
per-side/per-profile scope as Sticks/Triggers.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import MOTION_FIELDS
from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, read_back


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class MotionFastPathTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state.setdefault("motion", {"aim": {}, "tilt": {}})
        window._state["motion"]["aim"]["sensitivity_scale"] = 50
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_motion_draft()
        window.motion_view.load_state(window._state)
        return window

    def test_touching_a_field_updates_the_rail_count_and_shows_the_write_button(self):
        window = self._window()
        self.assertTrue(window.motion_write_btn.isHidden())

        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)

        self.assertEqual(window._motion_draft.edit_count, 1)
        self.assertEqual(window.rail._nav_buttons["motion"].text(), "Motion (1)")
        self.assertFalse(window.motion_write_btn.isHidden())
        self.assertEqual(window.motion_write_btn.text(), "Write 1 change")
        self.assertTrue(window.sticks_write_btn.isHidden())  # unrelated scope, untouched

    def test_reverting_drops_the_count_and_hides_the_button_again(self):
        window = self._window()
        side = window.motion_view.sides["aim"]
        side.sensitivity_scale.setValue(10)
        side._revert_setting("sensitivity_scale")

        self.assertEqual(window._motion_draft.edit_count, 0)
        self.assertEqual(window.rail._nav_buttons["motion"].text(), "Motion")
        self.assertTrue(window.motion_write_btn.isHidden())

    def test_clicking_write_emits_execute_requested_with_the_right_payload(self):
        window = self._window()
        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._connection_generation = 7

        window._on_write_motion_clicked()

        self.assertTrue(window._syncing)
        self.assertEqual(len(calls), 1)
        intents, baseline, gen = calls[0]
        self.assertEqual(len(intents), 1)
        self.assertIsInstance(intents[0], ApprovedIntent)
        self.assertEqual(intents[0].path, ("motion", "aim", "sensitivity_scale"))
        self.assertEqual(intents[0].desired, 10)
        self.assertEqual(baseline["motion"]["aim"]["sensitivity_scale"], 50)  # baseline, not edited
        self.assertEqual(gen, 7)

    def test_clicking_write_with_nothing_touched_is_a_no_op(self):
        window = self._window()
        calls = []
        window.execute_requested.connect(lambda *a: calls.append(a))
        window._on_write_motion_clicked()
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
        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        window._on_write_motion_clicked()

        rb = self._real_read_back(
            ("motion", "aim", "sensitivity_scale"), MOTION_FIELDS["aim"]["sensitivity_scale"], 10, 2,
            fresh_value=50, post_write_state={"motion": {"aim": {"sensitivity_scale": 10}}})
        window.set_execute_finished(True, "Written.", rb)

        self.assertFalse(window._syncing)
        self.assertEqual(window._motion_draft.edit_count, 0)
        self.assertTrue(window.motion_write_btn.isHidden())
        self.assertEqual(window._state["motion"]["aim"]["sensitivity_scale"], 10)
        self.assertEqual(window.motion_view.sides["aim"].sensitivity_scale.value(), 10)

    def test_readback_mismatch_keeps_the_field_touched_not_silently_accepted(self):
        """FEASIBILITY.md M1: "read-back mismatch => draft retained"."""
        window = self._window()
        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        window._on_write_motion_clicked()

        rb = self._real_read_back(
            ("motion", "aim", "sensitivity_scale"), MOTION_FIELDS["aim"]["sensitivity_scale"], 10, 2,
            fresh_value=50, post_write_state={"motion": {"aim": {"sensitivity_scale": 50}}})  # didn't take
        self.assertEqual(rb.ok, ())
        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window.set_execute_finished(False, "1 field(s) read back differently than written.", rb)

        self.assertEqual(window._motion_draft.edit_count, 1)
        self.assertFalse(window.motion_write_btn.isHidden())

    def test_set_connection_generation_discards_a_stale_motion_draft(self):
        window = self._window()
        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        self.assertEqual(window._motion_draft.edit_count, 1)

        window.set_connection_generation(2)

        self.assertEqual(window._motion_draft.edit_count, 0)

    def test_sync_now_success_also_clears_the_motion_draft(self):
        window = self._window()
        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        self.assertEqual(window._motion_draft.edit_count, 1)

        window.set_sync_finished(True, "State applied (0 binding(s) already matched, skipped).")

        self.assertEqual(window._motion_draft.edit_count, 0)

    def test_profile_switch_discards_the_per_profile_motion_draft(self):
        window = self._window()
        window.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        self.assertEqual(window._motion_draft.edit_count, 1)

        with mock.patch.object(window, "request_read_from_device"):
            window._on_profile_changed(3)

        self.assertEqual(window._motion_draft.edit_count, 0)


if __name__ == "__main__":
    unittest.main()
