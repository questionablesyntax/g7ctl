"""Main window: ownership bar, rail navigation, Import/Export, Sync Now,
Read from Device.

A3 of the redesign (`IMPLEMENTATION-PLAN.md` track A): the shell is new
(`OwnershipBar`, `Rail`, a `QStackedWidget` replacing the old
`QTabWidget`), but the confirmation/gating/race-fix logic below is
"re-wired to the new widgets, not redesigned" -- every method that used
to poke `self.tabs`/`self.profile_combo`/`self.import_export_btn` etc.
still exists with the same name and the same bug-fix history in its
comments; only which widget it reaches has changed. Pages themselves
(Buttons/Sticks/Triggers/Motion/Vibration/Dock) are still today's
un-reskinned views -- that's A4's job.
"""
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QByteArray, QEvent, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QHideEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyg7 import state as state_mod

from . import help_content
from .empty_state import EmptyState
from .hatch_overlay import HatchOverlay
from .inline_notice import InlineNotice
from .modal_overlay import ModalOverlayBase
from .ownership_bar import OwnershipBar
from .qss import generate_stylesheet
from .rail import PROFILE_PAGE_KEYS, SHARED_PAGE_KEYS, Rail
from .segmented_control import SegmentedControl
from .theme_runtime import ThemeController
from .views.buttons_view import ButtonsView
from .views.motion_view import MotionView
from .views.settings_view import SettingsView
from .views.sticks_view import SticksView
from .views.triggers_view import TriggersView
from .views.vibration_view import VibrationView

_GEOMETRY_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "window_geometry.dat"
)

# Sentinel for the Shift layer's rail entry. Deliberately not 5: the
# Shift layer is not a fifth profile, and anything that mistakes it for
# one would send profile=5 somewhere that expects 1-4.
SHIFT_VIEW = "shift"

_LEGACY_PROFILES_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "profiles"
)

# How long the window has to stay unfocused before the controller is handed
# back. Debounce, not politeness: a modal QMessageBox (the Sync Now / Read
# confirmations) deactivates its parent window, so releasing the instant
# focus drops would release the device exactly while the user is confirming
# a write. The delay plus the "is any window of ours active" check in
# _auto_release_if_still_unfocused() covers that, and stops a quick
# alt-tab-and-back from costing a full release/reconnect cycle.
_AUTO_RELEASE_DELAY_MS = 400


