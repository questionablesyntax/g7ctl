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
class QuitSyncGuardTest(unittest.TestCase):
    """TrayIcon's Quit action now confirms before quitting mid-sync.

    Real bug, found 2026-09-17 (Astra and Sol's bug-sweeps independently):
    _quit() was a bare @staticmethod calling QApplication.instance().quit()
    unconditionally -- Quit was available and immediate even while a sync
    was actively writing to persistent device config, and app.py's own
    _shutdown() only gets a bounded 10s wait for the watcher thread before
    proceeding anyway. Fixed the way app.py's own comment already
    specified: confirm before quitting at all while main_window._syncing
    is true, reusing the same MainWindow._confirm() seam Sync Now itself
    already uses.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tray(self, syncing: bool):
        from g7ctlc.tray import TrayIcon
        fake_window = mock.Mock()
        fake_window._syncing = syncing
        return TrayIcon(fake_window), fake_window

    def test_quit_while_not_syncing_never_prompts(self):
        tray, fake_window = self._tray(syncing=False)
        with mock.patch("g7ctlc.tray.QApplication") as fake_app_cls:
            tray._quit()
        fake_window._confirm.assert_not_called()
        fake_app_cls.instance.return_value.quit.assert_called_once()

    def test_quit_while_syncing_prompts_and_respects_no(self):
        tray, fake_window = self._tray(syncing=True)
        fake_window._confirm.return_value = False
        with mock.patch("g7ctlc.tray.QApplication") as fake_app_cls:
            tray._quit()
        fake_window._confirm.assert_called_once()
        fake_app_cls.instance.return_value.quit.assert_not_called()

    def test_quit_while_syncing_respects_yes(self):
        tray, fake_window = self._tray(syncing=True)
        fake_window._confirm.return_value = True
        with mock.patch("g7ctlc.tray.QApplication") as fake_app_cls:
            tray._quit()
        fake_window._confirm.assert_called_once()
        fake_app_cls.instance.return_value.quit.assert_called_once()


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class IconBuildDedupTest(unittest.TestCase):
    """_VARIANT_BY_STATE maps "connecting"/"no_controller"/"disconnected"
    onto the same "pending" shape (A5's shape-coded tray icons, D4) --
    _variant_icon() draws into all 9 _ICON_SIZES on every call, no reason
    to pay for that three times for identical pixmap content. Found by a
    dedicated efficiency pass, 2026-09-01 -- ported from the pre-A5 file-
    based dedup this same test covered, same reasoning, new mechanism."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_state_icon_is_built_once_per_unique_variant(self):
        from g7ctlc import tray as tray_mod
        with mock.patch.object(tray_mod, "_variant_icon",
                               side_effect=tray_mod._variant_icon) as build:
            t = tray_mod.TrayIcon(mock.Mock())
        unique_variants = set(tray_mod._VARIANT_BY_STATE.values())
        # +1: _build_icons() also always draws the alarm variant up front
        # (set_error() needs it available before any error ever happens).
        self.assertEqual(build.call_count, len(unique_variants) + 1)
        # And the three states sharing a shape must end up with the same
        # object, not three separately-drawn QIcons with identical content.
        self.assertIs(t._icons["connecting"], t._icons["no_controller"])
        self.assertIs(t._icons["connecting"], t._icons["disconnected"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ShapeCodedStateTest(unittest.TestCase):
    """A5, decision D4: the icon's shape (not just colour) carries
    the state, so it reads at 16px without colour vision -- DIRECTION-A.md
    section 7 item 6.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tray(self):
        from g7ctlc.tray import TrayIcon
        return TrayIcon(mock.Mock())

    def test_connecting_no_controller_and_disconnected_share_one_shape(self):
        tray = self._tray()
        self.assertIs(tray._icons["connecting"], tray._icons["no_controller"])
        self.assertIs(tray._icons["connecting"], tray._icons["disconnected"])

    def test_held_and_released_are_each_their_own_shape(self):
        tray = self._tray()
        self.assertIsNot(tray._icons["connected"], tray._icons["paused"])
        self.assertIsNot(tray._icons["connected"], tray._icons["connecting"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ErrorStateTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tray(self):
        from g7ctlc.tray import TrayIcon
        return TrayIcon(mock.Mock())

    def test_a_message_switches_to_the_alarm_icon_and_tooltip(self):
        tray = self._tray()
        tray.set_state("connected")
        tray.set_error("USB write failed")
        self.assertEqual(tray.icon().cacheKey(), tray._alarm_icon.cacheKey())
        self.assertIn("USB write failed", tray.toolTip())

    def test_an_empty_message_clears_it(self):
        tray = self._tray()
        tray.set_state("connected")
        tray.set_error("USB write failed")
        tray.set_error("")
        self.assertEqual(tray.icon().cacheKey(), tray._icons["connected"].cacheKey())

    def test_a_state_change_does_not_clobber_the_error_tooltip(self):
        """Real bug, found in A6's code review (2026-10-22): set_state()
        used to overwrite the tooltip unconditionally. The icon stayed
        alarm-shaped through a state change while an error was still
        active, but the tooltip explaining why reverted to a generic
        state label -- an inconsistent, confusing combination."""
        tray = self._tray()
        tray.set_state("connected")
        tray.set_error("USB write failed")
        tray.set_state("disconnected")
        self.assertIn("USB write failed", tray.toolTip())
        self.assertEqual(tray.icon().cacheKey(), tray._alarm_icon.cacheKey())

    def test_a_successful_reconnect_clears_a_pending_error(self):
        # Same rule main_window.py's own set_connection_state() already
        # applies to error_label: a successful (re)connect supersedes any
        # earlier error.
        tray = self._tray()
        tray.set_state("paused")
        tray.set_error("Lost connection")
        tray.set_state("connected")
        self.assertFalse(tray._has_error)
        self.assertEqual(tray.icon().cacheKey(), tray._icons["connected"].cacheKey())

    def test_error_overrides_whichever_connection_state_is_current(self):
        tray = self._tray()
        tray.set_state("paused")
        tray.set_error("Lost connection")
        self.assertEqual(tray.icon().cacheKey(), tray._alarm_icon.cacheKey())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class PaletteTest(unittest.TestCase):
    """Tray icons are painted pixmaps, not QSS -- a theme change needs
    this explicit call (app.py wires ThemeController.paletteChanged to
    it), same reasoning as CurveEditor's set_palette() (A4)."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_set_palette_redraws_and_reapplies_the_current_icon(self):
        from g7ctlc.palette import LIGHT_PALETTE
        from g7ctlc.tray import TrayIcon
        tray = TrayIcon(mock.Mock())
        tray.set_state("connected")
        before = tray.icon().cacheKey()
        tray.set_palette(LIGHT_PALETTE)
        self.assertIs(tray._palette, LIGHT_PALETTE)
        self.assertNotEqual(tray.icon().cacheKey(), before, "icon was not redrawn")


if __name__ == "__main__":
    unittest.main()
