"""MainWindow's Buttons draft wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the seventh S6 slice. Mirrors every
other per-profile slice's MainWindow-level shape (test_gui_main_window_
sticks_draft.py etc.) over Buttons' own paths: `("buttons", layer,
button)` for a binding, `(setting,)` for a D-pad option.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import BUTTON_FIELDS, DPAD_FIELDS, Intent
from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, read_back


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsFastPathTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["buttons"].setdefault("default", {})["a"] = "native_a"
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_buttons_draft()
        window.buttons_view.load_state(window._state)
        return window

    def test_touching_a_button_updates_the_rail_count_and_shows_the_write_button(self):
        window = self._window()
        self.assertTrue(window.buttons_write_btn.isHidden())

        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")

        self.assertEqual(window._buttons_draft.edit_count, 1)
        self.assertEqual(window.rail._nav_buttons["buttons"].text(), "Buttons (1)")
        self.assertFalse(window.buttons_write_btn.isHidden())
        self.assertEqual(window.buttons_write_btn.text(), "Write 1 change")
        self.assertTrue(window.motion_write_btn.isHidden())  # unrelated scope, untouched

    def test_reverting_drops_the_count_and_hides_the_button_again(self):
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        window.buttons_view._on_revert_requested()

        self.assertEqual(window._buttons_draft.edit_count, 0)
        self.assertEqual(window.rail._nav_buttons["buttons"].text(), "Buttons")
        self.assertTrue(window.buttons_write_btn.isHidden())

    def test_clicking_write_emits_execute_requested_with_the_right_payload(self):
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._connection_generation = 7

        window._on_write_buttons_clicked()

        self.assertTrue(window._syncing)
        self.assertEqual(len(calls), 1)
        intents, baseline, gen = calls[0]
        self.assertEqual(len(intents), 1)
        self.assertIsInstance(intents[0], ApprovedIntent)
        self.assertEqual(intents[0].path, ("buttons", "default", "a"))
        self.assertEqual(intents[0].desired, "native_x")
        self.assertEqual(baseline["buttons"]["default"]["a"], "native_a")  # baseline, not edited
        self.assertEqual(gen, 7)

    def test_clicking_write_with_nothing_touched_is_a_no_op(self):
        window = self._window()
        calls = []
        window.execute_requested.connect(lambda *a: calls.append(a))
        window._on_write_buttons_clicked()
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
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        window._on_write_buttons_clicked()

        rb = self._real_read_back(
            ("buttons", "default", "a"), BUTTON_FIELDS["default"]["a"], "native_x", 2,
            fresh_value="native_a", post_write_state={"buttons": {"default": {"a": "native_x"}}})
        window.set_execute_finished(True, "Written.", rb)

        self.assertFalse(window._syncing)
        self.assertEqual(window._buttons_draft.edit_count, 0)
        self.assertTrue(window.buttons_write_btn.isHidden())
        self.assertEqual(window._state["buttons"]["default"]["a"], "native_x")

    def test_successful_clear_write_lands_as_none(self):
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen(None)
        window._on_write_buttons_clicked()

        rb = self._real_read_back(
            ("buttons", "default", "a"), BUTTON_FIELDS["default"]["a"], Intent.CLEAR, 2,
            fresh_value="native_a", post_write_state={"buttons": {"default": {"a": None}}})
        window.set_execute_finished(True, "Written.", rb)

        self.assertEqual(window._buttons_draft.edit_count, 0)
        self.assertIsNone(window._state["buttons"]["default"]["a"])

    def test_readback_mismatch_keeps_the_field_touched_not_silently_accepted(self):
        """FEASIBILITY.md M1: "read-back mismatch => draft retained"."""
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        window._on_write_buttons_clicked()

        rb = self._real_read_back(
            ("buttons", "default", "a"), BUTTON_FIELDS["default"]["a"], "native_x", 2,
            fresh_value="native_a", post_write_state={"buttons": {"default": {"a": "native_a"}}})  # didn't take
        self.assertEqual(rb.ok, ())
        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window.set_execute_finished(False, "1 field(s) read back differently than written.", rb)

        self.assertEqual(window._buttons_draft.edit_count, 1)
        self.assertFalse(window.buttons_write_btn.isHidden())

    def test_set_connection_generation_discards_a_stale_buttons_draft(self):
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        self.assertEqual(window._buttons_draft.edit_count, 1)

        window.set_connection_generation(2)

        self.assertEqual(window._buttons_draft.edit_count, 0)

    def test_sync_now_success_also_clears_the_buttons_draft(self):
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        self.assertEqual(window._buttons_draft.edit_count, 1)

        window.set_sync_finished(True, "State applied (0 binding(s) already matched, skipped).")

        self.assertEqual(window._buttons_draft.edit_count, 0)

    def test_profile_switch_discards_the_per_profile_buttons_draft(self):
        window = self._window()
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        self.assertEqual(window._buttons_draft.edit_count, 1)

        with mock.patch.object(window, "request_read_from_device"):
            window._on_profile_changed(3)

        self.assertEqual(window._buttons_draft.edit_count, 0)

    def test_manually_picking_back_to_the_loaded_binding_clears_the_draft_end_to_end(self):
        """REAL BUG, reported 2026-10-26: after binding button B to Native A,
        manually choosing B again from the picker left the "revert change"
        row showing while Write correctly reported that all fields
        match. Proves the
        view-level fix reaches MainWindow's own draft/rail-count/
        write-button through the real fieldReverted signal."""
        window = self._window()  # "a" loaded as "native_a"
        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_x")
        self.assertEqual(window._buttons_draft.edit_count, 1)

        window.buttons_view._on_diagram_activated("a")
        window.buttons_view._on_code_chosen("native_a")  # back to loaded, not Revert

        self.assertEqual(window._buttons_draft.edit_count, 0)
        self.assertTrue(window.buttons_write_btn.isHidden())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsDpadFastPathTest(unittest.TestCase):
    """The two D-pad options share _buttons_draft with the per-button
    bindings -- one scope, one write button, covering both field shapes
    this page has."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["dpad_diagonal_lock"] = False
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_buttons_draft()
        window.buttons_view.load_state(window._state)
        return window

    def test_touching_a_dpad_option_shares_the_buttons_draft_and_write_button(self):
        window = self._window()
        window.buttons_view.dpad_diagonal_lock.setChecked(True)

        self.assertEqual(window._buttons_draft.edit_count, 1)
        self.assertFalse(window.buttons_write_btn.isHidden())

    def test_clicking_write_emits_the_dpad_intent(self):
        window = self._window()
        window.buttons_view.dpad_diagonal_lock.setChecked(True)
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))

        window._on_write_buttons_clicked()

        intents, baseline, _gen = calls[0]
        self.assertEqual(intents[0].path, ("dpad_diagonal_lock",))
        self.assertIs(intents[0].field, DPAD_FIELDS["dpad_diagonal_lock"])
        self.assertTrue(intents[0].desired)
        self.assertFalse(baseline["dpad_diagonal_lock"])

    def test_manually_toggling_back_to_the_loaded_value_clears_the_draft_end_to_end(self):
        """Same real bug as for button bindings, seen on D-Pad options (2026-10-26)."""
        window = self._window()
        window.buttons_view.dpad_diagonal_lock.setChecked(True)
        self.assertEqual(window._buttons_draft.edit_count, 1)

        window.buttons_view.dpad_diagonal_lock.setChecked(False)  # back to loaded, not Revert

        self.assertEqual(window._buttons_draft.edit_count, 0)
        self.assertTrue(window.buttons_write_btn.isHidden())


if __name__ == "__main__":
    unittest.main()
