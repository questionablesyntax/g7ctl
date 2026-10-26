"""MainWindow's review-sheet escalation wiring (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S/DESIGN-SPEC.md 10.3): "If it finds a
conflict... it escalates to the full review sheet. Any change touching
shared scope, or more than three rows, always uses the sheet." Mocks
`ReviewSheet` itself (a real modal `exec()` would block the test) --
this file's own job is MainWindow's decision logic around the sheet
(which scope owns the job, force_conflicts, re-locking the UI), not the
sheet's own rendering (covered by test_components_review_sheet.py).
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QDialog
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import VIBRATION_LEVEL_FIELDS
from pyg7.workflow import (
    ApprovedIntent,
    Classification,
    DraftRevision,
    ExecutionResult,
    FieldOutcome,
    prepare,
    read_back,
)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ExecuteRequestedSignalShapeTest(unittest.TestCase):
    """Dock's write handler used to pass a 4th is_shared_scope=True arg
    (dropped 2026-10-26 -- shared scope alone no longer forces the
    sheet, see watcher._do_execute()'s own docstring). Both Dock and an
    ordinary per-profile scope now emit the same 3-arg shape."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state_confirmed = True
        window._connection_state = "connected"
        return window

    def test_dock_write_emits_the_plain_three_arg_signal(self):
        window = self._window()
        window._state["dock_led_brightness"] = 25
        window._reset_dock_draft()
        window.settings_view.load_state(window._state)
        window.settings_view.brightness.set_value("100")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))

        window._on_write_dock_clicked()

        self.assertEqual(len(calls), 1)

    def test_vibration_write_emits_the_plain_three_arg_signal(self):
        window = self._window()
        window._state["vibration"]["left_grip"] = 25
        window._reset_vibration_draft()
        window.vibration_view.load_state(window._state)
        window.vibration_view.sliders["left_grip"].set_value("75")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))

        window._on_write_vibration_clicked()

        self.assertEqual(len(calls), 1)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class SetNeedsReviewTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window_with_pending_vibration_write(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["vibration"]["left_grip"] = 25
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_vibration_draft()
        window.vibration_view.load_state(window._state)
        window.vibration_view.sliders["left_grip"].set_value("75")
        window._pending_execute_scope = "vibration"
        window._syncing = True  # as _start_execute() would have left it
        return window

    def _job(self):
        intent = ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2)
        return prepare("t", DraftRevision("t", 1), 1, [intent],
                        baseline_state={"vibration": {"left_grip": 25}},
                        fresh_state={"vibration": {"left_grip": 25}})

    def test_clicking_write_in_the_sheet_emits_execute_reviewed_requested_with_force_conflicts(self):
        window = self._window_with_pending_vibration_write()
        job = self._job()
        calls = []
        window.execute_reviewed_requested.connect(lambda j, gen, force: calls.append((j, gen, force)))

        with mock.patch("g7ctlc.main_window.ReviewSheet") as mock_sheet_cls:
            mock_sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            window._connection_generation = 5
            window.set_needs_review(job, {"vibration": {"left_grip": 25}})

        self.assertEqual(len(calls), 1)
        emitted_job, gen, force = calls[0]
        self.assertIs(emitted_job, job)
        self.assertEqual(gen, 5)
        self.assertTrue(force)
        # Still mid-write -- scope must survive for the eventual set_execute_finished().
        self.assertEqual(window._pending_execute_scope, "vibration")
        self.assertTrue(window._syncing)
        self.assertFalse(window.vibration_write_btn.isEnabled())  # locked again for the write
        self.assertFalse(window.rail.read_button.isEnabled())

    def test_keep_editing_clears_the_pending_scope_and_unlocks_the_ui(self):
        window = self._window_with_pending_vibration_write()
        job = self._job()
        calls = []
        window.execute_reviewed_requested.connect(lambda *a: calls.append(a))

        with mock.patch("g7ctlc.main_window.ReviewSheet") as mock_sheet_cls:
            mock_sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            window.set_needs_review(job, {"vibration": {"left_grip": 25}})

        self.assertEqual(calls, [])
        self.assertIsNone(window._pending_execute_scope)
        self.assertFalse(window._syncing)
        self.assertTrue(window.rail.read_button.isEnabled())

    def test_the_scope_label_passed_to_the_sheet_is_human_readable(self):
        window = self._window_with_pending_vibration_write()
        job = self._job()

        with mock.patch("g7ctlc.main_window.ReviewSheet") as mock_sheet_cls:
            mock_sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            window.set_needs_review(job, {"vibration": {"left_grip": 25}})

        args, _kwargs = mock_sheet_cls.call_args
        self.assertEqual(args[1], "Vibration")

    def test_a_full_round_trip_through_the_reviewed_write_still_updates_the_right_draft(self):
        """The sheet's own write path reaches set_execute_finished() the
        same way the ordinary fast path does -- same scope dispatch, no
        separate code path for "did this go through the sheet"."""
        window = self._window_with_pending_vibration_write()
        job = self._job()

        with mock.patch("g7ctlc.main_window.ReviewSheet") as mock_sheet_cls:
            mock_sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            window._connection_generation = 1
            window.set_needs_review(job, {"vibration": {"left_grip": 25}})

        outcome = FieldOutcome(
            ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2),
            Classification.CLEAN, baseline_value=25, fresh_value=25)
        result = ExecutionResult(job_id="t", executed=(outcome,))
        rb = read_back(result, {"vibration": {"left_grip": 75}})
        window.set_execute_finished(True, "Written.", rb)

        self.assertEqual(window._vibration_draft.edit_count, 0)
        self.assertEqual(window._state["vibration"]["left_grip"], 75)
        self.assertTrue(window.vibration_write_btn.isHidden())


if __name__ == "__main__":
    unittest.main()