class MainWindow(QMainWindow):
    release_toggled = pyqtSignal(bool)  # True = release to XInput, False = reconnect
    sync_requested = pyqtSignal(dict)   # the state dict to push to the device
    # the controller_slot to read bindings back from, and whether to force a
    # real dock-settings read regardless of DeviceWatcher's own _dock_known
    # optimization -- see request_read_from_device()'s own comment.
    read_requested = pyqtSignal(int, bool)
    # Emitted every time self._syncing changes -- so anything outside this
    # class (the tray icon's own Release Device action, currently) can stay
    # in step without reaching into a private attribute.
    syncing_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("G7 Control Center")
        self.resize(1120, 760)  # DIRECTION-A.md section 3's default shell size
        self._restore_geometry()

        self._theme = ThemeController(self)
        self._apply_stylesheet()
        self._theme.paletteChanged.connect(self._on_palette_changed)

        self._state = state_mod.default_state_dict("Current State")
        self._dirty = False
        self._connection_state = "disconnected"
        self._firmware = None
        self._active_profile = None
        self._syncing = False  # true while either a sync-to or read-from-device job is in flight
        # Set only when *we* released the device because the window lost
        # focus, so refocusing knows to reconnect. Kept distinct from the
        # Release Device button: an explicit release has to survive the
        # window being focused again, and this must never undo one.
        self._auto_released = False
        self._auto_release_timer = QTimer(self)
        self._auto_release_timer.setSingleShot(True)
        self._auto_release_timer.setInterval(_AUTO_RELEASE_DELAY_MS)
        self._auto_release_timer.timeout.connect(self._auto_release_if_still_unfocused)
        # True only once self._state has been confirmed against real hardware
        # (a successful Read from Device) or an explicit user Import -- never
        # true for the untouched default_state_dict() scaffold. Gates Sync
        # Now: without this, a freshly-launched app (or one where every read
        # attempt has failed) could push entirely untested blank Sticks/
        # Triggers/Vibration defaults straight to the device on an accidental
        # click, with no prior safety net -- exactly what happened once
        # already (2026-07-27) after ProfileStore's "always start from a
        # previously-synced real profile" guarantee was removed with nothing
        # in its place.
        self._state_confirmed = False
        self._loading_profile_switch = False
        self._loading_report_rate_combo = False
        # True only while the Shift layer's single screen is showing. The
        # only reliable source of this -- rail.profile_switch.value() ==
        # SHIFT_VIEW was tried and is wrong, since _select_shift_view()
        # actually sets that control to None (off-scale), not "shift": a
        # real bug found in A6's code review, 2026-10-22, that made the
        # Shift-layer sync warning never show and let a background read
        # silently re-check a numbered profile segment while Shift was
        # still on screen. Set once, in _apply_view(), the one place that
        # actually decides this.
        self._viewing_shift = False
        self.setWindowIcon(self._app_icon())

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_ownership_bar())
        outer.addWidget(self._build_connection_alarm())
        content_row = QHBoxLayout()
        content_row.setContentsMargins(14, 10, 14, 10)
        content_row.setSpacing(14)
        content_row.addWidget(self._build_rail())
        content_column = QVBoxLayout()
        content_column.setSpacing(8)
        content_column.addWidget(self._build_unconfirmed_banner())
        content_column.addWidget(self._build_content_area(), 1)
        content_column.addLayout(self._build_write_action_row())
        content_row.addLayout(content_column, 1)
        outer.addLayout(content_row, 1)
        outer.addLayout(self._build_status_bar())

        self._load_views_from_state()
        self._refresh_confirmed_display()

    def _app_icon(self):
        from .tray import _state_icon
        # Static regardless of connection state -- only the tray icon
        # reflects state with colour. Reuses the "disconnected" icon
        # rather than a dedicated static asset, so the taskbar entry
        # stays state-neutral (see tray.py's own TrayIcon).
        return _state_icon("icon_black.png")

    def _apply_stylesheet(self) -> None:
        # `QApplication.setStyleSheet()` re-polishes every existing
        # top-level widget on every call, regardless of whether the text
        # actually changed -- a real cost in the live app only once (there
        # is only ever one MainWindow), but a construction-count-squared
        # one in a test suite that builds a fresh MainWindow per test
        # without closing the last (every one of them reaching this same
        # code, same palette, same generated string). Found by timing
        # MainWindow() construction directly: 0.8s/1.7s/2.8s/4.2s... for
        # the 1st/2nd/3rd/4th instance in one process, climbing without
        # bound. Guarding on the generated text actually changing fixes
        # both: the hot path here is a no-op, and a real theme change
        # (different palette) still re-polishes exactly once.
        app = QApplication.instance()
        if app is None:
            return
        stylesheet = generate_stylesheet(self._theme.palette)
        if stylesheet != app.styleSheet():
            app.setStyleSheet(stylesheet)

    def _on_palette_changed(self, palette) -> None:
        self._apply_stylesheet()
        # CurveEditor paints directly with QPainter, not QSS (DESIGN-SPEC.md
        # 10.2 item 5) -- it needs this explicit repaint call on a theme
        # change, a regenerated stylesheet alone doesn't reach it.
        self.sticks_view.set_palette(palette)
        self.triggers_view.set_palette(palette)
        self._hatch_overlay.set_palette(palette)
        # Real bug, found in A6's code review (2026-10-22): rail and
        # _connection_alarm (InlineNotice) are the other baked-pixmap-icon
        # widgets this method missed entirely -- both had no set_palette()
        # to call until now (see each one's own docstring).
        self.rail.set_palette(palette)
        self._connection_alarm.set_palette(palette)

    @property
    def theme(self) -> ThemeController:
        """Public read path for app.py, which owns the tray icon -- a
        sibling of this window, not a child, so it needs this window's
        ThemeController from the outside rather than reaching into a
        private attribute."""
        return self._theme

    # --- Construction helpers ----------------------------------------------

    def _build_ownership_bar(self) -> QWidget:
        self.ownership_bar = OwnershipBar(self._theme.palette, self._theme.icons, self)
        self.ownership_bar.releaseRequested.connect(self._on_release_clicked)
        # Aliases: tests and the rest of this class reach these by the name
        # they've always had -- only where they physically live has moved.
        self.playability_label = self.ownership_bar.playability_label
        self.battery_label = self.ownership_bar.battery_label
        return self.ownership_bar

    def _build_connection_alarm(self) -> QWidget:
        """The alarm inline notice CRITIC.md #7 accepted but left unwired --
        DESIGN-SPEC.md 10.1 #7: "the bar stays Holding and an alarm inline
        notice sits directly beneath it", for a connection-level problem
        (lost connection, a USB error, an unreachable identity -- see
        watcher.py's own `_emit_error()` call sites) as distinct from an
        ordinary failed Sync/Read, which already gets its own blocking
        QMessageBox. error_label (the status bar's small text) stays as
        today's quieter, persistent record of the same message; this is
        the prominent one the bar's own docstring already pointed at.
        """
        self._connection_alarm = InlineNotice(
            "alarm", "", self._theme.palette, self._theme.icons, parent=self
        )
        self._connection_alarm.hide()
        return self._connection_alarm

    def _build_rail(self) -> QWidget:
        self.rail = Rail(self._theme.palette, self._theme.icons, self)
        self.rail.profileChanged.connect(self._on_profile_changed)
        self.rail.pageRequested.connect(self._on_page_requested)
        self.rail.readRequested.connect(lambda: self.request_read_from_device(force_dock_read=True))
        self.rail.importRequested.connect(self._on_import)
        self.rail.exportRequested.connect(self._on_export)
        self.rail.appPreferencesRequested.connect(self._on_app_preferences)
        self.rail.wire_help_menu(self._build_help_menu)
        # Aliases, same reasoning as the ownership bar above.
        self.read_btn = self.rail.read_button
        self.import_export_btn = self.rail.snapshots_button
        self.help_btn = self.rail.help_button
        return self.rail

    def _build_help_menu(self, menu) -> None:
        about_action = QAction("About", self)
        about_action.triggered.connect(self._on_about)
        menu.addAction(about_action)
        ondevice_action = QAction("On-Device Features", self)
        ondevice_action.setToolTip(
            "The controller's own button combos (profile switch, on-the-fly "
            "paddle remap, hair-trigger toggle, calibration) -- these work "
            "with no software at all."
        )
        ondevice_action.triggered.connect(self._on_ondevice_features)
        menu.addAction(ondevice_action)
        menu.addSeparator()
        report_issue_action = QAction("Report an Issue…", self)
        report_issue_action.triggered.connect(self._on_report_issue)
        menu.addAction(report_issue_action)

    def _build_unconfirmed_banner(self) -> QLabel:
        # Roadmap: "the GUI displays unread state as if it were real" -- a
        # freshly-launched window, or one where a read just failed, painted
        # default_state_dict()'s scaffold or the previous profile's real
        # values with nothing distinguishing them from a confirmed reading.
        # Sync Now being disabled was the only signal, and it is easy to
        # miss since nobody is trying to sync yet. This banner plus the
        # disabled-control styling from _refresh_confirmed_display() puts
        # the same fact where it can't be missed: on the values themselves.
        self.unconfirmed_banner = QLabel(
            "Not yet confirmed against the device -- these are placeholder "
            "values. Read from Device once connected."
        )
        self.unconfirmed_banner.setProperty("role", "caution")
        return self.unconfirmed_banner

    def _build_pages(self) -> QStackedWidget:
        """One stacked page per rail nav entry. Settings is last and
        deliberately apart from the rest: everything before it is
        per-profile, while the dock settings it holds are device-wide.
        """
        self.pages = QStackedWidget()
        self.buttons_view = ButtonsView()
        self.sticks_view = SticksView(self._theme.palette)
        self.triggers_view = TriggersView(self._theme.palette)
        self.motion_view = MotionView()
        self.vibration_view = VibrationView()
        self.settings_view = SettingsView()  # Dock, device-wide
        self._profile_settings_page = self._build_profile_settings_page()
        self._page_widgets = {
            "buttons": self.buttons_view,
            "sticks": self.sticks_view,
            "triggers": self.triggers_view,
            "motion": self.motion_view,
            "vibration": self.vibration_view,
            "profile_settings": self._profile_settings_page,
            "shift": self.buttons_view,  # same widget, set_layer("shift") below
            "dock": self.settings_view,
        }
        for key in (*PROFILE_PAGE_KEYS, *SHARED_PAGE_KEYS):
            widget = self._page_widgets[key]
            if self.pages.indexOf(widget) < 0:
                self.pages.addWidget(widget)
            # buttons_view/_profile_settings_page wire their own dirty
            # signal elsewhere (buttons_view.changed below; report rate's
            # combo is a plain QComboBox with no `changed` signal of its
            # own, wired straight to _on_report_rate_changed instead).
            if widget in (self.buttons_view, self._profile_settings_page):
                continue
            widget.changed.connect(self._on_dirty)
        self.buttons_view.changed.connect(self._on_dirty)
        return self.pages

    def _build_content_area(self) -> QStackedWidget:
        """Wraps self.pages with the "no controller" EmptyState
        (DIRECTION-A.md section 5's component inventory) and the unread
        HatchOverlay (section 6's "unread to read reveal"), A5 of the
        redesign. self.pages itself is unchanged by this -- still built,
        still addressable, still what every page-navigation method and
        test reaches into; only what MainWindow shows on top of it is new.

        The hatch sits over self.pages only, not the EmptyState -- unread
        placeholder data and "there is no data, nothing is connected" are
        different facts, and hatching the empty state would muddy an
        already-honest "nothing here" screen.
        """
        self._content_area = QStackedWidget()

        # setCurrentWidget() below needs this wrapper, not self.pages --
        # self.pages is only an indirect child now (nested inside its own
        # QStackedLayout alongside the hatch), not a direct child of
        # self._content_area the way addWidget() would need to find it.
        self._pages_with_hatch = QWidget()
        pages_stack = QStackedLayout(self._pages_with_hatch)
        pages_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        pages_stack.addWidget(self._build_pages())
        self._hatch_overlay = HatchOverlay(self._theme.palette)
        pages_stack.addWidget(self._hatch_overlay)
        self._content_area.addWidget(self._pages_with_hatch)

        self._empty_state = EmptyState(
            "No controller connected",
            "Connect a GameSir G7 Pro to configure it. "
            "Already connected? It may still be enumerating.",
            self._theme.fonts,
        )
        self._content_area.addWidget(self._empty_state)
        return self._content_area

    def _refresh_content_area(self) -> None:
        """Shows the EmptyState in place of the page content only when
        there is genuinely nothing to show yet -- no controller at all,
        and nothing ever confirmed. Connecting (a controller IS present,
        a read is imminent) and an already-confirmed reading both keep
        showing today's page content, just as before this phase."""
        show_empty = self._connection_state in ("disconnected", "no_controller") and not self._state_confirmed
        self._content_area.setCurrentWidget(self._empty_state if show_empty else self._pages_with_hatch)
        # The empty state already says "no controller" on its own --
        # the unconfirmed banner on top of it would just repeat that.
        if show_empty:
            self.unconfirmed_banner.setVisible(False)

    def _build_profile_settings_page(self) -> QWidget:
        """Report rate, CRITIC.md #9's fix: it had no rail home at all
        before (built into the old top selector bar, outside self.tabs
        entirely -- the exact structural gap that let it slip through
        _refresh_confirmed_display()'s QScrollArea sweep, a code review
        2026-09-17). Wrapped in a QScrollArea like every other page, so it
        is now reached by that same generic sweep instead of needing its
        own special-cased line.
        """
        content = QWidget()
        form = QFormLayout(content)
        # A3-style SegmentedControl, A4's re-skin -- "report_rate_combo"
        # keeps its pre-redesign name (MainWindow/tests address it that
        # way; same precedent as VibrationView's `sliders`), not because
        # it's still a QComboBox.
        self.report_rate_combo = SegmentedControl([(str(hz), f"{hz} Hz") for hz in (250, 500, 1000)])
        self.report_rate_combo.setToolTip(
            "Per-profile polling rate. Note: GameSir Nexus disables native "
            "trigger vibration when this is set to 1000 Hz -- likely a real "
            "bandwidth constraint, not a bug."
        )
        # Display default, signals blocked -- see sticks_view.py's
        # SegmentedControl off-scale fix for why a fresh control needs one.
        self.report_rate_combo.blockSignals(True)
        self.report_rate_combo.set_value("1000")
        self.report_rate_combo.blockSignals(False)
        self.report_rate_combo.selectionChanged.connect(self._on_report_rate_changed)
        form.addRow("Report Rate:", self.report_rate_combo)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _build_write_action_row(self) -> QHBoxLayout:
        """Sync Now: the one control in wave 1 that actually writes to the
        controller, so -- per CRITIC.md #1's closed list -- it is the one
        non-rail, non-live use of the signal colour. Occupies the same row
        wave 2's DraftBar lands in later; this phase keeps today's direct
        confirm-then-write contract (DESIGN-SPEC.md 10.2 item 1), just
        restyled.
        """
        row = QHBoxLayout()
        row.addStretch(1)
        self.sync_btn = QPushButton("Sync Now")
        self.sync_btn.setProperty("role", "write")
        self.sync_btn.setEnabled(False)
        self.sync_btn.setToolTip(
            "Push the current state to the connected controller. Disabled "
            "until the state has been confirmed against real hardware, via "
            "a successful Read from Device or an explicit Import."
        )
        self.sync_btn.clicked.connect(self.request_sync_now)
        row.addWidget(self.sync_btn)
        return row

    def _build_status_bar(self) -> QHBoxLayout:
        """Job progress and local errors -- connection state, battery and
        release now live in the ownership bar instead.

        Three separate labels rather than one shared message area, so a
        sync progress update can't wipe out an error the user hasn't read.
        """
        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 4, 14, 8)
        bottom.setSpacing(12)
        self.error_label = QLabel("")
        self.error_label.setProperty("role", "alarm")
        bottom.addWidget(self.error_label)
        bottom.addStretch(1)
        self.sync_status_label = QLabel("")
        self.sync_status_label.setProperty("role", "muted")
        bottom.addWidget(self.sync_status_label)
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "muted")
        bottom.addWidget(self.status_label)
        return bottom

    def set_battery(self, percent: int, charging: bool) -> None:
        """Show a charge reading. Called on the GUI thread via a queued
        connection from DeviceWatcher.battery_changed."""
        self.ownership_bar.set_battery(percent, charging)

    def set_active_profile(self, slot: int) -> None:
        """Mark which profile the controller is physically using.

        The rail's switch chooses what you *edit*; this shows what you are
        *playing*. They are independent -- every category targets a
        profile explicitly, so editing Profile 2 while playing Profile 1
        works correctly.
        """
        self._active_profile = slot
        self.rail.set_active_profile(slot)

    def set_firmware(self, version: str) -> None:
        """Record the controller's firmware version, read once per
        connection -- goes in the ownership bar's tooltip, reference
        information someone looks up when filing a bug, not something
        worth spending bar width on every session."""
        self._firmware = version
        self.ownership_bar.set_firmware_tooltip(f"Controller firmware v{version}")

    def clear_battery(self) -> None:
        """No reading available -- hide rather than show a stale number."""
        self.ownership_bar.clear_battery()

    # --- Window geometry ----------------------------------------------------

    def _restore_geometry(self) -> None:
        try:
            data = _GEOMETRY_PATH.read_bytes()
        except OSError:
            return
        self.restoreGeometry(QByteArray(data))

    def save_geometry(self) -> None:
        """Persist window position/size so it's remembered across both
        hide/show (tray minimize) and full app restarts. Called from
        closeEvent (covers the tray-app "close = hide" path) and from
        app.py's aboutToQuit (redundant safety net for other quit paths)."""
        try:
            _GEOMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _GEOMETRY_PATH.write_bytes(bytes(self.saveGeometry()))
        except OSError:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_geometry()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        """Hand the controller back while the window isn't focused.

        Holding the device keeps its gamepad interface claimed, detaching
        the kernel driver -- so tabbing away to actually play would
        otherwise find a dead controller until Release Device was clicked
        by hand. GameSir Nexus releases on unfocus for the same reason.
        Hiding to the tray deactivates the window too, so that path is
        covered by this one.
        """
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow() and self.isVisible():
                self._auto_release_timer.stop()
                self._reconnect_after_auto_release()
            else:
                self._auto_release_timer.start()
        super().changeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        """Closing to the tray releases too.

        Hooked directly rather than left to changeEvent: whether a window
        being hidden gets an ActivationChange at all is platform-dependent
        (it does under the offscreen platform these tests run on, it does
        not reliably under a real compositor), and closing the window is a
        clearer "I'm done with it" than losing focus is.
        """
        self._auto_release_timer.start()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        """Counterpart to hideEvent -- coming back from the tray reconnects
        without waiting to also be activated, for the same reason."""
        self._auto_release_timer.stop()
        self._reconnect_after_auto_release()
        super().showEvent(event)

    def _auto_release_if_still_unfocused(self) -> None:
        if self.isActiveWindow() or QApplication.activeWindow() is not None:
            # Focus came back, or it only ever went to one of our own windows
            # -- a modal confirmation dialog, not the user leaving.
            return
        if self._connection_state != "connected":
            return
        if self._syncing:
            # Mid sync-to or read-from-device. Dropping the session here
            # would abort a write to persistent device config, so wait and
            # re-check rather than skipping the release entirely.
            self._auto_release_timer.start()
            return
        self._auto_released = True
        self.release_toggled.emit(True)

    def _reconnect_after_auto_release(self) -> None:
        """Only undoes this class's own release -- an explicit Release Device
        leaves _auto_released false, so refocusing won't silently reconnect.
        See set_connection_state() for the other half of this fix (self-
        correcting a too-fast refocus).
        """
        if not self._auto_released or self._connection_state != "paused":
            return
        self._auto_released = False
        self.release_toggled.emit(False)

    def set_connection_state(self, state: str) -> None:
        self.ownership_bar.set_state(state)
        was_connected = self._connection_state == "connected"
        self._connection_state = state
        if state == "connected":
            self.ownership_bar.set_release_enabled(not self._syncing)
            self._refresh_sync_btn()
            self.rail.read_button.setEnabled(not self._syncing)
            self.set_error("")  # a successful (re)connect supersedes any earlier error
            if not was_connected:
                self._auto_read_on_connect()
        elif state == "paused":
            self.ownership_bar.set_release_enabled(True)
            self.sync_btn.setEnabled(False)
            self.rail.read_button.setEnabled(False)
            # If a focus event already tried to undo an auto-release before
            # this "paused" confirmation arrived (see
            # _reconnect_after_auto_release()'s own comment), don't wait
            # for another focus change to notice -- act on it now that
            # _connection_state has actually caught up.
            self._reconnect_after_auto_release()
        else:
            self.ownership_bar.set_release_enabled(False)
            self.sync_btn.setEnabled(False)
            self.rail.read_button.setEnabled(False)
        self._refresh_content_area()

    def set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self._connection_alarm.set_text(message)
        self._connection_alarm.setVisible(bool(message))

    def _confirm(self, title: str, text: str) -> bool:
        """One seam for every "are you sure" prompt in this window -- a
        thin wrapper, not inlined at each call site, so a test can
        monkeypatch just this method instead of dealing with a real blocking
        modal dialog."""
        reply = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _sync_allowed(self) -> bool:
        return (self._connection_state == "connected" and not self._syncing
                and self._state_confirmed)

    def _refresh_sync_btn(self) -> None:
        self.sync_btn.setEnabled(self._sync_allowed())

    def _refresh_confirmed_display(self) -> None:
        """Make an unconfirmed self._state look inert, not just un-syncable.

        Disables every QScrollArea's *contained widget*, not self.pages and
        not the QScrollAreas themselves -- Qt's disabled state cascades
        downward with no way for a child to opt back out (confirmed: a
        QScrollArea explicitly re-enabled still reports its own scrollbar
        as disabled if any ancestor is disabled), so disabling self.pages
        directly would take the scrollbars down with every actual control.
        Scrolling and switching pages are navigation, not an edit -- a user
        should be able to look at an unconfirmed page's full content
        without that being mistaken for permission to change it. Every
        category view wraps its real content in a QScrollArea (see
        TriggersView/VibrationView/SettingsView's own comments, and
        _build_profile_settings_page() above for report rate's), so this
        still reaches every control with one flag, not a per-view "is this
        real" plumbing job.

        Must be called every time self._state_confirmed OR self._syncing
        changes: on construction, after every read attempt (success or
        failure), on Import, on a profile switch (whose value it turns
        False again -- see _on_profile_changed for why that has to happen
        even before the resulting read comes back), and around every
        sync-to/read-from-device job.
        """
        editable = self._state_confirmed and not self._syncing
        for scroll in self.pages.findChildren(QScrollArea):
            content = scroll.widget()
            if content is not None:
                content.setEnabled(editable)
        self.unconfirmed_banner.setVisible(not self._state_confirmed)
        self._hatch_overlay.set_unread(not self._state_confirmed)
        self._refresh_content_area()

    def _on_release_clicked(self) -> None:
        self.release_toggled.emit(self._connection_state != "paused")

    def _auto_read_on_connect(self) -> None:
        """Pull live state from the device the moment we (re)connect, so the
        GUI never sits there showing stale in-memory state while the real
        device has since changed (e.g. edited via GameSir Nexus). Skipped
        if there are unsynced local edits -- an automatic read would otherwise
        silently discard them; the user can still hit "Read from Device" by
        hand to discard on purpose."""
        if self._dirty:
            self.sync_status_label.setText(
                "Connected -- pending changes not synced; Sync Now or "
                "Read from Device to discard them."
            )
            return
        self.request_read_from_device()

    def request_sync_now(self) -> None:
        if not self._sync_allowed():
            return
        slot = self._state.get("controller_slot") or 1
        if self._viewing_shift:
            message = ("Push the current settings to the connected controller? The Shift "
                       f"layer is shared by all four profiles, so this changes it for every "
                       f"profile — and anything else edited since the last sync still goes to "
                       f"Profile {slot}.")
        else:
            message = (f"Push the current settings to Profile {slot} on the connected "
                       "controller? This overwrites that profile's stored settings.")
        if not self._confirm("Sync to controller?", message):
            return
        self._syncing = True
        self.syncing_changed.emit(True)
        self.sync_btn.setEnabled(False)
        self.rail.read_button.setEnabled(False)
        self.rail.set_nav_enabled(False)
        self.ownership_bar.set_release_enabled(False)
        # Real gap, found 2026-09-01: Import/Export were never gated on
        # _syncing at all, unlike every other state-affecting control here.
        # Export reads self._state while the watcher thread is iterating
        # that same dict object mid-sync (see _refresh_confirmed_display()'s
        # docstring); Import replaces self._state outright, so a sync that
        # finishes after an Import lands calls set_sync_finished() -> the
        # dirty flag clears as if the *imported* state had just been synced,
        # when the device actually still holds whatever was pushed before
        # the import.
        self.import_export_btn.setEnabled(False)
        self._refresh_confirmed_display()  # locks every page for the duration
        self.sync_status_label.setText("Syncing…")
        self.sync_requested.emit(self._state)

    def set_sync_progress(self, step: int, total: int, label: str) -> None:
        if total == 0:
            self.sync_status_label.setText(label)  # e.g. "Reading current device state…", no step count yet
        else:
            self.sync_status_label.setText(f"Syncing ({step}/{total}): {label}")

    def set_sync_finished(self, success: bool, message: str) -> None:
        self._syncing = False
        self.syncing_changed.emit(False)
        self.sync_status_label.setText(message)
        self._refresh_sync_btn()
        self._refresh_confirmed_display()  # unlocks the pages request_sync_now() locked
        self.rail.read_button.setEnabled(self._connection_state == "connected")
        self.ownership_bar.set_release_enabled(self._connection_state == "connected")
        self.rail.set_nav_enabled(True)
        self.import_export_btn.setEnabled(True)
        if success:
            self._set_dirty(False)  # the device now matches what we just pushed
        else:
            QMessageBox.warning(self, "Sync failed", message)

    def request_read_from_device(self, force_dock_read: bool = False) -> None:
        """`force_dock_read`: DeviceWatcher skips the dock-settings blob
        after the first read per connection (a real, deliberate
        optimization -- dock settings don't change mid-connection). That's
        fine for the automatic callers below (profile switch, auto-read-
        on-connect), but the explicit "Read from controller" BUTTON's
        whole promised contract is "discard my edits, show me the
        controller's actual truth". Only the button's own connection
        passes True; both automatic callers keep the optimization.
        """
        if self._connection_state != "connected" or self._syncing:
            return
        if self._dirty and not self._confirm(
            "Discard unsynced changes?",
            "Reading from the device will overwrite unsaved edits in every "
            "page with the controller's actual current settings. Continue?",
        ):
            return
        self._syncing = True
        self.syncing_changed.emit(True)
        self.sync_btn.setEnabled(False)
        self.rail.read_button.setEnabled(False)
        self.rail.set_nav_enabled(False)
        self.ownership_bar.set_release_enabled(False)  # same reasoning as request_sync_now()
        self.import_export_btn.setEnabled(False)  # same reasoning as request_sync_now()
        self._refresh_confirmed_display()  # locks every page for the duration
        self.sync_status_label.setText("Reading from device…")
        slot = self._state.get("controller_slot") or 1
        self.read_requested.emit(slot, force_dock_read)

    def set_read_finished(self, success: bool, message: str, device_state: Optional[dict]) -> None:
        self._syncing = False
        self.syncing_changed.emit(False)
        self.sync_status_label.setText(message)
        if success and device_state is not None:
            self._state_confirmed = True
        self._refresh_sync_btn()
        self._refresh_confirmed_display()
        self.rail.read_button.setEnabled(self._connection_state == "connected")
        self.ownership_bar.set_release_enabled(self._connection_state == "connected")
        self.rail.set_nav_enabled(True)
        self.import_export_btn.setEnabled(True)
        if not success or device_state is None:
            if not success:
                QMessageBox.warning(self, "Read from device failed", message)
            return
        # Merge key-by-key rather than replacing the layer dict wholesale --
        # read_state() coverage isn't exhaustive, so replace-the-whole-dict
        # isn't safe to bet user data on.
        for layer in ("default", "shift"):
            self._state["buttons"].setdefault(layer, {}).update(device_state["buttons"].get(layer, {}))
        self._state["dpad_diagonal_lock"] = device_state["dpad_diagonal_lock"]
        self._state["swap_stick_dpad"] = device_state["swap_stick_dpad"]
        # Continuous Trigger. Must land BEFORE the Buttons view repaints on
        # the next line, or the checkboxes are painted from the previous
        # state and the device's values arrive too late to show. Replaced
        # wholesale, not merged: decode_continuous_triggers() returns every
        # button-table slot on every read.
        self._state["continuous_trigger"] = device_state.get("continuous_trigger", {})
        self.buttons_view.load_state(self._state)

        self._state["sticks"] = device_state["sticks"]
        self._state["triggers"] = device_state["triggers"]
        self._state["motion"] = device_state["motion"]
        self._state["vibration"] = device_state["vibration"]
        self._state["report_rate_hz"] = device_state["report_rate_hz"]
        # None means "not read this call" (the watcher skips this
        # device-global blob after the first read per connection), not
        # "read back empty" -- keep whatever value is already showing.
        if device_state["dock_led_brightness"] is not None:
            self._state["dock_led_brightness"] = device_state["dock_led_brightness"]
        if device_state["dock_auto_on_off"] is not None:
            self._state["dock_auto_on_off"] = device_state["dock_auto_on_off"]
        self._sync_report_rate_combo()
        self.sticks_view.load_state(self._state)
        self.triggers_view.load_state(self._state)
        self.motion_view.load_state(self._state)
        self.vibration_view.load_state(self._state)
        self.settings_view.load_state(self._state)

        self._set_dirty(False)  # local state now matches the device, not a pending change

    def _load_views_from_state(self) -> None:
        self._sync_profile_switch()
        self._sync_report_rate_combo()
        self.buttons_view.load_state(self._state)
        self.sticks_view.load_state(self._state)
        self.triggers_view.load_state(self._state)
        self.motion_view.load_state(self._state)
        self.vibration_view.load_state(self._state)
        self.settings_view.load_state(self._state)
        self._set_dirty(False)

    def _sync_profile_switch(self) -> None:
        """Reflect self._state["controller_slot"] in the rail switch without
        re-triggering _on_profile_changed (which would otherwise fire a
        redundant read/no-op write for a value that just came FROM state,
        not from the user picking a new one)."""
        if self._viewing_shift:
            # A read finishing must not yank the user out of the Shift view
            # back to whichever profile it happened to target. The Shift
            # layer came back with that read anyway -- it is global.
            return
        self._loading_profile_switch = True
        try:
            self.rail.set_profile(self._state.get("controller_slot") or 1)
        finally:
            self._loading_profile_switch = False

    def _on_profile_changed(self, slot: object) -> None:
        if self._loading_profile_switch:
            return
        self._apply_view(slot)
        self._state["controller_slot"] = slot
        # The values on screen right now were confirmed (if ever) against
        # whichever profile was selected before, not this one -- they say
        # nothing about this profile until a read of it succeeds. Clearing
        # here, not only on read failure, is what stops a failed OR declined
        # read from leaving the previous profile's real values on screen
        # looking exactly like a confirmed reading of the new selection.
        self._state_confirmed = False
        self._refresh_confirmed_display()
        self._refresh_sync_btn()
        if self._connection_state == "connected" and not self._syncing:
            self.request_read_from_device()

    def _on_page_requested(self, key: str) -> None:
        if key == "shift":
            self._select_shift_view()
            return
        if key == "buttons" and self._viewing_shift:
            # Both "buttons" and "shift" route to the same buttons_view
            # widget, so a plain setCurrentWidget() here was a no-op: the
            # rail's exclusive button group checks "Buttons" purely from
            # the click, but nothing told buttons_view to leave shift mode
            # or restored the profile switch -- real bug, found in A6's
            # code review, 2026-10-22. Treat it exactly like picking the
            # current profile, since that's genuinely what "Buttons" means
            # once you're not on Shift.
            self._apply_view(self._state.get("controller_slot") or 1)
            self._sync_profile_switch()
            return
        self.pages.setCurrentWidget(self._page_widgets[key])

    def _select_shift_view(self) -> None:
        """Choosing Shift never changes `controller_slot` -- it is one
        layer shared by all four profiles, not addressed by a profile
        number at all (see `_apply_view`'s own comment)."""
        self._apply_view(SHIFT_VIEW)
        self.rail.profile_switch.set_value(None)  # off-scale: Shift isn't one of the 4 slots

    def _apply_view(self, selected) -> None:
        """Show the Shift layer's single screen, or the full per-profile
        set. The Shift blob carries stick/trigger/vibration bytes only
        because every one of the five blobs shares a 480-byte layout --
        their values are plain factory defaults and Nexus never exposes
        them, and nothing can write them (the Sticks/Triggers/Vibration/
        Report Rate prefixes carry a plain profile number, and there is no
        profile number that addresses the Shift blob). So those rail
        entries are hidden here rather than shown and quietly ignored --
        same behaviour as the old per-tab hiding this replaces, including
        hiding Dock, which is also shared/device-wide: not fixed here,
        A3 is layout only.
        """
        shift_view = selected == SHIFT_VIEW
        self._viewing_shift = shift_view
        self.buttons_view.set_layer("shift" if shift_view else "default")
        for key in PROFILE_PAGE_KEYS:
            if key == "buttons":
                continue  # Buttons stays reachable -- it's the Shift screen itself
            self.rail.set_page_visible(key, not shift_view)
        self.rail.set_page_visible("dock", not shift_view)
        if shift_view:
            self.rail.set_current_page("shift")
            self.pages.setCurrentWidget(self.buttons_view)
        else:
            self.rail.set_page_visible("shift", True)
            if self.rail.current_page() in ("shift",):
                self.rail.set_current_page("buttons")
                self.pages.setCurrentWidget(self.buttons_view)

    def _sync_report_rate_combo(self) -> None:
        """Reflect self._state["report_rate_hz"] in the control -- same
        loading-guard reasoning as _sync_profile_switch()."""
        self._loading_report_rate_combo = True
        try:
            hz = self._state.get("report_rate_hz") or 1000
            # Falls back to 1000 Hz -- default_state_dict()'s own confirmed
            # default, not just "whatever happens to be last."
            value = str(hz) if hz in (250, 500, 1000) else "1000"
            self.report_rate_combo.set_value(value)
        finally:
            self._loading_report_rate_combo = False

    def _on_report_rate_changed(self, value: object) -> None:
        if self._loading_report_rate_combo or value is None:
            return
        self._state["report_rate_hz"] = int(value)
        self._on_dirty()

    def _default_snapshot_dir(self) -> str:
        return str(_LEGACY_PROFILES_DIR if _LEGACY_PROFILES_DIR.is_dir() else Path.home())

    def _on_export(self) -> None:
        # Also guarded by import_export_btn being disabled during a sync/read
        # -- checked here too, same belt-and-suspenders reasoning as
        # request_read_from_device()'s own self._syncing check. self._state
        # is the exact dict object the watcher thread may be iterating
        # mid-sync; reading it concurrently here would be a data race.
        if self._syncing:
            return
        # Declining "Discard unsynced changes?" after picking a different
        # profile leaves self._state["controller_slot"] pointing at the
        # NEWLY selected profile while self._state itself still holds the
        # PREVIOUS profile's real, dirty values -- exactly the case
        # _state_confirmed=False exists to flag (see _on_profile_changed).
        if not self._state_confirmed:
            QMessageBox.warning(
                self, "Export unavailable",
                "The current settings haven't been confirmed against the controller "
                "(or an import) yet -- read from the device or import a snapshot first.",
            )
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export State", self._default_snapshot_dir(), "JSON files (*.json)",
        )
        if not path:
            return
        try:
            state_mod.save_state(path, self._state)
        except (state_mod.StateError, OSError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status_label.setText(f"Exported to {Path(path).name}")

    def _on_import(self) -> None:
        # Same guard as _on_export(): replacing self._state mid-sync would
        # leave the in-flight job's set_sync_finished()/set_read_finished()
        # clearing the dirty flag against the *imported* state once it
        # lands, as if the imported state -- not what was actually pushed
        # -- had just been synced.
        if self._syncing:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import State", self._default_snapshot_dir(), "JSON files (*.json)",
        )
        if not path:
            return
        try:
            imported = state_mod.load_state(path)
        except (state_mod.StateError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self._state = imported
        self._state_confirmed = True
        self._load_views_from_state()
        self._refresh_sync_btn()
        self._refresh_confirmed_display()
        self._set_dirty(True)
        self.status_label.setText(f"Imported {Path(path).name} -- not yet synced")

    # --- Help menu -----------------------------------------------------

    def _on_about(self) -> None:
        QMessageBox.about(self, "About G7 Control Center", help_content.ABOUT_HTML)

    def _on_ondevice_features(self) -> None:
        QMessageBox.information(self, "On-Device Features", help_content.ON_DEVICE_FEATURES_HTML)

    def _on_report_issue(self) -> None:
        QDesktopServices.openUrl(QUrl(help_content.ISSUES_URL))

    def _on_app_preferences(self) -> None:
        # Content is A4's job (DESIGN-SPEC.md section 3's decision table:
        # its own rail-footer entry, not under Help). This phase gives it
        # the entry and a real, honest placeholder rather than a dead
        # click or an invented "Reduce motion" checkbox that does nothing.
        dialog = ModalOverlayBase(self._theme.palette, self)
        dialog.setWindowTitle("App preferences")
        label = QLabel(
            "No preferences yet -- Reduce motion and other app-level "
            "settings land in a later phase.", dialog)
        label.setWordWrap(True)
        dialog.content_layout.addWidget(label)
        close_button = QPushButton("Close", dialog)
        close_button.clicked.connect(dialog.accept)
        dialog.content_layout.addWidget(close_button)
        dialog.exec()

    def _on_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self.status_label.setText("Unsynced changes")
        else:
            self.status_label.setText("")
