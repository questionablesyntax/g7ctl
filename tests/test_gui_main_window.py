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
