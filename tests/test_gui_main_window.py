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
