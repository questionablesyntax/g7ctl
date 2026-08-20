"""Main window: category tabs, Import/Export, Sync Now, Read from Device."""
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QByteArray, QEvent, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QHideEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pyg7 import state as state_mod

from . import help_content
from .tray import _state_icon
from .views.buttons_view import ButtonsView
from .views.motion_view import MotionView
from .views.settings_view import SettingsView
from .views.sticks_view import SticksView
from .views.triggers_view import TriggersView
from .views.vibration_view import VibrationView

# The window/taskbar icon is static regardless of connection state -- only
# the tray icon (see tray.py's TrayIcon) reflects state with color. A
# per-state window icon was tried and reverted (2026-07-29): distracting in
# the title bar/taskbar, which users expect to stay constant for an app.
# Reuses the "disconnected" icon (icon_black.png) rather than a dedicated
# static asset, so the launcher/taskbar entry stays state-neutral.
_APP_ICON_FILE = "icon_black.png"

_GEOMETRY_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "window_geometry.dat"
)

# Old ProfileStore-managed profiles lived here -- kept only as a friendly
# default starting directory for the Export/Import file dialogs, so existing
# users land somewhere with their old profile JSONs still importable (same
# schema, no migration needed).
# Sentinel for the profile combo's Shift entry. Deliberately not 5: the
# Shift layer is not a fifth profile, and anything that mistakes it for one
# would send profile=5 somewhere that expects 1-4.
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
    read_requested = pyqtSignal(int)    # the controller_slot to read bindings back from

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("G7 Control Center")
        self.setWindowIcon(_state_icon(_APP_ICON_FILE))
        self.resize(760, 640)
        self._restore_geometry()

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
        self._loading_profile_combo = False
        self._loading_report_rate_combo = False

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(14, 12, 14, 10)
        outer.setSpacing(10)

        # Four horizontal bands, top to bottom: what you're editing, the
        # editor itself, what you can do with it, and what the device is
        # currently doing. Each is built by its own method below so this
        # constructor reads as that layout rather than as 110 lines of
        # widget plumbing.
        outer.addLayout(self._build_selector_bar())
        outer.addWidget(self._build_tabs(), 1)
        outer.addLayout(self._build_action_bar())
        outer.addLayout(self._build_status_bar())

        self._load_views_from_state()
        self._refresh_confirmed_display()

    # --- Construction helpers ----------------------------------------------
    #
    # Each returns the layout/widget it built and assigns any widget the rest
    # of the class needs to reach later to self.

    def _build_selector_bar(self) -> QHBoxLayout:
        """Profile slot + report rate: what the tabs below are editing."""
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        for slot in (1, 2, 3, 4):
            self.profile_combo.addItem(f"Profile {slot}", slot)
        # The Shift layer sits here as a peer of the four profiles because
        # that is what it is on the device: five config blobs, 0x01-0x05,
        # which GameSir Nexus also reads as peers. It is NOT a fifth profile
        # -- it is one layer shared by all four, so it gets its own entry
        # rather than a column inside a per-profile screen, where it used to
        # imply a per-profile scope it does not have.
        self.profile_combo.addItem("Shift Layer (shared)", SHIFT_VIEW)
        self.profile_combo.setToolTip(
            "Which of the controller's 4 onboard profile slots to read from / "
            "sync to. Buttons, Sticks, Triggers, Vibration and Report Rate are "
            "each independently profile-scoped.\n\n"
            "\"Shift Layer (shared)\" is not a fifth profile: the controller "
            "has ONE Shift layer, used by all four profiles. Editing it there "
            "changes it everywhere.\n\n"
            "\"(in use)\" marks the profile the controller is physically on. "
            "You can read and write any of them regardless -- the two are "
            "independent."
        )
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)
        self.report_rate_label = QLabel("Report Rate:")
        top.addWidget(self.report_rate_label)
        self.report_rate_combo = QComboBox()
        for hz in (250, 500, 1000):
            self.report_rate_combo.addItem(f"{hz} Hz", hz)
        self.report_rate_combo.setToolTip(
            "Per-profile polling rate. Note: GameSir Nexus disables native "
            "trigger vibration when this is set to 1000 Hz -- likely a real "
            "bandwidth constraint, not a bug."
        )
        self.report_rate_combo.currentIndexChanged.connect(self._on_report_rate_changed)
        top.addWidget(self.report_rate_combo)
        top.addStretch(1)
        self.help_btn = QToolButton()
        self.help_btn.setText("Help")
        self.help_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        help_menu = QMenu(self.help_btn)
        about_action = QAction("About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
        ondevice_action = QAction("On-Device Features", self)
        ondevice_action.setToolTip(
            "The controller's own button combos (profile switch, on-the-fly "
            "paddle remap, hair-trigger toggle, calibration) -- these work "
            "with no software at all."
        )
        ondevice_action.triggered.connect(self._on_ondevice_features)
        help_menu.addAction(ondevice_action)
        help_menu.addSeparator()
        report_issue_action = QAction("Report an Issue…", self)
        report_issue_action.triggered.connect(self._on_report_issue)
        help_menu.addAction(report_issue_action)
        self.help_btn.setMenu(help_menu)
        top.addWidget(self.help_btn)
        return top

    def _build_tabs(self) -> QWidget:
        """One tab per settings category, mirroring pyg7's modules, plus the
        banner that marks them unconfirmed (see _refresh_confirmed_display).

        Settings is last and deliberately apart from the rest: everything
        before it is per-profile, while the dock settings it holds are
        device-wide.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
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
        self.unconfirmed_banner.setStyleSheet("color: #d99a3f;")
        layout.addWidget(self.unconfirmed_banner)
        self.tabs = QTabWidget()
        self.buttons_view = ButtonsView()
        self.sticks_view = SticksView()
        self.triggers_view = TriggersView()
        self.motion_view = MotionView()
        self.vibration_view = VibrationView()
        self.settings_view = SettingsView()
        for view, label in (
            (self.buttons_view, "Buttons"),
            (self.sticks_view, "Sticks"),
            (self.triggers_view, "Triggers"),
            (self.motion_view, "Motion"),
            (self.vibration_view, "Vibration"),
            (self.settings_view, "Settings"),
        ):
            self.tabs.addTab(view, label)
            # Any edit in any tab marks the state dirty, which is what
            # suppresses the automatic read-on-connect from discarding it.
            view.changed.connect(self._on_dirty)
        layout.addWidget(self.tabs, 1)
        return container

    def _build_action_bar(self) -> QHBoxLayout:
        """File actions on the left, device actions on the right.

        The split is intentional: Import/Export only touch local JSON, while
        Release/Read/Sync all talk to hardware. Sync Now is the only
        destructive one and is styled and gated accordingly.
        """
        button_bar = QHBoxLayout()
        button_bar.setSpacing(8)
        self.import_export_btn = QToolButton()
        self.import_export_btn.setText("Import / Export")
        self.import_export_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        import_export_menu = QMenu(self.import_export_btn)
        import_action = QAction("Import…", self)
        import_action.setToolTip("Load a previously exported JSON snapshot file")
        import_action.triggered.connect(self._on_import)
        import_export_menu.addAction(import_action)
        export_action = QAction("Export…", self)
        export_action.setToolTip("Save the current state to a JSON snapshot file")
        export_action.triggered.connect(self._on_export)
        import_export_menu.addAction(export_action)
        self.import_export_btn.setMenu(import_export_menu)
        button_bar.addWidget(self.import_export_btn)
        button_bar.addStretch(1)
        self.release_btn = QPushButton("Release Device")
        self.release_btn.setEnabled(False)
        self.release_btn.setToolTip(
            "Hand the controller back so it works as a gamepad again "
            "(stops heartbeating), without quitting the app"
        )
        self.release_btn.clicked.connect(self._on_release_clicked)
        button_bar.addWidget(self.release_btn)
        self.read_btn = QPushButton("Read from Device")
        self.read_btn.setEnabled(False)
        self.read_btn.setToolTip(
            "Read the controller's actual current settings back from it, "
            "overwriting every tab here."
        )
        self.read_btn.clicked.connect(self.request_read_from_device)
        button_bar.addWidget(self.read_btn)
        self.sync_btn = QPushButton("Sync Now")
        self.sync_btn.setProperty("role", "primary")
        self.sync_btn.setEnabled(False)
        self.sync_btn.setToolTip(
            "Push the current state to the connected controller. Disabled "
            "until the state has been confirmed against real hardware, via "
            "a successful Read from Device or an explicit Import."
        )
        self.sync_btn.clicked.connect(self.request_sync_now)
        button_bar.addWidget(self.sync_btn)
        return button_bar

    def _build_status_bar(self) -> QHBoxLayout:
        """Connection state and errors on the left, job progress on the right.

        Five separate labels rather than one shared message area, so a sync
        progress update can't wipe out a connection error the user hasn't
        read yet.
        """
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.connection_label = QLabel("Device: disconnected")
        self.connection_label.setProperty("role", "muted")
        bottom.addWidget(self.connection_label)
        # Shown only while a session is actually held -- see
        # set_connection_state(). Not an error (nothing is wrong), so it gets
        # its own amber label rather than sharing error_label's red one or
        # hiding in the muted grey of connection_label.
        self.playability_label = QLabel("")
        self.playability_label.setStyleSheet("color: #d99a3f;")
        self.playability_label.setToolTip(
            "To read or write configuration the controller has to sit in its "
            "vendor/config identity, where it is not an Xbox pad and has no "
            "HID keyboard/mouse to emit your remapped keys. This is just as "
            "true over the 2.4GHz dongle as it is wired -- the dongle bridges "
            "the same session through. Click \"Release Device\" to hand the "
            "controller back without quitting."
        )
        bottom.addWidget(self.playability_label)
        # Charge, sampled off the input stream by DeviceWatcher. Hidden
        # entirely when there is no reading rather than showing "Battery: ?" --
        # an unknown charge is not information, and a permanent placeholder in
        # a status bar reads as something being wrong.
        self.battery_label = QLabel("")
        self.battery_label.setProperty("role", "muted")
        self.battery_label.setToolTip(
            "Charge as reported by the controller itself.\n\n"
            "Read from the input stream it broadcasts while connected, so it "
            "costs no extra USB traffic and issues no config read."
        )
        self.battery_label.setVisible(False)
        bottom.addWidget(self.battery_label)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e0524f;")
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
        self.battery_label.setText(
            f"Battery: {percent}%" + ("  (charging)" if charging else ""))
        # Amber below 20%, and only then -- a status bar that is permanently
        # coloured teaches the user to ignore the colour.
        self.battery_label.setStyleSheet("" if percent > 20 else "color: #d99a3f;")
        self.battery_label.setVisible(True)

    def set_active_profile(self, slot: int) -> None:
        """Mark which profile the controller is physically using.

        The selector chooses what you *edit*; this shows what you are
        *playing*. They are independent -- every category targets a profile
        explicitly, so editing Profile 2 while playing Profile 1 works
        correctly -- but until now nothing on screen said so, and a user
        editing "their" profile had no way to tell they were looking at a
        different one.

        Rendered by relabelling the combo entries rather than adding another
        status widget, so the fact lands where the choice is made. Uses
        setItemText, which does not change the current index and so cannot
        fire _on_profile_changed.
        """
        self._active_profile = slot
        for i in range(self.profile_combo.count()):
            data = self.profile_combo.itemData(i)
            if not isinstance(data, int) or data == SHIFT_VIEW:
                continue
            self.profile_combo.setItemText(
                i, f"Profile {data} (in use)" if data == slot else f"Profile {data}")

    def set_firmware(self, version: str) -> None:
        """Record the controller's firmware version, read once per connection.

        It goes in the connection label's tooltip rather than its text: the
        version is reference information someone looks up when filing a bug,
        not something worth spending status-bar width on every session.
        """
        self._firmware = version
        self.connection_label.setToolTip(f"Controller firmware v{version}")

    def clear_battery(self) -> None:
        """No reading available -- hide rather than show a stale number."""
        self.battery_label.clear()
        self.battery_label.setVisible(False)

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

        Holding the device keeps it in vendor/config mode, where it isn't a
        gamepad at all -- so tabbing away to actually play would otherwise
        find a dead controller until Release Device was clicked by hand.
        GameSir Nexus releases on unfocus for the same reason. Hiding to the
        tray deactivates the window too, so that path is covered by this one.
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
        leaves _auto_released false, so refocusing won't silently reconnect."""
        if not self._auto_released:
            return
        self._auto_released = False
        if self._connection_state == "paused":
            self.release_toggled.emit(False)

    def set_connection_state(self, state: str) -> None:
        labels = {
            "disconnected": "disconnected", "connecting": "connecting…",
            "connected": "connected", "paused": "released (click Reconnect to resume)",
            "no_controller": "dongle detected, no controller responding",
        }
        self.connection_label.setText(f"Device: {labels.get(state, state)}")
        # The controller is not usable for playing while this app holds it,
        # on the dongle as much as wired (see PROTOCOL.md "Device
        # identities"). Until 2026-08-01 that was documented only in the
        # README -- and documented there as a wired-only caveat -- so a
        # wireless user met a dead gamepad with nothing on screen connecting
        # it to this app or pointing at the button that fixes it.
        self.playability_label.setText(
            "not usable as a gamepad until released" if state == "connected" else ""
        )
        was_connected = self._connection_state == "connected"
        self._connection_state = state
        if state == "connected":
            self.release_btn.setText("Release Device")
            self.release_btn.setEnabled(True)
            self._set_role(self.release_btn, "danger")
            self._refresh_sync_btn()
            self.read_btn.setEnabled(not self._syncing)
            self.error_label.setText("")  # a successful (re)connect supersedes any earlier error
            if not was_connected:
                self._auto_read_on_connect()
        elif state == "paused":
            self.release_btn.setText("Reconnect")
            self.release_btn.setEnabled(True)
            self._set_role(self.release_btn, None)
            self.sync_btn.setEnabled(False)
            self.read_btn.setEnabled(False)
        else:
            self.release_btn.setEnabled(False)
            self._set_role(self.release_btn, None)
            self.sync_btn.setEnabled(False)
            self.read_btn.setEnabled(False)

    @staticmethod
    def _set_role(widget: QWidget, role: Optional[str]) -> None:
        """Update a widget's `role` dynamic property and force Qt's style
        engine to re-evaluate the QSS selectors keyed on it -- a plain
        setProperty() after the widget is already shown doesn't repaint on
        its own."""
        widget.setProperty("role", role)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def set_error(self, message: str) -> None:
        self.error_label.setText(message)

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

        Disables every QScrollArea's *contained widget*, not self.tabs and
        not the QScrollAreas themselves -- Qt's disabled state cascades
        downward with no way for a child to opt back out (confirmed: a
        QScrollArea explicitly re-enabled still reports its own scrollbar
        as disabled if any ancestor is disabled), so disabling self.tabs
        directly, as this used to do, took the scrollbars down with every
        actual control. Scrolling and switching tabs are navigation, not an
        edit -- a user should be able to look at an unconfirmed tab's full
        content without that being mistaken for permission to change it.
        Every category view wraps its real content in a QScrollArea now
        (see TriggersView/VibrationView/SettingsView's own comments), so
        this still reaches every control with one flag, not a per-view "is
        this real" plumbing job -- just aimed one level deeper than before.
        The banner above the tabs (built in _build_tabs()) covers the case
        a user never hovers or tries to interact, which "just disabled"
        would miss.

        Must be called every time self._state_confirmed changes: on
        construction, after every read attempt (success or failure), on
        Import, and on a profile switch (whose value it turns False again --
        see _on_profile_changed for why that has to happen even before the
        resulting read comes back).
        """
        confirmed = self._state_confirmed
        for scroll in self.tabs.findChildren(QScrollArea):
            content = scroll.widget()
            if content is not None:
                content.setEnabled(confirmed)
        self.unconfirmed_banner.setVisible(not confirmed)

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
        if self.profile_combo.currentData() == SHIFT_VIEW:
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
        self.sync_btn.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self.sync_status_label.setText("Syncing…")
        self.sync_requested.emit(self._state)

    def set_sync_progress(self, step: int, total: int, label: str) -> None:
        if total == 0:
            self.sync_status_label.setText(label)  # e.g. "Reading current device state…", no step count yet
        else:
            self.sync_status_label.setText(f"Syncing ({step}/{total}): {label}")

    def set_sync_finished(self, success: bool, message: str) -> None:
        self._syncing = False
        self.sync_status_label.setText(message)
        self._refresh_sync_btn()
        self.read_btn.setEnabled(self._connection_state == "connected")
        self.profile_combo.setEnabled(True)
        if success:
            self._set_dirty(False)  # the device now matches what we just pushed
        else:
            # Previously this only updated the small muted status label --
            # easy to miss for the riskier of the two hardware operations
            # (this pushes to persistent device config), while a local
            # Export/Import failure got a blocking dialog. Now both do.
            QMessageBox.warning(self, "Sync failed", message)

    def request_read_from_device(self) -> None:
        if self._connection_state != "connected" or self._syncing:
            return
        # Covers both callers that can reach here with unsynced edits still
        # pending: the "Read from Device" button itself, and picking a
        # different profile in the combo (_on_profile_changed() calls this
        # too, previously with no guard at all). _auto_read_on_connect()
        # already checks self._dirty before ever calling in here, so the
        # automatic path never reaches this prompt -- no double-confirm.
        if self._dirty and not self._confirm(
            "Discard unsynced changes?",
            "Reading from the device will overwrite unsaved edits in every "
            "tab with the controller's actual current settings. Continue?",
        ):
            return
        self._syncing = True
        self.sync_btn.setEnabled(False)
        self.read_btn.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self.sync_status_label.setText("Reading from device…")
        slot = self._state.get("controller_slot") or 1
        self.read_requested.emit(slot)

    def set_read_finished(self, success: bool, message: str, device_state: Optional[dict]) -> None:
        self._syncing = False
        self.sync_status_label.setText(message)
        if success and device_state is not None:
            self._state_confirmed = True
        self._refresh_sync_btn()
        self._refresh_confirmed_display()
        self.read_btn.setEnabled(self._connection_state == "connected")
        self.profile_combo.setEnabled(True)
        if not success or device_state is None:
            if not success:
                # Same reasoning as set_sync_finished()'s warning -- a
                # failed read is at least as consequential as a failed
                # Export/Import (which already gets a blocking dialog).
                QMessageBox.warning(self, "Read from device failed", message)
            return
        # Merge key-by-key rather than replacing the layer dict wholesale.
        #
        # read_state() does now cover all 21 buttons (it didn't when this
        # merge was written -- RT, LT and the D-pad directions were missing,
        # and a blind `self._state["buttons"] = device_state["buttons"]`
        # silently deleted real bindings on them during ordinary "Read from
        # Device" use, confirmed the hard way on 2026-07-28). The merge stays
        # regardless: it costs nothing, and it means the next button the
        # decoder doesn't yet know about degrades to "left alone" instead of
        # "silently unbound". Replace-the-whole-dict is only safe while
        # coverage is exhaustive, which is not a property worth betting user
        # data on.
        for layer in ("default", "shift"):
            self._state["buttons"].setdefault(layer, {}).update(device_state["buttons"].get(layer, {}))
        self._state["dpad_diagonal_lock"] = device_state["dpad_diagonal_lock"]
        self._state["swap_stick_dpad"] = device_state["swap_stick_dpad"]
        # Continuous Trigger. Must land BEFORE the Buttons view
        # repaints on the next line, or the checkboxes are painted from the
        # previous state and the device's values arrive too late to show.
        #
        # Replaced wholesale rather than merged: decode_continuous_triggers()
        # returns every button-table slot on every read, so there is no
        # partial-coverage case for a merge to protect.
        #
        # Omitting this entirely was a real bug, reported from a game on
        # 2026-08-14: the GUI read the device's Continuous Trigger state, dropped it
        # here, and painted default_state_dict()'s all-unchecked scaffold, so
        # buttons that were genuinely repeating showed as off. Worse, the
        # Buttons view writes every checkbox back into the state on any edit,
        # so a later Sync would have pushed those false values to the device
        # and silently cleared Continuous Trigger set from Nexus or the CLI.
        self._state["continuous_trigger"] = device_state.get("continuous_trigger", {})
        self.buttons_view.load_state(self._state)

        # Sticks/Triggers/Vibration/report rate are read in full (every
        # setting mapped, no partial-coverage gaps like Buttons had) -- a
        # plain replace is safe here, unlike the merge-not-replace fix
        # Buttons needed above.
        self._state["sticks"] = device_state["sticks"]
        self._state["triggers"] = device_state["triggers"]
        # Additive section (see pyg7/state.py's validate_state()) -- always
        # present in a fresh read_state(), unlike dock settings below, so no
        # None-guard needed here.
        self._state["motion"] = device_state["motion"]
        self._state["vibration"] = device_state["vibration"]
        self._state["report_rate_hz"] = device_state["report_rate_hz"]
        # None means "not read this call" (the watcher skips this
        # device-global, unconfirmed-to-ever-change-mid-connection blob
        # after the first read per connection -- see DeviceWatcher's
        # `_dock_known` and read_state()'s `include_dock`), not "read back
        # empty" -- keep whatever value is already showing instead of
        # blanking the Settings tab on every profile switch.
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
        self._sync_profile_combo()
        self._sync_report_rate_combo()
        self.buttons_view.load_state(self._state)
        self.sticks_view.load_state(self._state)
        self.triggers_view.load_state(self._state)
        self.motion_view.load_state(self._state)
        self.vibration_view.load_state(self._state)
        self.settings_view.load_state(self._state)
        self._set_dirty(False)

    def _sync_profile_combo(self) -> None:
        """Reflect self._state["controller_slot"] in the combo without
        re-triggering _on_profile_changed (which would otherwise fire a
        redundant read/no-op write for a value that just came FROM state,
        not from the user picking a new one)."""
        if self.profile_combo.currentData() == SHIFT_VIEW:
            # A read finishing must not yank the user out of the Shift view
            # back to whichever profile it happened to target. The Shift
            # layer came back with that read anyway -- it is global.
            return
        self._loading_profile_combo = True
        try:
            idx = self.profile_combo.findData(self._state.get("controller_slot") or 1)
            self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._loading_profile_combo = False

    def _on_profile_changed(self, _index: int) -> None:
        if self._loading_profile_combo:
            return
        selected = self.profile_combo.currentData()
        self._apply_view(selected)
        if selected == SHIFT_VIEW:
            # The Shift layer is device-global and came back with whichever
            # profile was last read, so there is nothing new to fetch and no
            # profile to re-target. Switching to it must NOT touch
            # controller_slot: the other categories still belong to a real
            # profile, and a sync from this screen still targets that one.
            return
        self._state["controller_slot"] = selected
        # The values on screen right now were confirmed (if ever) against
        # whichever profile was selected before, not this one -- they say
        # nothing about this profile until a read of it succeeds. Clearing
        # here, not only on read failure, is what stops a failed OR declined
        # read from leaving the previous profile's real values on screen
        # looking exactly like a confirmed reading of the new selection.
        # (Roadmap: "GUI displays unread state as if it were real" -- this
        # was the specific case that made a real bug look believable rather
        # than obviously broken.)
        self._state_confirmed = False
        self._refresh_confirmed_display()
        self._refresh_sync_btn()
        if self._connection_state == "connected" and not self._syncing:
            self.request_read_from_device()

    def _apply_view(self, selected) -> None:
        """Show the Shift layer's single screen, or the full per-profile set.

        The Shift blob carries stick/trigger/vibration bytes only because
        every one of the five blobs shares a 480-byte layout -- their values
        are plain factory defaults and Nexus never exposes them. More to the
        point, nothing can write them: the Sticks/Triggers/Vibration/Report
        Rate prefixes carry a plain profile number, and there is no profile
        number that addresses the Shift blob. So those tabs are hidden here
        rather than shown and quietly ignored.
        """
        shift_view = selected == SHIFT_VIEW
        self.buttons_view.set_layer("shift" if shift_view else "default")
        for index in range(self.tabs.count()):
            if self.tabs.widget(index) is not self.buttons_view:
                self.tabs.setTabVisible(index, not shift_view)
        if shift_view:
            self.tabs.setCurrentWidget(self.buttons_view)
        self.report_rate_label.setVisible(not shift_view)
        self.report_rate_combo.setVisible(not shift_view)

    def _sync_report_rate_combo(self) -> None:
        """Reflect self._state["report_rate_hz"] in the combo -- same
        loading-guard reasoning as _sync_profile_combo()."""
        self._loading_report_rate_combo = True
        try:
            idx = self.report_rate_combo.findData(self._state.get("report_rate_hz") or 1000)
            # Falls back to the last item (1000 Hz) -- default_state_dict()'s
            # own confirmed default, not just "whatever happens to be last."
            self.report_rate_combo.setCurrentIndex(idx if idx >= 0 else self.report_rate_combo.count() - 1)
        finally:
            self._loading_report_rate_combo = False

    def _on_report_rate_changed(self, _index: int) -> None:
        if self._loading_report_rate_combo:
            return
        self._state["report_rate_hz"] = self.report_rate_combo.currentData()
        self._on_dirty()

    def _default_snapshot_dir(self) -> str:
        return str(_LEGACY_PROFILES_DIR if _LEGACY_PROFILES_DIR.is_dir() else Path.home())

    def _on_export(self) -> None:
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

    def _on_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self.status_label.setText("Unsynced changes")
        else:
            self.status_label.setText("")
