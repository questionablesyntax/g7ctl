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
        window.rail.profile_switch.setEnabled(True)
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
        window._loading_profile_switch = False
        with mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window._on_profile_changed(1)
        confirm.assert_called_once()
        self.assertFalse(window._syncing)

    def test_declining_profile_switch_read_blocks_export(self):
        # REAL BUG, found 2026-09-18 (a code review): _on_profile_changed()
        # sets self._state["controller_slot"] to the NEWLY selected profile
        # unconditionally, before the "Discard unsynced changes?" prompt.
        # Declining that prompt used to leave Export fully available --
        # self._state["controller_slot"] would say the new profile while
        # self._state itself still held the previous, dirty profile's real
        # values, so Export wrote that data out mislabeled as the new
        # profile. _state_confirmed=False (set by _on_profile_changed()
        # right alongside controller_slot, for exactly this reason) must
        # gate Export the same way it already gates Sync.
        window = self._window()
        window._dirty = True
        window._loading_profile_switch = False
        with mock.patch.object(window, "_confirm", return_value=False):
            window._on_profile_changed(1)
        self.assertFalse(window._state_confirmed)

        with mock.patch.object(state_mod, "save_state") as save_state, mock.patch(
            "g7ctlc.main_window.QFileDialog.getSaveFileName",
            return_value=("/tmp/snapshot.json", ""),
        ), mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            window._on_export()
        save_state.assert_not_called()

    def test_read_button_click_forces_a_real_dock_read(self):
        # REAL BUG, found 2026-09-17 (two independent
        # code reviews): read_btn.clicked emits a `checked: bool` that Qt
        # passes straight through to a directly-connected slot -- always
        # False for a plain button -- which would silently defeat
        # force_dock_read if connected without the explicit lambda this
        # test is really checking for. A REAL Qt .click() (not calling
        # request_read_from_device() directly, which would miss this
        # exact class of bug) confirms the signal that actually reaches
        # DeviceWatcher carries True.
        window = self._window()
        window._dirty = False
        received = []
        window.read_requested.connect(lambda slot, force_dock: received.append((slot, force_dock)))
        window.read_btn.click()
        self.assertEqual(received, [(1, True)])

    def test_automatic_profile_switch_read_does_not_force_dock(self):
        window = self._window()
        window._dirty = False
        window._loading_profile_switch = False
        received = []
        window.read_requested.connect(lambda slot, force_dock: received.append((slot, force_dock)))
        window._on_profile_changed(1)
        self.assertEqual(received, [(1, False)])


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

    Held, the device's gamepad interface is claimed and the kernel driver
    detached, so it isn't a gamepad at all while the session lasts -- so
    tabbing away to play would find a dead pad. Driven by calling the
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

    # -- Import/Export's file dialog (reported 2026-10-26: an Import left the
    # app Released, Read and Write disabled; never reproduced) ---------------

    def _open_dialog_that_fires_the_release_timer(self, window):
        """Stand-in for a native file dialog: not a Qt window, so
        activeWindow() stays None, and it stays open long enough for the
        400 ms unfocus timer to fire."""
        def fake(*_args, **_kwargs):
            window._auto_release_if_still_unfocused()
            return ("", "")
        return mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName", side_effect=fake)

    def test_unfocus_does_release_outside_a_file_dialog(self):
        # Control for the next test: the same call does release normally, so
        # that test would notice the guard going missing.
        window = self._window()
        window._auto_release_if_still_unfocused()
        self.assertEqual(self.emitted, [True])

    def test_an_import_dialog_does_not_cost_the_connection(self):
        window = self._window()
        with self._open_dialog_that_fires_the_release_timer(window):
            window._on_import()
        self.assertEqual(self.emitted, [])
        self.assertFalse(window._auto_released)
        self.assertFalse(window._file_dialog_open)

    def test_an_export_dialog_does_not_cost_the_connection(self):
        window = self._window()
        window._state_confirmed = True

        def fake(*_args, **_kwargs):
            window._auto_release_if_still_unfocused()
            return ("", "")
        with mock.patch("g7ctlc.main_window.QFileDialog.getSaveFileName", side_effect=fake):
            window._on_export()
        self.assertEqual(self.emitted, [])
        self.assertFalse(window._file_dialog_open)

    def test_a_release_that_happened_anyway_is_undone_when_the_dialog_closes(self):
        window = self._window(active=True)
        window._auto_released = True
        window._connection_state = "paused"
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName", return_value=("", "")):
            window._on_import()
        self.assertEqual(self.emitted, [False])
        self.assertFalse(window._auto_released)

    def test_an_explicit_release_survives_a_file_dialog(self):
        # Release Device leaves _auto_released False; closing a dialog must
        # not silently reconnect it.
        window = self._window(active=True)
        window._connection_state = "paused"
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName", return_value=("", "")):
            window._on_import()
        self.assertEqual(self.emitted, [])

    def test_leaving_during_the_dialog_still_gets_the_normal_release_check(self):
        window = self._window(active=False)
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName", return_value=("", "")):
            window._on_import()
        self.assertTrue(window._auto_release_timer.isActive())

    def test_refocus_reconnects_after_an_auto_release(self):
        window = self._window()
        window._auto_release_if_still_unfocused()
        self.emitted.clear()
        window._connection_state = "paused"
        window._reconnect_after_auto_release()
        self.assertEqual(self.emitted, [False])
        self.assertFalse(window._auto_released)

    def test_a_too_fast_refocus_does_not_forget_the_pending_reconnect(self):
        # Real bug, found 2026-09-01: refocusing faster than the watcher
        # thread's own poll granularity lands here while pause() has been
        # called but not yet acted on -- _connection_state still reads
        # "connected", not "paused" yet. The old code cleared
        # _auto_released unconditionally regardless, permanently
        # forgetting the release with no reconnect ever emitted -- no
        # future focus change would trigger one either, since the flag
        # was already gone.
        window = self._window()
        window._auto_release_if_still_unfocused()
        self.emitted.clear()
        # _connection_state is deliberately still "connected" here -- the
        # watcher hasn't caught up yet.

        window._reconnect_after_auto_release()

        self.assertEqual(self.emitted, [], "must not reconnect before pause is confirmed")
        self.assertTrue(window._auto_released, "must stay pending, not be forgotten")

        # The watcher catches up moments later.
        window._connection_state = "paused"
        window._reconnect_after_auto_release()
        self.assertEqual(self.emitted, [False])
        self.assertFalse(window._auto_released)

    def test_set_connection_state_paused_self_corrects_a_pending_reconnect(self):
        # The other half of the same fix: set_connection_state() itself
        # acts on a still-pending auto-release the moment "paused" lands,
        # rather than waiting for another focus/show event to notice.
        window = self._window()
        window._auto_release_if_still_unfocused()
        self.emitted.clear()

        window.set_connection_state("paused")

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

    def _select(self, window, slot):
        """`slot` is 1-4, or `g7ctlc.main_window.SHIFT_VIEW`. Goes through
        the rail's own selection methods, same as a real click/Enter would,
        rather than poking private state -- `Rail.pageRequested`/
        `profileChanged` are what MainWindow actually listens to."""
        from g7ctlc.main_window import SHIFT_VIEW
        if slot == SHIFT_VIEW:
            window.rail.pageRequested.emit("shift")
        else:
            window.rail.profile_switch.set_value(str(slot))

    def test_rail_offers_the_four_profile_slots(self):
        window = self._window()
        self.assertEqual(
            [window.rail.profile_switch._values[i] for i in range(4)],
            ["1", "2", "3", "4"],
        )

    def test_selecting_shift_hides_the_profile_scoped_nav_entries(self):
        from g7ctlc.main_window import SHIFT_VIEW
        from g7ctlc.rail import PROFILE_PAGE_KEYS
        window = self._window()
        self._select(window, SHIFT_VIEW)
        for key in PROFILE_PAGE_KEYS:
            expected = key == "buttons"
            self.assertEqual(window.rail.is_page_visible(key), expected,
                             f"rail entry {key!r} visibility wrong on the Shift screen")
        self.assertFalse(window.rail.is_page_visible("dock"))  # same as today's exact behaviour
        self.assertTrue(window.rail.is_page_visible("shift"))

    def test_returning_to_a_profile_restores_every_nav_entry(self):
        from g7ctlc.main_window import SHIFT_VIEW
        from g7ctlc.rail import PROFILE_PAGE_KEYS, SHARED_PAGE_KEYS
        window = self._window()
        self._select(window, SHIFT_VIEW)
        self._select(window, 2)
        for key in (*PROFILE_PAGE_KEYS, *SHARED_PAGE_KEYS):
            self.assertTrue(window.rail.is_page_visible(key))

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
        self.assertIsNone(window.rail.profile_switch.value(),
                         "a completed read pulled the user back to a profile screen")
        self.assertEqual(window.rail.current_page(), "shift")
        # ...and the Shift bindings that read brought back are on screen --
        # no more per-button widget to read directly (D2's rework,
        # 2026-10-22), so this reads the diagram's own callout instead.
        self.assertIn("a", window.buttons_view.diagram._bindings)

    def test_shift_entries_are_hidden_on_a_freshly_launched_window(self):
        """Regression: the Shift column was visible on Profile 1 until the
        user changed profile.

        MainWindow only called `_apply_view()` from `_on_profile_changed`, so
        on a fresh launch nothing ever set the Buttons view's layer and both
        columns stayed visible. Switching away and back "fixed" it for the
        rest of the session, which is why it read as a redraw glitch rather
        than a missing call. Reported from the real desktop 2026-08-08.

        D2's rework (2026-10-22) replaced the column-visibility UI this
        originally guarded with direct `_layer` state, so the real
        invariant now is simply: a fresh window's ButtonsView starts on
        the Default layer, not Shift.
        """
        window = self._window()
        view = window.buttons_view
        self.assertEqual(window.rail.profile_switch.value(), "1")
        self.assertEqual(view._layer, "default",
                         "ButtonsView was left on the Shift layer on a fresh launch")

    def test_sync_warning_mentions_shift_is_shared_while_viewing_it(self):
        """Real bug, found in A6's code review (2026-10-22):
        request_sync_now() compared rail.profile_switch.value() to
        SHIFT_VIEW ("shift"), but _select_shift_view() actually sets that
        control to None (off-scale) -- the comparison could never be true,
        so this warning never showed while genuinely viewing Shift."""
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        window._connection_state = "connected"  # bypass set_connection_state()'s own auto-read
        window._state_confirmed = True
        self._select(window, SHIFT_VIEW)
        with mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window.request_sync_now()
        confirm.assert_called_once()
        self.assertIn("shared by all four profiles", confirm.call_args.args[-1])

    def test_importing_while_on_shift_does_not_light_up_a_profile_segment(self):
        """Same root bug as above, different call site: _sync_profile_switch()
        (reached from an Import, or MainWindow's own construction) used the
        identical broken comparison, so its own "don't yank the user off
        Shift" guard never fired either."""
        from g7ctlc.main_window import SHIFT_VIEW
        window = self._window()
        self._select(window, 2)
        self._select(window, SHIFT_VIEW)
        window._sync_profile_switch()
        self.assertIsNone(window.rail.profile_switch.value(),
                         "a profile-switch sync pulled the user back to a "
                         "numbered profile segment while still on Shift")
        self.assertEqual(window.rail.current_page(), "shift")

    def test_clicking_buttons_while_on_shift_actually_leaves_shift(self):
        """Real bug, found in A6's code review (2026-10-22): "buttons" and
        "shift" route to the same buttons_view widget, so clicking Buttons
        while on Shift only called pages.setCurrentWidget() -- a no-op,
        since that widget was already current -- never _apply_view(), so
        the rail showed "Buttons" selected while the content stayed on the
        Shift layer."""
        window = self._window()
        self._select(window, 3)
        self._select(window, "shift")
        self.assertTrue(window._viewing_shift)
        window.rail.pageRequested.emit("buttons")
        self.assertFalse(window._viewing_shift)
        self.assertEqual(window.buttons_view._layer, "default")
        self.assertEqual(window.rail.profile_switch.value(), "3")
        self.assertTrue(window.rail.is_page_visible("sticks"))


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
        # Checks the `role` dynamic property the redesign's QSS keys off
        # of (A3: the whole app's styling moved off theme.py's inline
        # setStyleSheet() hex literals onto g7ctlc/qss.py's generator --
        # see OwnershipBar.set_battery()), not a literal inline stylesheet
        # string the old main_window.py used to set directly.
        w = self._window()
        w.set_battery(46, False)
        self.assertEqual(w.battery_label.property("role"), "muted")
        w.set_battery(12, False)
        self.assertEqual(w.battery_label.property("role"), "caution")

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

    def test_marks_the_active_profile(self):
        w = self._window()
        w.set_active_profile(3)
        self.assertFalse(w.rail.on_controller_marker.isHidden())
        self.assertIn("3", w.rail._marker_label.text())

    def test_switching_moves_the_marker_rather_than_adding_one(self):
        # The marker is one label, not a per-segment relabelling -- there
        # is structurally only ever one "on controller" fact on screen.
        w = self._window()
        w.set_active_profile(3)
        w.set_active_profile(2)
        self.assertIn("2", w.rail._marker_label.text())
        self.assertNotIn("3", w.rail._marker_label.text())

    def test_no_active_profile_hides_the_marker(self):
        w = self._window()
        w.set_active_profile(None)
        self.assertTrue(w.rail.on_controller_marker.isHidden())

    def test_marking_does_not_change_the_selection(self):
        # set_active_profile() must not fire profileChanged -- that would
        # kick off a device read every time the poll noticed the same
        # profile.
        w = self._window()
        before = w.rail.profile_switch.value()
        w.set_active_profile(4)
        self.assertEqual(w.rail.profile_switch.value(), before)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ContinuousTriggerReachesTheViewTest(unittest.TestCase):
    """Regression, reported from a game on 2026-08-14.

    Continuous Trigger was on for A and Y on the device and the GUI showed it off.
    Cause: set_read_finished() merged buttons, D-pad, sticks, triggers,
    vibration, report rate and dock -- and dropped continuous_trigger on the
    floor. The Buttons tab then painted default_state_dict()'s all-unchecked
    scaffold, which looks exactly like a real reading of "all off".

    Second-order risk, which is why this is a data-loss bug and not a display
    one: ButtonsView._on_edit() writes every checkbox back into the state, so
    any later edit + Sync would have pushed those false values to the device
    and cleared Continuous Trigger the user set in Nexus or via the CLI.

    **These tests go through set_read_finished() deliberately.** The existing
    coverage called ButtonsView.load_state() directly, which always worked --
    it exercised a path the application does not take on a device read, so it
    passed for the entire time the feature was broken.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def _device_state(self, continuous):
        state = state_mod.default_state_dict("from device")
        state["controller_slot"] = 1
        state["continuous_trigger"] = continuous
        return state

    def _latch_checked(self, buttons_view, button_id):
        # No per-button checkbox left to read directly (D2's rework,
        # 2026-10-22) -- activating the diagram opens the shared picker,
        # whose own Latch checkbox is set to match state on every open.
        buttons_view._on_diagram_activated(button_id)
        return buttons_view._picker.latch_checkbox.isChecked()

    def test_device_values_reach_the_checkboxes(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "ok", self._device_state({"a": True, "y": True, "b": False}))
        self.assertTrue(self._latch_checked(w.buttons_view, "a"))
        self.assertTrue(self._latch_checked(w.buttons_view, "y"))
        self.assertFalse(self._latch_checked(w.buttons_view, "b"))

    def test_the_state_dict_itself_carries_them(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "ok", self._device_state({"a": True}))
        self.assertTrue((w._state.get("continuous_trigger") or {}).get("a"))

    def test_a_later_read_clears_flags_that_were_turned_off(self):
        # Replace, not merge: a button switched off elsewhere must not stay
        # checked because an earlier read had it on.
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "ok", self._device_state({"a": True}))
        w.set_read_finished(True, "ok", self._device_state({"a": False}))
        self.assertFalse(self._latch_checked(w.buttons_view, "a"))

    def test_a_device_state_without_the_key_does_not_crash(self):
        # Older state files and any read predating this feature.
        w = self._window()
        w.set_connection_state("connected")
        state = self._device_state({})
        del state["continuous_trigger"]
        w.set_read_finished(True, "ok", state)
        self.assertFalse(self._latch_checked(w.buttons_view, "a"))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class UnconfirmedStateDisplayTest(unittest.TestCase):
    """Roadmap: 'the GUI displays unread state as if it were real'.

    A read failure only ever touched a muted status label and left Sync
    disabled -- everything else about the screen looked exactly like a
    confirmed reading, which is what made a real bug (Continuous Trigger
    dropped by set_read_finished(), see ContinuousTriggerReachesTheViewTest)
    look believable instead of obviously broken. These tests check the
    actual controls go inert, not just Sync Now.

    Corrected 2026-08-19: this used to assert on `w.tabs.isEnabled()`
    directly, from when _refresh_confirmed_display() disabled the whole
    tab widget. That took every QScrollArea's scrollbar down with it --
    a user couldn't even scroll to see an unconfirmed tab's full content,
    reported as a real usability complaint (Reddit, u/Rokofur). The fix
    disables each QScrollArea's contained widget instead, leaving
    self.tabs (and scrolling) always interactive -- browsing isn't
    editing. `w.tabs.isEnabled()` is now always True and no longer means
    anything; _content_locked() below checks the thing that actually
    matters now.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def _content_locked(self, w) -> bool:
        """True iff every scroll area's actual content is disabled --
        the real "is this confirmed" signal now. Also asserts scrolling
        itself is never a casualty, every time this is checked, so no
        test needs to remember to check that part separately."""
        from PyQt6.QtWidgets import QScrollArea
        scrolls = w.pages.findChildren(QScrollArea)
        self.assertTrue(scrolls, "expected at least one QScrollArea under the pages")
        for scroll in scrolls:
            self.assertTrue(scroll.isEnabled(), "a QScrollArea itself must never be disabled")
        return all(not s.widget().isEnabled() for s in scrolls if s.widget() is not None)

    def test_freshly_launched_window_is_unconfirmed(self):
        # A5 of the redesign: a freshly launched window has no controller
        # at all, so the EmptyState covers the page content instead of
        # the banner+disabled-controls combination this test used to
        # check -- the banner would just repeat what the EmptyState
        # already says ("no controller"). The content underneath stays
        # genuinely locked either way; see EmptyStateAndHatchOverlayTest
        # for the EmptyState/banner-suppression behaviour itself.
        w = self._window()
        self.assertTrue(self._content_locked(w))
        self.assertFalse(w.unconfirmed_banner.isVisibleTo(w))

    def test_successful_read_confirms_the_display(self):
        w = self._window()
        w.set_connection_state("connected")
        state = state_mod.default_state_dict("read")
        w.set_read_finished(True, "read ok", state)
        self.assertFalse(self._content_locked(w))
        self.assertFalse(w.unconfirmed_banner.isVisibleTo(w))

    def test_failed_read_leaves_the_display_inert(self):
        w = self._window()
        w.set_connection_state("connected")
        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            w.set_read_finished(False, "Read failed: timeout", None)
        self.assertTrue(self._content_locked(w))
        self.assertTrue(w.unconfirmed_banner.isVisibleTo(w))

    def test_import_confirms_the_display(self):
        w = self._window()
        with mock.patch.object(
            state_mod, "load_state", return_value=state_mod.default_state_dict("imported")
        ), mock.patch(
            "g7ctlc.main_window.QFileDialog.getOpenFileName",
            return_value=("/tmp/snapshot.json", ""),
        ):
            w._on_import()
        self.assertFalse(self._content_locked(w))
        self.assertFalse(w.unconfirmed_banner.isVisibleTo(w))

    def test_switching_profile_un_confirms_immediately_even_before_the_read_returns(self):
        """The specific bug the roadmap item is about: a confirmed reading
        of Profile 1 must not go on looking confirmed for Profile 2 just
        because nothing has failed yet -- the new read hasn't even
        finished."""
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        self.assertFalse(self._content_locked(w))  # sanity: confirmed for Profile 1

        w.rail.profile_switch.set_value("2")

        self.assertFalse(w._state_confirmed)
        self.assertTrue(self._content_locked(w))
        self.assertTrue(w.unconfirmed_banner.isVisibleTo(w))

    def test_a_declined_read_after_switching_profile_stays_unconfirmed(self):
        """Same bug, via the path that made it easy to miss: the user
        declines to discard unsynced edits, so no read even runs -- the
        screen must not keep presenting Profile 1's confirmed values as
        Profile 2's."""
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        w._dirty = True

        with mock.patch.object(w, "_confirm", return_value=False):
            w.rail.profile_switch.set_value("2")

        self.assertFalse(w._state_confirmed)
        self.assertTrue(self._content_locked(w))

    def test_an_in_flight_sync_locks_the_tabs_even_though_state_is_confirmed(self):
        # Real bug, found 2026-09-01: a control left editable while a sync
        # was in flight let an edit made mid-sync race the watcher
        # thread's own iteration over the same state dict, and (for a
        # mid-read edit specifically) get silently overwritten the moment
        # the job landed. _content_locked() used to only ever go True for
        # an unconfirmed reading -- a confirmed reading mid-sync stayed
        # fully editable.
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        self.assertFalse(self._content_locked(w))  # sanity: confirmed, not syncing yet

        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()

        self.assertTrue(w._syncing)
        self.assertTrue(self._content_locked(w))

    def test_report_rate_combo_is_gated_too(self):
        # REAL BUG, found 2026-09-17 (a code review): report_rate_combo
        # used to live in the top selector bar, built before self.tabs
        # even existed -- _content_locked()'s own sweep (and
        # _refresh_confirmed_display()'s real one), keyed on self.tabs'
        # QScrollArea children, structurally could never reach it. A3 of
        # the redesign gave report rate a real rail home of its own
        # ("Profile settings", CRITIC.md #9) wrapped in a QScrollArea like
        # every other page -- closing the structural gap itself, not just
        # special-casing around it (the old main_window.py's
        # _refresh_confirmed_display() had a second, hand-written
        # `self.report_rate_combo.setEnabled(editable)` line specifically
        # for this; A3 deleted it because the generic sweep now reaches it
        # on its own).
        w = self._window()
        self.assertFalse(w.report_rate_combo.isEnabled())  # freshly launched, unconfirmed

        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        self.assertTrue(w.report_rate_combo.isEnabled())  # confirmed, not syncing

        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()
        self.assertFalse(w.report_rate_combo.isEnabled())  # confirmed but mid-sync
        # The banner is specifically about "go read the device" -- an
        # in-flight sync of an already-confirmed reading isn't that.
        self.assertFalse(w.unconfirmed_banner.isVisibleTo(w))

    def test_tabs_unlock_again_once_the_sync_finishes(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()
        self.assertTrue(self._content_locked(w))  # sanity: locked while in flight

        w.set_sync_finished(True, "State applied")

        self.assertFalse(w._syncing)
        self.assertFalse(self._content_locked(w))

    def test_an_in_flight_read_also_locks_the_tabs(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        w._dirty = False  # no confirm prompt needed for this path

        w.request_read_from_device()

        self.assertTrue(w._syncing)
        self.assertTrue(self._content_locked(w))

    def test_scrollbars_stay_usable_while_unconfirmed(self):
        # The exact complaint (Reddit, u/Rokofur): a user should be able to
        # scroll through an unconfirmed tab's full content -- browsing isn't
        # editing, and Sticks/Triggers/Motion specifically have per-side
        # sub-tabs a user may well want to check before a controller's even
        # connected. Named separately from _content_locked's built-in check
        # so this exact regression has its own obvious label if it recurs.
        from PyQt6.QtWidgets import QScrollArea
        w = self._window()
        self.assertFalse(w._state_confirmed)  # freshly launched -- the reported state
        scrolls = w.pages.findChildren(QScrollArea)
        self.assertGreaterEqual(len(scrolls), 6)  # at least one per page, several have two
        for scroll in scrolls:
            self.assertTrue(scroll.isEnabled())
            self.assertTrue(scroll.verticalScrollBar().isEnabled())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ImportedProvenanceBannerTest(unittest.TestCase):
    """DESIGN-SPEC.md section 4 item 2: "An import is labelled 'Imported,
    not read from this controller.'" _on_import() already set
    self._state_confirmed = True (so the page unlocks for editing) and
    showed a one-line status message, but nothing persistent told the
    user the values hadn't actually come from the connected controller
    -- the status text gets overwritten by the next unrelated event.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def _import(self, w):
        with mock.patch.object(
            state_mod, "load_state", return_value=state_mod.default_state_dict("imported")
        ), mock.patch(
            "g7ctlc.main_window.QFileDialog.getOpenFileName",
            return_value=("/tmp/snapshot.json", ""),
        ):
            w._on_import()

    def test_hidden_on_a_freshly_launched_window(self):
        w = self._window()
        self.assertFalse(w.imported_banner.isVisibleTo(w))

    def test_shown_after_an_import(self):
        w = self._window()
        self._import(w)
        self.assertTrue(w._state_imported)
        self.assertTrue(w.imported_banner.isVisibleTo(w))

    def test_a_successful_read_from_device_hides_it_and_clears_the_flag(self):
        w = self._window()
        self._import(w)
        w.set_connection_state("connected")

        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))

        self.assertFalse(w._state_imported)
        self.assertFalse(w.imported_banner.isVisibleTo(w))

    def test_a_successful_sync_now_hides_it_and_clears_the_flag(self):
        w = self._window()
        self._import(w)
        w.set_connection_state("connected")

        w.set_sync_finished(True, "State applied")

        self.assertFalse(w._state_imported)
        self.assertFalse(w.imported_banner.isVisibleTo(w))

    def test_a_failed_sync_does_not_clear_it(self):
        """An import that failed to actually land on the device must
        keep reading as unconfirmed -- the whole point of the flag."""
        w = self._window()
        self._import(w)
        w.set_connection_state("connected")

        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            w.set_sync_finished(False, "Lost connection during sync")

        self.assertTrue(w._state_imported)
        self.assertTrue(w.imported_banner.isVisibleTo(w))

    def test_a_failed_read_does_not_clear_it(self):
        w = self._window()
        self._import(w)
        w.set_connection_state("connected")

        with mock.patch("g7ctlc.main_window.QMessageBox.warning"):
            w.set_read_finished(False, "Read failed: timeout", None)

        self.assertTrue(w._state_imported)
        self.assertTrue(w.imported_banner.isVisibleTo(w))

    def test_switching_profile_does_not_clear_it(self):
        """Whole-state provenance, not per-profile -- an import covers
        every profile at once, so viewing a different one doesn't change
        whether any of it has actually been confirmed against hardware."""
        w = self._window()
        self._import(w)

        w.rail.profile_switch.set_value("2")

        self.assertTrue(w._state_imported)
        self.assertTrue(w.imported_banner.isVisibleTo(w))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ImportExportSyncingGuardTest(unittest.TestCase):
    """Real race, found 2026-09-01: Import/Export were never gated on
    _syncing at all, unlike every other state-affecting control
    (sync_btn/read_btn/release_btn/the profile switch). Export reads self._state
    while the watcher thread may be iterating that same dict object
    mid-sync; Import replaces self._state outright, so a sync that finishes
    after an Import lands calls set_sync_finished() -- which clears the
    dirty flag as if the *imported* state had just been synced, when the
    device actually still holds whatever was pushed before the import.

    This class was itself missing the usual `@unittest.skipIf(QApplication
    is None, ...)` guard every other class here carries -- found during
    A3's port (constructing MainWindow in a PyQt6-less environment crashed
    setUpClass with AttributeError instead of skipping cleanly). Fixed
    alongside the port rather than filed separately, since the fix is this
    one line."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        w = MainWindow()
        w.set_connection_state("connected")
        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        return w

    def test_import_export_button_disabled_during_a_sync(self):
        w = self._window()
        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()
        self.assertFalse(w.import_export_btn.isEnabled())

        w.set_sync_finished(True, "State applied")
        self.assertTrue(w.import_export_btn.isEnabled())

    def test_import_export_button_disabled_during_a_read(self):
        w = self._window()
        w._dirty = False  # no confirm prompt needed for this path
        w.request_read_from_device()
        self.assertFalse(w.import_export_btn.isEnabled())

        w.set_read_finished(True, "read ok", state_mod.default_state_dict("read"))
        self.assertTrue(w.import_export_btn.isEnabled())

    def test_import_does_not_replace_state_mid_sync(self):
        w = self._window()
        original_state = w._state
        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()

        with mock.patch.object(
            state_mod, "load_state", return_value=state_mod.default_state_dict("imported")
        ), mock.patch(
            "g7ctlc.main_window.QFileDialog.getOpenFileName",
            return_value=("/tmp/snapshot.json", ""),
        ):
            w._on_import()

        self.assertIs(w._state, original_state, "Import must not swap self._state while a sync is in flight")

    def test_export_does_not_read_state_mid_sync(self):
        w = self._window()
        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()

        with mock.patch.object(state_mod, "save_state") as save_state, mock.patch(
            "g7ctlc.main_window.QFileDialog.getSaveFileName",
            return_value=("/tmp/snapshot.json", ""),
        ):
            w._on_export()

        save_state.assert_not_called()


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class EmptyStateAndHatchOverlayTest(unittest.TestCase):
    """A5 of the redesign: the "no controller" EmptyState and the unread
    HatchOverlay. Offscreen Qt paints nothing, so these check the actual
    state (which widget is current, whether the overlay is shown), not
    how either looks -- DirectionA.md's visual intent was confirmed by
    rendering a real PNG and looking at it, not by this file.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def test_a_freshly_launched_window_shows_the_empty_state(self):
        w = self._window()
        self.assertIs(w._content_area.currentWidget(), w._empty_state)

    def test_connecting_keeps_the_page_content_not_the_empty_state(self):
        # A controller IS present once connected, even before a read
        # confirms anything -- only "no controller at all" shows the
        # empty state (see _refresh_content_area()'s own comment).
        w = self._window()
        w.set_connection_state("connected")
        self.assertIs(w._content_area.currentWidget(), w._pages_with_hatch)

    def test_a_confirmed_read_shows_the_page_content(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "ok", state_mod.default_state_dict("t"))
        self.assertIs(w._content_area.currentWidget(), w._pages_with_hatch)

    def test_disconnecting_again_without_ever_confirming_restores_the_empty_state(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_connection_state("disconnected")
        self.assertIs(w._content_area.currentWidget(), w._empty_state)

    def test_hatch_is_visible_on_a_freshly_launched_window(self):
        w = self._window()
        self.assertFalse(w._hatch_overlay.isHidden())

    def test_hatch_reappears_instantly_on_a_profile_switch(self):
        w = self._window()
        w.set_connection_state("connected")
        w.set_read_finished(True, "ok", state_mod.default_state_dict("t"))
        w.rail.profile_switch.set_value("2")
        self.assertFalse(w._hatch_overlay.isHidden())
        self.assertEqual(w._hatch_overlay._effect.opacity(), 1.0)

    def test_hatch_fades_out_on_a_confirmed_read(self):
        import time
        w = self._window()
        self.assertFalse(w._hatch_overlay.isHidden())
        w.set_connection_state("connected")
        w.set_read_finished(True, "ok", state_mod.default_state_dict("t"))
        self.assertFalse(w._hatch_overlay.isHidden(), "still fading immediately after")
        deadline = time.time() + 0.6
        while time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertTrue(w._hatch_overlay.isHidden(), "must be hidden once the reveal finishes")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ConnectionAlarmTest(unittest.TestCase):
    """CRITIC.md #7's accepted-but-unwired finding, wired up: a
    connection-level error (lost connection, a USB error -- anything that
    reaches set_error(), as opposed to a Sync/Read failure, which already
    gets its own QMessageBox) shows as an alarm InlineNotice directly
    beneath the ownership bar, not just the quiet status-bar text label.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def test_starts_hidden(self):
        w = self._window()
        self.assertTrue(w._connection_alarm.isHidden())

    def test_an_error_shows_the_alarm_with_the_message(self):
        w = self._window()
        w.set_error("Lost connection: timed out")
        self.assertFalse(w._connection_alarm.isHidden())
        self.assertEqual(w._connection_alarm.text_label.text(), "Lost connection: timed out")
        # The quieter status-bar label still carries the same message too.
        self.assertEqual(w.error_label.text(), "Lost connection: timed out")

    def test_a_successful_reconnect_clears_and_hides_it(self):
        w = self._window()
        w.set_error("USB error: no such device")
        w.set_connection_state("connected")
        self.assertTrue(w._connection_alarm.isHidden())
        self.assertEqual(w.error_label.text(), "")

    def test_clearing_with_an_empty_message_hides_it(self):
        w = self._window()
        w.set_error("something went wrong")
        w.set_error("")
        self.assertTrue(w._connection_alarm.isHidden())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class PaletteWiringTest(unittest.TestCase):
    """Real bug, found in A6's code review (2026-10-22): _on_palette_changed()
    refreshed sticks_view/triggers_view/_hatch_overlay on a live theme
    switch, but never rail or _connection_alarm -- both baked-pixmap-icon
    widgets with their own set_palette() now, but nothing was calling
    them.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def test_a_palette_change_reaches_the_rail_and_the_connection_alarm(self):
        from g7ctlc.palette import LIGHT_PALETTE
        w = self._window()
        before = [
            w.rail.read_button.icon().cacheKey(),
            w._connection_alarm._icon_label.pixmap().cacheKey(),
        ]
        w._on_palette_changed(LIGHT_PALETTE)
        after = [
            w.rail.read_button.icon().cacheKey(),
            w._connection_alarm._icon_label.pixmap().cacheKey(),
        ]
        for b, a in zip(before, after):
            self.assertNotEqual(b, a, "an icon did not change for a different palette")

    def test_a_palette_change_reaches_the_buttons_diagram(self):
        from g7ctlc.palette import LIGHT_PALETTE
        w = self._window()
        before = w.buttons_view.diagram._palette
        w._on_palette_changed(LIGHT_PALETTE)
        self.assertIsNot(w.buttons_view.diagram._palette, before)
        self.assertIs(w.buttons_view.diagram._palette, LIGHT_PALETTE)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class LaunchPageTest(unittest.TestCase):
    """The stacked pages and the rail's default-checked entry are set in
    separate places, so a fresh window must land on Buttons in both."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_buttons_is_the_page_shown_on_launch(self):
        from g7ctlc.main_window import MainWindow
        w = MainWindow()
        self.assertIs(w.pages.currentWidget(), w.buttons_view)
        self.assertEqual(w.rail.current_page(), "buttons")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ShiftLayerHasItsOwnFileTest(unittest.TestCase):
    """The Shift layer is one table shared by all four profiles, so a snapshot
    of one profile must not carry it: importing that snapshot and pressing
    Sync Now would rewrite the Shift layer for every profile. Game-profile
    Export/Import leave it alone; Export/Import Shared Profile move only it.
    (Reported as g7ctl PR #2 by w33tti, against the pre-0.4.0 window.)
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _path(self, name):
        return os.path.join(self._tmp.name, name)

    def _window(self):
        from g7ctlc.main_window import MainWindow
        w = MainWindow()
        w.set_connection_state("connected")
        read = state_mod.default_state_dict("read")
        read["buttons"]["shift"] = {"a": "f12", "l4": "shift"}
        w.set_read_finished(True, "read ok", read)
        return w

    def _write_json(self, name, payload):
        import json
        path = self._path(name)
        with open(path, "w") as f:
            json.dump(payload, f)
        return path

    def _export_game(self, w, name="game.json"):
        path = self._path(name)
        with mock.patch("g7ctlc.main_window.QFileDialog.getSaveFileName", return_value=(path, "")):
            w._on_export()
        return path

    def _import_game(self, w, path):
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName", return_value=(path, "")):
            w._on_import()

    def _import_shared(self, w, path):
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName", return_value=(path, "")):
            w._on_import_shared_profile()

    def _snapshot_with_shift(self, shift):
        snap = state_mod.default_state_dict("snapshot")
        snap["buttons"]["default"]["b"] = "f11"
        snap["buttons"]["shift"] = shift
        return snap

    def test_game_export_has_no_shift_layer_and_leaves_the_live_one_alone(self):
        import json
        w = self._window()
        path = self._export_game(w)
        with open(path) as f:
            exported = json.load(f)
        self.assertEqual(exported["buttons"]["shift"], {})
        self.assertEqual(w._state["buttons"]["shift"], {"a": "f12", "l4": "shift"})

    def test_game_import_keeps_the_controllers_shift_layer(self):
        w = self._window()
        path = self._write_json("old.json", self._snapshot_with_shift({"a": "f1"}))
        self._import_game(w, path)
        self.assertEqual(w._state["buttons"]["default"]["b"], "f11")
        self.assertEqual(w._state["buttons"]["shift"], {"a": "f12", "l4": "shift"})

    def test_game_import_says_when_it_ignored_a_shift_layer(self):
        w = self._window()
        self._import_game(w, self._write_json("old.json", self._snapshot_with_shift({"a": "f1"})))
        self.assertIn("Shift layer was ignored", w.status_label.text())
        self._import_game(w, self._write_json("new.json", self._snapshot_with_shift({})))
        self.assertNotIn("ignored", w.status_label.text())

    def test_a_game_import_never_plans_a_shift_write(self):
        # The regression this class exists for, end to end: a snapshot whose
        # Shift layer disagrees with the controller's must not turn into a
        # Shift write when the imported state is synced.
        w = self._window()
        device = copy_of_state(w._state)
        self._import_game(w, self._write_json("old.json", self._snapshot_with_shift({"a": "f1"})))
        steps, _skipped = state_mod._build_steps(w._state, baseline=device)
        self.assertEqual([label for label, _op in steps if "(shift)" in label], [])

    def test_shared_export_holds_only_the_shift_layer(self):
        import json
        w = self._window()
        path = self._path("shared.json")
        with mock.patch("g7ctlc.main_window.QFileDialog.getSaveFileName", return_value=(path, "")):
            w._on_export_shared_profile()
        with open(path) as f:
            exported = json.load(f)
        self.assertEqual(exported, {"format": "g7ctlc-shared-profile", "version": 1,
                                    "shift": {"a": "f12", "l4": "shift"}})

    def test_shared_import_changes_only_the_shift_layer(self):
        w = self._window()
        w._state["buttons"]["default"]["b"] = "f11"
        before = copy_of_state(w._state)
        path = self._write_json("shared.json", {
            "format": "g7ctlc-shared-profile", "version": 1, "shift": {"a": "f1"}})
        self._import_shared(w, path)
        expected = copy_of_state(before)
        expected["buttons"]["shift"] = {"a": "f1"}
        self.assertEqual(w._state, expected)
        self.assertTrue(w._dirty)
        self.assertTrue(w._state_imported)
        self.assertIn("not yet synced", w.status_label.text())

    def test_a_bad_shared_file_is_refused_and_changes_nothing(self):
        good = {"format": "g7ctlc-shared-profile", "version": 1, "shift": {}}
        cases = {
            "wrong format": dict(good, format="something-else"),
            "wrong version": dict(good, version=999),
            "shift not an object": dict(good, shift=["a"]),
            "unknown binding": dict(good, shift={"a": "definitely_not_a_keycode"}),
            "not an object": ["shift"],
        }
        for name, payload in cases.items():
            with self.subTest(name):
                w = self._window()
                before = copy_of_state(w._state)
                with mock.patch("g7ctlc.main_window.QMessageBox.critical") as critical:
                    self._import_shared(w, self._write_json("bad.json", payload))
                critical.assert_called_once()
                self.assertEqual(w._state, before)

    def test_a_shared_file_that_is_not_json_is_refused(self):
        w = self._window()
        before = copy_of_state(w._state)
        path = self._path("garbage.json")
        with open(path, "w") as f:
            f.write("not json")
        with mock.patch("g7ctlc.main_window.QMessageBox.critical") as critical:
            self._import_shared(w, path)
        critical.assert_called_once()
        self.assertEqual(w._state, before)

    def test_shared_import_and_export_wait_for_a_confirmed_state(self):
        w = self._window()
        w._state_confirmed = False
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName") as open_dialog, mock.patch(
            "g7ctlc.main_window.QFileDialog.getSaveFileName"
        ) as save_dialog, mock.patch("g7ctlc.main_window.QMessageBox.warning") as warning:
            w._on_import_shared_profile()
            w._on_export_shared_profile()
        self.assertEqual(warning.call_count, 2)
        open_dialog.assert_not_called()
        save_dialog.assert_not_called()

    def test_shared_import_and_export_do_nothing_mid_sync(self):
        w = self._window()
        original = w._state
        with mock.patch.object(w, "_confirm", return_value=True):
            w.request_sync_now()
        with mock.patch("g7ctlc.main_window.QFileDialog.getOpenFileName") as open_dialog, mock.patch(
            "g7ctlc.main_window.QFileDialog.getSaveFileName"
        ) as save_dialog:
            w._on_import_shared_profile()
            w._on_export_shared_profile()
        open_dialog.assert_not_called()
        save_dialog.assert_not_called()
        self.assertIs(w._state, original)


def copy_of_state(state):
    import copy
    return copy.deepcopy(state)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class WriteButtonsComeBackAfterAWriteTest(unittest.TestCase):
    """_lock_write_ui() greys out every scope's Write/Discard pair for the
    duration of a write, and only the scopes that were written used to get
    refreshed afterwards. A scope that was edited but not part of the write
    came back visible and permanently disabled (reported on Reddit
    2026-11-01: change Buttons and Motion, write Buttons, and Motion's Write
    button stays greyed out with a change still pending). Cancelling the
    review sheet left every scope that way.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        w = MainWindow()
        w._state["controller_slot"] = 2
        w._state["vibration"]["left_grip"] = 25
        w._state.setdefault("motion", {"aim": {}, "tilt": {}})
        w._state["motion"]["aim"]["sensitivity_scale"] = 50
        w._state_confirmed = True
        w._connection_state = "connected"
        w._reset_vibration_draft()
        w._reset_motion_draft()
        w.vibration_view.load_state(w._state)
        w.motion_view.load_state(w._state)
        w.vibration_view.sliders["left_grip"].set_value("75")
        w.motion_view.sides["aim"].sensitivity_scale.setValue(10)
        return w

    def test_an_unwritten_scope_can_still_be_written_after_another_scope_was(self):
        from pyg7.field_spec import VIBRATION_LEVEL_FIELDS
        from pyg7.workflow import ApprovedIntent, Classification, ExecutionResult, FieldOutcome, read_back
        w = self._window()
        w._on_write_vibration_clicked()
        self.assertFalse(w.motion_write_btn.isEnabled())  # locked while the write is in flight

        outcome = FieldOutcome(
            ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], 2),
            Classification.CLEAN, baseline_value=None, fresh_value=25)
        rb = read_back(ExecutionResult(job_id="t", executed=(outcome,)), {"vibration": {"left_grip": 75}})
        w.set_execute_finished(True, "Written.", rb)

        self.assertEqual(w._vibration_draft.edit_count, 0)
        self.assertEqual(w._motion_draft.edit_count, 1)
        self.assertTrue(w.motion_write_btn.isEnabled())
        self.assertTrue(w.motion_discard_btn.isEnabled())

    def test_every_scope_can_be_written_again_after_the_review_sheet_is_cancelled(self):
        from PyQt6.QtWidgets import QDialog

        from pyg7.workflow import DraftRevision, prepare
        w = self._window()
        w._on_write_vibration_clicked()
        job = prepare("t", DraftRevision("t", 1), 1, list(w._vibration_draft.to_approved_intents()),
                      baseline_state={"vibration": {"left_grip": 25}},
                      fresh_state={"vibration": {"left_grip": 25}})
        with mock.patch("g7ctlc.main_window.ReviewSheet") as sheet_cls:
            sheet_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            w.set_needs_review(job, {"vibration": {"left_grip": 25}})

        self.assertTrue(w.vibration_write_btn.isEnabled())
        self.assertTrue(w.motion_write_btn.isEnabled())
