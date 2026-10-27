"""MainWindow's S7 cross-scope batch write (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- "Write all changes," a single write
spanning every scope with an outstanding draft at once. No escalation
rule of its own: the same conflict-or->3-rows test every other write
already uses decides whether this needs the review sheet (see
MainWindow._on_write_all_clicked()'s own docstring for why "more than
one scope always escalates" was dropped the same day it was proposed).

Runs headless; skipped entirely if PyQt6 is absent, same as the other
g7ctlc test modules.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QDialog
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import DOCK_FIELDS, VIBRATION_LEVEL_FIELDS
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
class WriteAllButtonVisibilityTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["vibration"]["left_grip"] = 25
        window._state["dock_led_brightness"] = 25
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_vibration_draft()
        window._reset_dock_draft()
        window.vibration_view.load_state(window._state)
        window.settings_view.load_state(window._state)
        return window

    def test_hidden_with_only_one_dirty_scope(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertTrue(window.write_all_btn.isHidden())

    def test_shown_once_a_second_scope_goes_dirty(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")

        self.assertFalse(window.write_all_btn.isHidden())
        self.assertEqual(window.write_all_btn.text(), "Write all 2 changes")

    def test_hides_again_once_back_down_to_one_dirty_scope(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")
        self.assertFalse(window.write_all_btn.isHidden())  # sanity

        window.settings_view.revert_all()

        self.assertTrue(window.write_all_btn.isHidden())

    def test_count_sums_every_dirty_scopes_own_edit_count(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.vibration_view.sliders["right_grip"].set_value("75")  # 2 vibration edits
        window.settings_view.brightness.set_value("100")  # 1 dock edit

        self.assertEqual(window.write_all_btn.text(), "Write all 3 changes")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class WriteAllClickTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["vibration"]["left_grip"] = 25
        window._state["dock_led_brightness"] = 50
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_vibration_draft()
        window._reset_dock_draft()
        window.vibration_view.load_state(window._state)
        window.settings_view.load_state(window._state)
        return window

    def test_with_fewer_than_two_dirty_scopes_is_a_no_op(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        calls = []
        window.execute_requested.connect(lambda *a: calls.append(a))

        window._on_write_all_clicked()

        self.assertEqual(calls, [])
        self.assertIsNone(window._pending_execute_scopes)

    def test_combines_intents_and_baselines_from_every_dirty_scope(self):
        """The real point of the feature: one write, intents from two
        different pages, each compared against ITS OWN baseline -- not a
        wholesale merge of two different whole-state snapshots (see
        _on_write_all_clicked()'s own docstring for why that would be
        unsafe)."""
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")
        calls = []
        window.execute_requested.connect(lambda intents, baseline, gen: calls.append((intents, baseline, gen)))
        window._connection_generation = 9

        window._on_write_all_clicked()

        self.assertEqual(window._pending_execute_scopes, ["vibration", "dock"])
        self.assertIsNone(window._pending_execute_scope)
        self.assertTrue(window._syncing)
        self.assertEqual(len(calls), 1)
        intents, baseline, gen = calls[0]
        self.assertEqual(gen, 9)
        paths = {intent.path for intent in intents}
        self.assertEqual(paths, {("vibration", "left_grip"), ("dock_led_brightness",)})
        self.assertEqual(baseline["vibration"]["left_grip"], 25)  # vibration's own baseline
        self.assertEqual(baseline["dock_led_brightness"], 50)  # dock's own baseline, not vibration's

    def test_successful_execute_finished_clears_both_drafts_and_updates_both_views(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")
        window._on_write_all_clicked()

        outcomes = (
            FieldOutcome(
                ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2),
                Classification.CLEAN, baseline_value=25, fresh_value=25),
            FieldOutcome(
                ApprovedIntent(("dock_led_brightness",), 100, DOCK_FIELDS["dock_led_brightness"], profile=1),
                Classification.CLEAN, baseline_value=50, fresh_value=50),
        )
        result = ExecutionResult(job_id="t", executed=outcomes)
        rb = read_back(result, {"vibration": {"left_grip": 75}, "dock_led_brightness": 100})

        window.set_execute_finished(True, "Written.", rb)

        self.assertEqual(window._vibration_draft.edit_count, 0)
        self.assertEqual(window._dock_draft.edit_count, 0)
        self.assertEqual(window._state["vibration"]["left_grip"], 75)
        self.assertEqual(window._state["dock_led_brightness"], 100)
        self.assertIsNone(window._pending_execute_scopes)
        self.assertIsNone(window._pending_execute_scope)
        self.assertTrue(window.vibration_write_btn.isHidden())
        self.assertTrue(window.dock_write_btn.isHidden())
        self.assertTrue(window.write_all_btn.isHidden())

    def test_a_read_back_mismatch_on_one_scope_does_not_clear_the_other(self):
        """FEASIBILITY.md M1: "read-back mismatch => draft retained" --
        must hold per scope in a combined write, not just for the batch
        as a whole."""
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")
        window._on_write_all_clicked()

        # Only Dock's outcome actually confirmed -- Vibration's own
        # write silently didn't land (simulated via an empty `ok`).
        dock_outcome = FieldOutcome(
            ApprovedIntent(("dock_led_brightness",), 100, DOCK_FIELDS["dock_led_brightness"], profile=1),
            Classification.CLEAN, baseline_value=50, fresh_value=50)
        result = ExecutionResult(job_id="t", executed=(dock_outcome,))
        rb = read_back(result, {"dock_led_brightness": 100})

        window.set_execute_finished(True, "1 of 2 confirmed.", rb)

        self.assertEqual(window._vibration_draft.edit_count, 1)  # still outstanding
        self.assertEqual(window._dock_draft.edit_count, 0)

    def test_failed_execute_finished_refreshes_every_scope_and_warns(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")
        window._on_write_all_clicked()

        with mock.patch("g7ctlc.main_window.QMessageBox.warning") as warn:
            window.set_execute_finished(False, "Lost connection while writing.", None)
            warn.assert_called_once()

        # Nothing was confirmed -- both drafts (and their buttons) stay
        # exactly as they were, just unlocked again.
        self.assertEqual(window._vibration_draft.edit_count, 1)
        self.assertEqual(window._dock_draft.edit_count, 1)
        # Each page's own buttons now show only on that page once two
        # scopes are dirty (ScopeButtonPlacementTest below) -- confirm
        # both are still there by visiting each page.
        window.rail._nav_buttons["vibration"].click()
        self.assertFalse(window.vibration_write_btn.isHidden())
        window.rail._nav_buttons["dock"].click()
        self.assertFalse(window.dock_write_btn.isHidden())
        self.assertIsNone(window._pending_execute_scopes)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ScopeButtonPlacementTest(unittest.TestCase):
    """2026-10-26, first hardware run: with three pages dirty the
    write row showed "Discard 1 change / Write 1 change" three times over
    plus "Write all 3 changes" -- read as one button duplicating itself.
    With one dirty scope nothing changes; with two or more, each scope's
    pair shows only on its own page and "Write all" is the global one."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["vibration"]["left_grip"] = 25
        window._state["dock_led_brightness"] = 50
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_vibration_draft()
        window._reset_dock_draft()
        window.vibration_view.load_state(window._state)
        window.settings_view.load_state(window._state)
        return window

    def test_one_dirty_scope_shows_its_buttons_on_every_page(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")

        for page in ("vibration", "sticks", "overview", "dock"):
            window.rail._nav_buttons[page].click()
            self.assertFalse(window.vibration_write_btn.isHidden(), page)
            self.assertFalse(window.vibration_discard_btn.isHidden(), page)

    def test_two_dirty_scopes_show_only_the_current_pages_own_pair(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")

        window.rail._nav_buttons["vibration"].click()
        self.assertFalse(window.vibration_write_btn.isHidden())
        self.assertFalse(window.vibration_discard_btn.isHidden())
        self.assertTrue(window.dock_write_btn.isHidden())
        self.assertTrue(window.dock_discard_btn.isHidden())

        window.rail._nav_buttons["dock"].click()
        self.assertTrue(window.vibration_write_btn.isHidden())
        self.assertTrue(window.vibration_discard_btn.isHidden())
        self.assertFalse(window.dock_write_btn.isHidden())
        self.assertFalse(window.dock_discard_btn.isHidden())

    def test_write_all_is_visible_on_every_page(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")

        for page in ("vibration", "dock", "sticks", "overview"):
            window.rail._nav_buttons[page].click()
            self.assertFalse(window.write_all_btn.isHidden(), page)

    def test_a_page_with_no_dirty_scope_of_its_own_shows_only_write_all(self):
        window = self._window()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")

        window.rail._nav_buttons["sticks"].click()

        self.assertTrue(window.vibration_write_btn.isHidden())
        self.assertTrue(window.dock_write_btn.isHidden())
        self.assertFalse(window.write_all_btn.isHidden())

    def test_overview_hosts_the_profile_settings_pair(self):
        """Overview carries the second Report Rate control, so a Profile
        Settings edit's own Write/Discard belong on Overview too."""
        window = self._window()
        window._state["report_rate_hz"] = 500
        window._reset_profile_draft()
        window._sync_report_rate_combo()
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.report_rate_combo.set_value("1000")

        window.rail._nav_buttons["overview"].click()

        self.assertFalse(window.profile_write_btn.isHidden())
        self.assertFalse(window.profile_discard_btn.isHidden())
        self.assertTrue(window.vibration_write_btn.isHidden())

    def test_an_edit_made_on_the_current_page_never_hides_its_own_buttons(self):
        """Touching a second scope's field must not flip the first
        scope's already-visible pair off while the user's still on its
        page -- visibility is recomputed for every scope on every change."""
        window = self._window()
        window.rail._nav_buttons["vibration"].click()
        window.vibration_view.sliders["left_grip"].set_value("75")
        self.assertFalse(window.vibration_write_btn.isHidden())

        window.settings_view.brightness.set_value("100")  # second scope goes dirty

        self.assertFalse(window.vibration_write_btn.isHidden())  # still on its page
        self.assertTrue(window.dock_write_btn.isHidden())        # dock's pair waits for its own page


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class WriteAllNeedsReviewTest(unittest.TestCase):
    """set_needs_review()/_revert_review_sheet_path() with a multi-scope
    pending batch -- mocks ReviewSheet itself (a real modal exec() would
    block), same reasoning test_gui_main_window_review_sheet.py's own
    tests use."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow

        window = MainWindow()
        window._state["controller_slot"] = 2
        window._state["vibration"]["left_grip"] = 25
        window._state["dock_led_brightness"] = 50
        window._state_confirmed = True
        window._connection_state = "connected"
        window._reset_vibration_draft()
        window._reset_dock_draft()
        window.vibration_view.load_state(window._state)
        window.settings_view.load_state(window._state)
        window.vibration_view.sliders["left_grip"].set_value("75")
        window.settings_view.brightness.set_value("100")
        window._on_write_all_clicked()  # sets _pending_execute_scopes, locks the UI
        return window

    def _job(self):
        intents = [
            ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2),
            ApprovedIntent(("dock_led_brightness",), 100, DOCK_FIELDS["dock_led_brightness"], profile=1),
        ]
        fresh = {"vibration": {"left_grip": 25}, "dock_led_brightness": 50}
        return prepare("t", DraftRevision("t", 1), 1, intents, baseline_state=fresh, fresh_state=fresh)

    def test_scope_label_names_both_scopes(self):
        window = self._window()
        job = self._job()

        with mock.patch("g7ctlc.main_window.ReviewSheet") as mock_sheet_cls:
            mock_sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            window.set_needs_review(job, {"vibration": {"left_grip": 25}, "dock_led_brightness": 50})

        args, _kwargs = mock_sheet_cls.call_args
        self.assertEqual(args[1], "Vibration and Dock (shared by every profile)")

    def test_a_row_revert_dispatches_to_the_right_view_by_its_own_path(self):
        """The real point: with two scopes pending, _pending_execute_
        scope alone could never tell a Vibration row from a Dock row --
        dispatch has to go by the row's own path, and it does
        (scope_for_path()), so this works with no extra wiring."""
        window = self._window()
        job = self._job()

        with mock.patch("g7ctlc.main_window.ReviewSheet") as mock_sheet_cls:
            mock_sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            window.set_needs_review(job, {"vibration": {"left_grip": 25}, "dock_led_brightness": 50})
            rowReverted = mock_sheet_cls.return_value.rowReverted
            handler = rowReverted.connect.call_args[0][0]

        handler(("dock_led_brightness",))

        self.assertEqual(window._dock_draft.edit_count, 0)
        self.assertEqual(window._vibration_draft.edit_count, 1)  # untouched by the Dock-only revert


if __name__ == "__main__":
    unittest.main()
