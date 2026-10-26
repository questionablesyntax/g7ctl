"""MainWindow's S6 fast-path wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the DesiredDraft ledger, the rail
edit count, the "Write N changes" button, and execute_requested/
set_execute_finished's round trip. Vibration's four levels are the only
page wired onto this so far; see vibration_view.py's module docstring.

Runs headless; skipped entirely if PyQt6 is absent, same as the other
g7ctlc test modules.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import VIBRATION_LEVEL_FIELDS
from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, prepare, read_back


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class VibrationFastPathTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["vibration"]["left_grip"] = 25
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_vibration_draft()
        window.vibration_view.load_state(window._state)
        return window

    def test_touching_a_field_updates_the_rail_count_and_shows_the_write_button(self):
        window = self._window()
        self.assertTrue(window.vibration_write_btn.isHidden())

        window.vibration_view.sliders["left_grip"].set_value("75")

        self.assertEqual(window._vibration_draft.edit_count, 1)
        self.assertEqual(window.rail._nav_buttons["vibration"].text(), "Vibration (1)")
        self.assertFalse(window.vibration_write_btn.isHidden())
        self.assertEqual(window.vibration_write_btn.text(), "Write 1 change")

    def test_reverting_drops_the_count_and_hides_the_button_again(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.vibration_view._revert_level("left_grip")

        self.assertEqual(window._vibration_draft.edit_count, 0)
        self.assertEqual(window.rail._nav_buttons["vibration"].text(), "Vibration")
        self.assertTrue(window.vibration_write_btn.isHidden())

    def test_discard_button_reverts_the_field_through_the_view_and_clears_the_draft(self):
        """Scope-level "Discard changes" (IMPLEMENTATION-PLAN.md's "Not
        started" list, item 2) -- goes through the real view signal
        chain (view.revert_all() -> fieldReverted -> untouch()), not a
        separate MainWindow-side bulk-discard path."""
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertFalse(window.vibration_discard_btn.isHidden())
        self.assertEqual(window.vibration_discard_btn.text(), "Discard 1 change")

        window._on_discard_vibration_clicked()

        self.assertEqual(window._vibration_draft.edit_count, 0)
        self.assertEqual(window.rail._nav_buttons["vibration"].text(), "Vibration")
        self.assertTrue(window.vibration_write_btn.isHidden())
        self.assertTrue(window.vibration_discard_btn.isHidden())
        self.assertEqual(window.vibration_view.sliders["left_grip"].value(), "25")

    def test_discard_with_nothing_touched_is_a_no_op(self):
        window = self._window()
        window._on_discard_vibration_clicked()  # must not raise with an empty draft
        self.assertEqual(window._vibration_draft.edit_count, 0)

    def test_discard_button_is_disabled_while_syncing(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window._lock_write_ui()
        self.assertFalse(window.vibration_discard_btn.isEnabled())

    def test_clicking_write_emits_execute_requested_with_the_right_payload(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._connection_generation = 7

        window._on_write_vibration_clicked()

        self.assertTrue(window._syncing)
        self.assertEqual(len(calls), 1)
        intents, baseline, gen = calls[0]
        self.assertEqual(len(intents), 1)
        self.assertIsInstance(intents[0], ApprovedIntent)
        self.assertEqual(intents[0].path, ("vibration", "left_grip"))
        self.assertEqual(intents[0].desired, 75)
        self.assertEqual(baseline["vibration"]["left_grip"], 25)  # the baseline, not the edited value
        self.assertEqual(gen, 7)

    def test_clicking_write_with_nothing_touched_is_a_no_op(self):
        window = self._window()
        calls = []
        window.execute_requested.connect(lambda *a: calls.append(a))
        window._on_write_vibration_clicked()
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
        window.vibration_view.sliders["left_grip"].set_value("75")
        window._on_write_vibration_clicked()

        rb = self._real_read_back(
            ("vibration", "left_grip"), VIBRATION_LEVEL_FIELDS["left_grip"], 75, 2,
            fresh_value=25, post_write_state={"vibration": {"left_grip": 75}})
        window.set_execute_finished(True, "Written.", rb)

        self.assertFalse(window._syncing)
        self.assertEqual(window._vibration_draft.edit_count, 0)
        self.assertTrue(window.vibration_write_btn.isHidden())
        self.assertEqual(window._state["vibration"]["left_grip"], 75)
        self.assertEqual(window.vibration_view.sliders["left_grip"].value(), "75")

    def test_a_second_write_after_a_successful_one_is_not_misclassified_as_a_conflict(self):
        """REAL BUG, found live on hardware 2026-10-26 (hardware test): Left
        Grip 25% -> write 75% (succeeds) -> move back to 50% -> write ->
        failed with "Something changed on the controller," even though
        nothing external had. Caused by the draft's own ObservedSnapshot
        never refreshing after the first successful write, so the SECOND
        prepare() compared the real post-write-1 value (75) against the
        stale pre-write-1 baseline (25) and correctly, by its own rules,
        called that a conflict -- it had no way to know this app's own
        prior write was why they differed. This reproduces the exact
        sequence end to end, including a real prepare() call with the
        baseline this window would actually send, not a shortcut."""
        window = self._window()  # left_grip starts at 25

        window.vibration_view.sliders["left_grip"].set_value("75")
        window._on_write_vibration_clicked()
        rb1 = self._real_read_back(
            ("vibration", "left_grip"), VIBRATION_LEVEL_FIELDS["left_grip"], 75, 2,
            fresh_value=25, post_write_state={"vibration": {"left_grip": 75}})
        window.set_execute_finished(True, "Written.", rb1)
        self.assertEqual(window._vibration_draft.edit_count, 0)

        window.vibration_view.sliders["left_grip"].set_value("50")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._on_write_vibration_clicked()

        intents, baseline, _gen = calls[0]
        self.assertEqual(baseline["vibration"]["left_grip"], 75,
                          "the second write's baseline must reflect the first write's real result, "
                          "not the value from before it")

        # The real classification _do_execute() would perform, against a
        # fresh read showing the controller genuinely still at 75 (the
        # first write's own result, nothing external happened).
        from pyg7.workflow import DraftRevision

        job = prepare("job", DraftRevision("d", 1), 0, intents,
                      baseline_state=baseline, fresh_state={"vibration": {"left_grip": 75}})
        self.assertEqual(job.outcomes[0].classification, Classification.CLEAN)
        self.assertEqual(job.conflicts, ())

    def test_readback_mismatch_keeps_the_field_touched_not_silently_accepted(self):
        """FEASIBILITY.md M1: "read-back mismatch => draft retained"."""
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window._on_write_vibration_clicked()

        rb = self._real_read_back(
            ("vibration", "left_grip"), VIBRATION_LEVEL_FIELDS["left_grip"], 75, 2,
            fresh_value=25, post_write_state={"vibration": {"left_grip": 25}})  # didn't actually take
        self.assertEqual(rb.ok, ())
        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window.set_execute_finished(False, "1 field(s) read back differently than written.", rb)

        self.assertEqual(window._vibration_draft.edit_count, 1)
        self.assertFalse(window.vibration_write_btn.isHidden())

    def test_a_failed_execute_with_no_readback_leaves_the_draft_intact(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window._on_write_vibration_clicked()

        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window.set_execute_finished(False, "Something changed on the controller.", None)

        self.assertEqual(window._vibration_draft.edit_count, 1)
        self.assertFalse(window._syncing)

    def test_set_connection_generation_discards_a_stale_draft(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertEqual(window._vibration_draft.edit_count, 1)

        window.set_connection_generation(2)  # a reconnect happened

        self.assertEqual(window._connection_generation, 2)
        self.assertEqual(window._vibration_draft.edit_count, 0)

    def test_sync_now_success_also_clears_the_vibration_draft(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertEqual(window._vibration_draft.edit_count, 1)

        window.set_sync_finished(True, "State applied (0 binding(s) already matched, skipped).")

        self.assertEqual(window._vibration_draft.edit_count, 0)

    def test_profile_switch_discards_the_per_profile_draft(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertEqual(window._vibration_draft.edit_count, 1)

        with mock.patch.object(window, "request_read_from_device"):
            window._on_profile_changed(3)

        self.assertEqual(window._vibration_draft.edit_count, 0)

    def test_manually_dialing_back_to_the_loaded_value_clears_the_draft_end_to_end(self):
        """REAL BUG, reported 2026-10-26: manually
        reverting a field by picking its original value again (not
        clicking the view's own Revert button) left MainWindow's own
        draft/rail-count/write-button all still claiming an edit. Proves
        the view-level fix (vibration_view.py's own regression test)
        actually reaches MainWindow's draft through the real
        fieldReverted signal, not just the view's own display state."""
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertEqual(window._vibration_draft.edit_count, 1)

        window.vibration_view.sliders["left_grip"].set_value("25")  # back to loaded, not Revert

        self.assertEqual(window._vibration_draft.edit_count, 0)
        self.assertTrue(window.vibration_write_btn.isHidden())


if __name__ == "__main__":
    unittest.main()
