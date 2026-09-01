"""TrayIcon.set_state()/set_syncing() -- the Release Device action's own
_syncing guard.

Real bug, found 2026-09-01 (second bug-hunt pass): main_window.py
deliberately disables its own release_btn during a sync/read
(request_sync_now()'s own comment: "no reason to let a click through
mid-sync"), and _auto_release_if_still_unfocused() separately re-checks
_syncing before ever emitting release_toggled -- but the tray icon's own
Release Device action had neither protection, bypassing the one guard
every other release-trigger in the app was deliberately hardened with.
Fixed via a new MainWindow.syncing_changed signal, since set_state() alone
can't see _syncing toggle (connection state stays "connected" throughout
a sync/read, so nothing re-invokes set_state() just because a job starts
or finishes).

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent,
same as the other g7ctlc test modules.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ReleaseActionSyncGuardTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tray(self):
        from g7ctlc.tray import TrayIcon
        # A minimal stand-in is enough: TrayIcon's __init__ only needs
        # main_window.request_sync_now to exist as a connectable slot, it's
        # never actually invoked by constructing the tray.
        fake_window = mock.Mock()
        return TrayIcon(fake_window)

    def test_release_action_enabled_when_connected_and_not_syncing(self):
        tray = self._tray()
        tray.set_state("connected")
        self.assertTrue(tray.release_action.isEnabled())

    def test_release_action_disabled_the_moment_syncing_starts(self):
        tray = self._tray()
        tray.set_state("connected")
        tray.set_syncing(True)
        self.assertFalse(tray.release_action.isEnabled())

    def test_release_action_re_enabled_once_syncing_finishes(self):
        tray = self._tray()
        tray.set_state("connected")
        tray.set_syncing(True)
        tray.set_syncing(False)
        self.assertTrue(tray.release_action.isEnabled())

    def test_set_state_itself_respects_an_already_in_flight_sync(self):
        # The order a real app could hit this in: a sync starts while
        # already connected, then something else re-invokes set_state()
        # (e.g. a battery/firmware update triggers no state change, but
        # defensively confirms set_state() alone can't re-enable it).
        tray = self._tray()
        tray.set_syncing(True)
        tray.set_state("connected")
        self.assertFalse(tray.release_action.isEnabled())

    def test_syncing_does_not_affect_the_paused_reconnect_action(self):
        # "Reconnect" (the paused-state relabeling of the same action) was
        # never part of this bug -- a sync can't be in flight while paused
        # in the first place (nothing left claimed to sync against). Pins
        # that the fix didn't accidentally touch this unrelated state.
        tray = self._tray()
        tray.set_state("paused")
        tray.set_syncing(True)
        self.assertTrue(tray.release_action.isEnabled())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class IconBuildDedupTest(unittest.TestCase):
    """_STATE_ICON_FILES maps "connecting" and "no_controller" to the same
    icon_yellow.png -- _state_icon() re-scales into all 9 _ICON_SIZES on
    every call, no reason to pay for that twice for identical pixmap
    content. Found by a dedicated efficiency pass, 2026-09-01."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_state_icon_is_built_once_per_unique_filename(self):
        from g7ctlc import tray as tray_mod
        with mock.patch.object(tray_mod, "_state_icon",
                               side_effect=tray_mod._state_icon) as build:
            t = tray_mod.TrayIcon(mock.Mock())
        unique_files = set(tray_mod._STATE_ICON_FILES.values())
        self.assertEqual(build.call_count, len(unique_files))
        # And the two states sharing a file must end up with the same
        # object, not two separately-built QIcons with identical content.
        self.assertIs(t._icons["connecting"], t._icons["no_controller"])


if __name__ == "__main__":
    unittest.main()
