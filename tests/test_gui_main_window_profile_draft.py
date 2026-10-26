"""MainWindow's Profile Settings draft wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the eighth and last S6 page, and the
shortest: one field (report_rate_hz), already a plain FieldSpec since
S3, with no view class of its own -- the mark/revert row and touch
tracking live directly on MainWindow (see _build_profile_settings_page()'s
own docstring). Mirrors every other per-profile slice's MainWindow-level
shape (test_gui_main_window_sticks_draft.py etc.).
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import REPORT_RATE_FIELD
from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, read_back


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ProfileSettingsFastPathTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["report_rate_hz"] = 500
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_profile_draft()
        window._sync_report_rate_combo()
        return window

    def test_touching_report_rate_updates_the_rail_count_and_shows_the_write_button(self):
        window = self._window()
        self.assertTrue(window.profile_write_btn.isHidden())

        window.report_rate_combo.set_value("1000")

        self.assertEqual(window._profile_draft.edit_count, 1)
        self.assertEqual(window.rail._nav_buttons["profile_settings"].text(), "Profile settings (1)")
        self.assertFalse(window.profile_write_btn.isHidden())
        self.assertEqual(window.profile_write_btn.text(), "Write 1 change")
        self.assertTrue(window.buttons_write_btn.isHidden())  # unrelated scope, untouched

    def test_mark_and_revert_appear_only_after_a_real_touch(self):
        window = self._window()
        self.assertTrue(window._report_rate_was_label.isHidden())
        self.assertTrue(window._report_rate_revert_btn.isHidden())

        window.report_rate_combo.set_value("1000")

        self.assertFalse(window._report_rate_was_label.isHidden())
        self.assertIn("500", window._report_rate_was_label.text())
        self.assertFalse(window._report_rate_revert_btn.isHidden())

    def test_editing_via_overview_also_touches_the_profile_draft(self):
        """Both combos funnel through the same _on_report_rate_changed --
        touching either must mark the one shared draft."""
        window = self._window()
        window.overview_view.report_rate_combo.set_value("250")
        self.assertEqual(window._profile_draft.edit_count, 1)
        self.assertEqual(window.report_rate_combo.value(), "250")

    def test_manually_dialing_back_to_the_loaded_value_acts_as_an_implicit_revert(self):
        """Same real bug every other S6 slice needed fixed (2026-10-26,
        hardware test) -- built in from the start here."""
        window = self._window()
        window.report_rate_combo.set_value("1000")
        self.assertEqual(window._profile_draft.edit_count, 1)

        window.report_rate_combo.set_value("500")  # back to the loaded value, not Revert

        self.assertEqual(window._profile_draft.edit_count, 0)
        self.assertTrue(window.profile_write_btn.isHidden())
        self.assertTrue(window._report_rate_was_label.isHidden())

    def test_revert_button_restores_the_loaded_value(self):
        window = self._window()
        window.report_rate_combo.set_value("1000")

        window._revert_report_rate()

        self.assertEqual(window.report_rate_combo.value(), "500")
        self.assertEqual(window._state["report_rate_hz"], 500)
        self.assertEqual(window._profile_draft.edit_count, 0)
        self.assertTrue(window._report_rate_was_label.isHidden())
        self.assertTrue(window.profile_write_btn.isHidden())

    def test_clicking_write_emits_execute_requested_with_the_right_payload(self):
        window = self._window()
        window.report_rate_combo.set_value("1000")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._connection_generation = 7

        window._on_write_profile_clicked()

        self.assertTrue(window._syncing)
        self.assertEqual(len(calls), 1)
        intents, baseline, gen = calls[0]
        self.assertEqual(len(intents), 1)
        self.assertIsInstance(intents[0], ApprovedIntent)
        self.assertEqual(intents[0].path, ("report_rate_hz",))
        self.assertEqual(intents[0].desired, 1000)
        self.assertEqual(baseline["report_rate_hz"], 500)  # the baseline, not the edited value
        self.assertEqual(gen, 7)

    def test_clicking_write_with_nothing_touched_is_a_no_op(self):
        window = self._window()
        calls = []
        window.execute_requested.connect(lambda *a: calls.append(a))
        window._on_write_profile_clicked()
        self.assertEqual(calls, [])
        self.assertFalse(window._syncing)

    def _real_read_back(self, path, field, desired, profile, fresh_value, post_write_state):
        outcome = FieldOutcome(
            ApprovedIntent(path, desired, field, profile), Classification.CLEAN,
            baseline_value=None, fresh_value=fresh_value)
        result = ExecutionResult(job_id="t", executed=(outcome,))
        return read_back(result, post_write_state)

    def test_successful_execute_finished_clears_the_draft_and_updates_state_and_combo(self):
        window = self._window()
        window.report_rate_combo.set_value("1000")
        window._on_write_profile_clicked()

        rb = self._real_read_back(
            ("report_rate_hz",), REPORT_RATE_FIELD, 1000, 2,
            fresh_value=500, post_write_state={"report_rate_hz": 1000})
        window.set_execute_finished(True, "Written.", rb)

        self.assertFalse(window._syncing)
        self.assertEqual(window._profile_draft.edit_count, 0)
        self.assertTrue(window.profile_write_btn.isHidden())
        self.assertEqual(window._state["report_rate_hz"], 1000)
        self.assertEqual(window.report_rate_combo.value(), "1000")

    def test_readback_mismatch_keeps_the_field_touched_not_silently_accepted(self):
        """FEASIBILITY.md M1: "read-back mismatch => draft retained"."""
        window = self._window()
        window.report_rate_combo.set_value("1000")
        window._on_write_profile_clicked()

        rb = self._real_read_back(
            ("report_rate_hz",), REPORT_RATE_FIELD, 1000, 2,
            fresh_value=500, post_write_state={"report_rate_hz": 500})  # didn't take
        self.assertEqual(rb.ok, ())
        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window.set_execute_finished(False, "1 field(s) read back differently than written.", rb)

        self.assertEqual(window._profile_draft.edit_count, 1)
        self.assertFalse(window.profile_write_btn.isHidden())

    def test_set_connection_generation_discards_a_stale_profile_draft(self):
        window = self._window()
        window.report_rate_combo.set_value("1000")
        self.assertEqual(window._profile_draft.edit_count, 1)

        window.set_connection_generation(2)

        self.assertEqual(window._profile_draft.edit_count, 0)

    def test_sync_now_success_also_clears_the_profile_draft(self):
        window = self._window()
        window.report_rate_combo.set_value("1000")
        self.assertEqual(window._profile_draft.edit_count, 1)

        window.set_sync_finished(True, "State applied (0 binding(s) already matched, skipped).")

        self.assertEqual(window._profile_draft.edit_count, 0)

    def test_profile_switch_discards_the_per_profile_profile_draft(self):
        window = self._window()
        window.report_rate_combo.set_value("1000")
        self.assertEqual(window._profile_draft.edit_count, 1)

        with mock.patch.object(window, "request_read_from_device"):
            window._on_profile_changed(3)

        self.assertEqual(window._profile_draft.edit_count, 0)


if __name__ == "__main__":
    unittest.main()
