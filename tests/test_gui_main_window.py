"""MainWindow behavior tests: the confirmation gates and failure surfacing
added in the pre-fork UX pass.

Sync Now (pushes to hardware) and Read from Device (overwrites every tab,
including via the profile-switch combo -- not just the button) previously
fired immediately with no confirmation, and a failed sync/read only updated
a small muted status label while a failed local Export/Import already got a
blocking QMessageBox. `MainWindow._confirm()` is monkeypatched rather than
driving a real modal, so these run headless with nothing to click through.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent, same
as the other g7ctlc test modules.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ConfirmationGateTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        window = MainWindow()
        window._state_confirmed = True
        window._connection_state = "connected"
        window.profile_combo.setEnabled(True)
        window.sync_btn.setEnabled(True)
        window.read_btn.setEnabled(True)
        return window

    def test_sync_now_asks_for_confirmation(self):
        window = self._window()
        with mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window.request_sync_now()
        confirm.assert_called_once()
        self.assertFalse(window._syncing)  # declined -- must not have started

    def test_sync_now_proceeds_when_confirmed(self):
        window = self._window()
        with mock.patch.object(window, "_confirm", return_value=True):
            window.request_sync_now()
        self.assertTrue(window._syncing)

    def test_read_from_device_asks_for_confirmation_only_when_dirty(self):
        window = self._window()
        window._dirty = False
        with mock.patch.object(window, "_confirm") as confirm:
            window.request_read_from_device()
        confirm.assert_not_called()
        self.assertTrue(window._syncing)  # clean state -- proceeds straight through

    def test_read_from_device_declined_when_dirty_does_not_proceed(self):
        window = self._window()
        window._dirty = True
        with mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window.request_read_from_device()
        confirm.assert_called_once()
        self.assertFalse(window._syncing)

    def test_profile_switch_goes_through_the_same_dirty_guard(self):
        # _on_profile_changed() used to call request_read_from_device() with
        # no dirty check at all -- since both routes now funnel through the
        # same method, this is the same fix, exercised via the other caller.
        window = self._window()
        window._dirty = True
        window._loading_profile_combo = False
        with mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window._on_profile_changed(0)
        confirm.assert_called_once()
        self.assertFalse(window._syncing)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class FailureSurfacingTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def test_sync_failure_shows_a_warning_dialog(self):
        window = self._window()
        with mock.patch("g7ctlc.main_window.QMessageBox.warning") as warn:
            window.set_sync_finished(False, "Lost connection during sync")
        warn.assert_called_once()
        self.assertIn("Lost connection", warn.call_args.args[-1])

    def test_sync_success_shows_no_dialog(self):
        window = self._window()
        with mock.patch("g7ctlc.main_window.QMessageBox.warning") as warn:
            window.set_sync_finished(True, "Synced.")
        warn.assert_not_called()

    def test_read_failure_shows_a_warning_dialog(self):
        window = self._window()
        with mock.patch("g7ctlc.main_window.QMessageBox.warning") as warn:
            window.set_read_finished(False, "Read failed: timeout", None)
        warn.assert_called_once()
        self.assertIn("Read failed", warn.call_args.args[-1])

    def test_read_success_shows_no_dialog(self):
        window = self._window()
        state = state_mod.default_state_dict("test")
        with mock.patch("g7ctlc.main_window.QMessageBox.warning") as warn:
            window.set_read_finished(True, "Read current bindings.", state)
        warn.assert_not_called()


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class PlayabilityWarningTest(unittest.TestCase):
    """The status bar has to say the controller isn't playable while the app
    holds it. Added 2026-08-01: this was a README-only caveat, and the README
    had it wrong -- it claimed the 2.4GHz dongle was exempt. It isn't (the
    dongle bridges the same session through), so a wireless user hit a dead
    gamepad with nothing on screen tying it to this app.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        window = MainWindow()
        # Pre-set so set_connection_state("connected") sees was_connected and
        # skips the auto-read; this test is only about the label.
        window._connection_state = "connected"
        return window

    def test_warning_shown_while_connected(self):
        window = self._window()
        window.set_connection_state("connected")
        self.assertIn("not usable as a gamepad", window.playability_label.text())

    def test_warning_cleared_once_released(self):
        window = self._window()
        window.set_connection_state("connected")
        window.set_connection_state("paused")
        self.assertEqual("", window.playability_label.text())

    def test_warning_absent_when_disconnected(self):
        window = self._window()
        window.set_connection_state("disconnected")
        self.assertEqual("", window.playability_label.text())

    def test_tray_connected_tooltip_carries_the_same_warning(self):
        from g7ctlc.tray import _STATE_LABELS
        # The window can be hidden to the tray, which is where a user who
        # just found a dead pad is most likely to look first.
        self.assertIn("not usable as a gamepad", _STATE_LABELS["connected"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class AutoReleaseOnUnfocusTest(unittest.TestCase):
    """Releasing the controller when the window loses focus.

    Held, the device sits in vendor/config mode and is not a gamepad at all,
    so tabbing away to play would find a dead pad. Driven by calling the
    handlers directly rather than by real focus events: the offscreen
    platform these run under has no window manager to activate anything.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, active=False, app_window=None):
        from g7ctlc.main_window import MainWindow
        window = MainWindow()
        window._connection_state = "connected"
        window.isActiveWindow = lambda: active
        self._patch = mock.patch(
            "g7ctlc.main_window.QApplication.activeWindow", return_value=app_window)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.emitted = []
        window.release_toggled.connect(self.emitted.append)
        return window

    def test_unfocused_and_idle_releases(self):
        window = self._window()
        window._auto_release_if_still_unfocused()
        self.assertEqual(self.emitted, [True])
        self.assertTrue(window._auto_released)

    def test_a_modal_dialog_does_not_count_as_leaving(self):
        # QMessageBox.question() (the Sync Now / Read confirmations)
        # deactivates its parent, so releasing on bare unfocus would drop the
        # device exactly while the user is confirming a write.
        window = self._window(app_window=object())
        window._auto_release_if_still_unfocused()
        self.assertEqual(self.emitted, [])
        self.assertFalse(window._auto_released)

    def test_mid_sync_defers_instead_of_releasing(self):
        window = self._window()
        window._syncing = True
        window._auto_release_if_still_unfocused()
        self.assertEqual(self.emitted, [],
                         "releasing mid-sync would abort a write to persistent config")
        self.assertTrue(window._auto_release_timer.isActive(),
                        "the release should be retried, not dropped")

    def test_disconnected_releases_nothing(self):
        window = self._window()
        window._connection_state = "disconnected"
        window._auto_release_if_still_unfocused()
        self.assertEqual(self.emitted, [])

    def test_refocus_reconnects_after_an_auto_release(self):
        window = self._window()
        window._auto_release_if_still_unfocused()
        self.emitted.clear()
        window._connection_state = "paused"
        window._reconnect_after_auto_release()
        self.assertEqual(self.emitted, [False])
        self.assertFalse(window._auto_released)

    def test_refocus_never_undoes_an_explicit_release(self):
        window = self._window()
        window._connection_state = "paused"  # user clicked Release Device
        window._reconnect_after_auto_release()
        self.assertEqual(self.emitted, [],
                         "an explicit Release Device has to survive refocusing")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class HideShowReleaseTest(unittest.TestCase):
    """Closing the window to the tray must release, not just unfocusing.

    Driven through hideEvent/showEvent directly: whether hiding also
    produces an ActivationChange is platform-dependent, and relying on it
    is exactly the bug this covers -- close-to-tray left the controller
    held on a real compositor while the offscreen platform released fine.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        window = MainWindow()
        window._connection_state = "connected"
        self.emitted = []
        window.release_toggled.connect(self.emitted.append)
        return window

    def test_hiding_arms_the_release(self):
        from PyQt6.QtGui import QHideEvent
        window = self._window()
        window._auto_release_timer.stop()
        window.hideEvent(QHideEvent())
        self.assertTrue(window._auto_release_timer.isActive(),
                        "close-to-tray has to release the controller too")

    def test_showing_reconnects_after_an_auto_release(self):
        from PyQt6.QtGui import QShowEvent
        window = self._window()
        window._auto_released = True
        window._connection_state = "paused"
        window.showEvent(QShowEvent())
        self.assertEqual(self.emitted, [False])
        self.assertFalse(window._auto_released)

    def test_showing_cancels_a_pending_release(self):
        from PyQt6.QtGui import QHideEvent, QShowEvent
        window = self._window()
        window.hideEvent(QHideEvent())
        window.showEvent(QShowEvent())
        self.assertFalse(window._auto_release_timer.isActive(),
                         "reopening before the timer fires should not release")

    def test_showing_never_undoes_an_explicit_release(self):
        from PyQt6.QtGui import QShowEvent
        window = self._window()
        window._connection_state = "paused"  # user clicked Release Device
        window.showEvent(QShowEvent())
        self.assertEqual(self.emitted, [])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ShiftViewSelectorTest(unittest.TestCase):
    """The Shift layer is a selector entry, not a per-profile column.

    The controller has one Shift layer shared by all four profiles. Sitting
    it beside a per-profile column implied a scope it does not have -- and
    before that, addressing it per profile corrupted Profile 1. It is now a
    peer of the four profiles in the selector, which is how the device
    stores it (five blobs, 0x01-0x05) and how Nexus reads it.
    """

    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def _select(self, window, data):
        window.profile_combo.setCurrentIndex(window.profile_combo.findData(data))

    def test_selector_offers_shift_after_the_four_profiles(self):
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        data = [window.profile_combo.itemData(i) for i in range(window.profile_combo.count())]
        self.assertEqual(data, [1, 2, 3, 4, SHIFT_VIEW])

    def test_selecting_shift_hides_the_profile_scoped_tabs(self):
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        self._select(window, SHIFT_VIEW)
        for index in range(window.tabs.count()):
            widget = window.tabs.widget(index)
            expected = widget is window.buttons_view
            self.assertEqual(window.tabs.isTabVisible(index), expected,
                             f"tab {window.tabs.tabText(index)!r} visibility wrong on the Shift screen")
        self.assertFalse(window.report_rate_combo.isVisibleTo(window))

    def test_returning_to_a_profile_restores_every_tab(self):
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        self._select(window, SHIFT_VIEW)
        self._select(window, 2)
        for index in range(window.tabs.count()):
            self.assertTrue(window.tabs.isTabVisible(index))
        self.assertTrue(window.report_rate_combo.isVisibleTo(window))

    def test_selecting_shift_does_not_retarget_the_profile(self):
        """Sticks/Triggers/Vibration/Report Rate still belong to a real
        profile, and nothing addresses the Shift blob with a profile number
        -- so controller_slot must survive a trip to the Shift screen."""
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        self._select(window, 3)
        self.assertEqual(window._state["controller_slot"], 3)
        self._select(window, SHIFT_VIEW)
        self.assertEqual(window._state["controller_slot"], 3)

    def test_a_read_does_not_yank_the_user_off_the_shift_screen(self):
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        self._select(window, SHIFT_VIEW)
        state = state_mod.default_state_dict("read")
        state["controller_slot"] = 2
        state["buttons"]["shift"] = {"a": "f11"}
        window.set_read_finished(True, "read ok", state)
        self.assertEqual(window.profile_combo.currentData(), SHIFT_VIEW,
                         "a completed read pulled the user back to a profile screen")
        # ...and the Shift bindings that read brought back are on screen.
        self.assertEqual(window.buttons_view._combos[("a", "shift")].currentData(), "f11")


    def test_shift_column_is_hidden_on_a_freshly_launched_window(self):
        """Regression: the Shift column was visible on Profile 1 until the
        user changed profile.

        MainWindow only called `_apply_view()` from `_on_profile_changed`, so
        on a fresh launch nothing ever set the Buttons view's layer and both
        columns stayed visible. Switching away and back "fixed" it for the
        rest of the session, which is why it read as a redraw glitch rather
        than a missing call. Reported from the real desktop 2026-08-08.

        Asserted with `isVisibleTo()`, not `isVisible()`: nothing is shown
        under the offscreen platform, so `isVisible()` is False for every
        widget here and would pass whether or not the bug was present.
        """
        window = self._window()
        view = window.buttons_view
        self.assertEqual(window.profile_combo.currentData(), 1)
        self.assertEqual(view.column_header.text(), "Default Layer")
        self.assertFalse(view._combos[("a", "shift")].isVisibleTo(view),
                         "Shift column visible on Profile 1 before any "
                         "profile change")
        self.assertTrue(view._combos[("a", "default")].isVisibleTo(view))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class BatteryLabelTest(unittest.TestCase):
    """The status-bar charge label.

    Data plumbing only. Offscreen Qt reports visibility for widgets that were
    never painted, so nothing here says how the status bar looks.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def test_hidden_until_there_is_a_reading(self):
        w = self._window()
        self.assertFalse(w.battery_label.isVisible())
        self.assertEqual(w.battery_label.text(), "")

    def test_shows_percent_and_charging(self):
        w = self._window()
        w.set_battery(46, False)
        self.assertIn("46%", w.battery_label.text())
        self.assertNotIn("charging", w.battery_label.text())
        w.set_battery(98, True)
        self.assertIn("charging", w.battery_label.text())

    def test_low_charge_is_highlighted_and_normal_charge_is_not(self):
        w = self._window()
        w.set_battery(46, False)
        self.assertEqual(w.battery_label.styleSheet(), "")
        w.set_battery(12, False)
        self.assertNotEqual(w.battery_label.styleSheet(), "")

    def test_clearing_hides_it_rather_than_showing_a_stale_number(self):
        w = self._window()
        w.set_battery(46, False)
        w.clear_battery()
        self.assertEqual(w.battery_label.text(), "")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ActiveProfileMarkerTest(unittest.TestCase):
    """Roadmap 32: the selector picks what you EDIT; this shows what you PLAY.

    Data plumbing only -- offscreen Qt paints nothing, so how the combo
    actually reads on screen is unverified here.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def _texts(self, w):
        return [w.profile_combo.itemText(i) for i in range(w.profile_combo.count())]

    def test_marks_only_the_active_profile(self):
        w = self._window()
        w.set_active_profile(3)
        texts = self._texts(w)
        self.assertIn("Profile 3 (in use)", texts)
        self.assertIn("Profile 1", texts)
        self.assertEqual(sum("(in use)" in t for t in texts), 1)

    def test_switching_moves_the_marker_rather_than_adding_one(self):
        w = self._window()
        w.set_active_profile(3)
        w.set_active_profile(2)
        texts = self._texts(w)
        self.assertIn("Profile 2 (in use)", texts)
        self.assertIn("Profile 3", texts)
        self.assertEqual(sum("(in use)" in t for t in texts), 1)

    def test_the_shift_entry_is_never_marked(self):
        # The Shift layer is not a profile and cannot be "in use".
        w = self._window()
        w.set_active_profile(1)
        self.assertTrue(any("Shift Layer" in t and "(in use)" not in t for t in self._texts(w)))

    def test_marking_does_not_change_the_selection(self):
        # setItemText must not fire _on_profile_changed -- that would kick
        # off a device read every time the poll noticed the same profile.
        w = self._window()
        before = w.profile_combo.currentIndex()
        w.set_active_profile(4)
        self.assertEqual(w.profile_combo.currentIndex(), before)
