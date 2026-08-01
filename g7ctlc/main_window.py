"""Main window: category tabs, Import/Export, Sync Now, Read from Device."""
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QByteArray, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pyg7 import state as state_mod

from . import help_content
from .tray import _state_icon
from .views.buttons_view import ButtonsView
from .views.settings_view import SettingsView
from .views.sticks_view import SticksView
from .views.triggers_view import TriggersView
from .views.vibration_view import VibrationView

# The window/taskbar icon is static regardless of connection state -- only
# the tray icon (see tray.py's TrayIcon) reflects state with color. A
# per-state window icon was tried and reverted (2026-07-29): distracting in
# the title bar/taskbar, which users expect to stay constant for an app.
# Reuses the "disconnected" glyph (icon_gray.png) rather than a dedicated
# static asset -- a denser solid-silhouette design was tried first but its
# small button holes aliased into a busy speckle at the ~16px size KWin
# renders the title-bar icon at; the open-outline glyph survives that fine.
_APP_ICON_FILE = "icon_gray.png"

_GEOMETRY_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "window_geometry.dat"
)

# Old ProfileStore-managed profiles lived here -- kept only as a friendly
# default starting directory for the Export/Import file dialogs, so existing
# users land somewhere with their old profile JSONs still importable (same
# schema, no migration needed).
_LEGACY_PROFILES_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "profiles"
)


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
        self._syncing = False  # true while either a sync-to or read-from-device job is in flight
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
        self.profile_combo.setToolTip(
            "Which of the controller's 4 onboard profile slots to read from / "
            "sync to. Every category (Buttons, Sticks, Triggers, Vibration, "
            "Report Rate) is independently profile-scoped."
        )
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)
        top.addWidget(QLabel("Report Rate:"))
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

    def _build_tabs(self) -> QTabWidget:
        """One tab per settings category, mirroring pyg7's modules.

        Settings is last and deliberately apart from the rest: everything
        before it is per-profile, while the dock settings it holds are
        device-wide.
        """
        self.tabs = QTabWidget()
        self.buttons_view = ButtonsView()
        self.sticks_view = SticksView()
        self.triggers_view = TriggersView()
        self.vibration_view = VibrationView()
        self.settings_view = SettingsView()
        for view, label in (
            (self.buttons_view, "Buttons"),
            (self.sticks_view, "Sticks"),
            (self.triggers_view, "Triggers"),
            (self.vibration_view, "Vibration"),
            (self.settings_view, "Settings"),
        ):
            self.tabs.addTab(view, label)
            # Any edit in any tab marks the state dirty, which is what
            # suppresses the automatic read-on-connect from discarding it.
            view.changed.connect(self._on_dirty)
        return self.tabs

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

        Four separate labels rather than one shared message area, so a sync
        progress update can't wipe out a connection error the user hasn't
        read yet.
        """
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.connection_label = QLabel("Device: disconnected")
        self.connection_label.setProperty("role", "muted")
        bottom.addWidget(self.connection_label)
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

    def set_connection_state(self, state: str) -> None:
        labels = {
            "disconnected": "disconnected", "connecting": "connecting…",
            "connected": "connected", "paused": "released (click Reconnect to resume)",
            "no_controller": "dongle detected, no controller responding",
        }
        self.connection_label.setText(f"Device: {labels.get(state, state)}")
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
        if not self._confirm(
            "Sync to controller?",
            f"Push the current settings to Profile {slot} on the connected "
            "controller? This overwrites that profile's stored settings.",
        ):
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
        self.buttons_view.load_state(self._state)

        # Sticks/Triggers/Vibration/report rate are read in full (every
        # setting mapped, no partial-coverage gaps like Buttons had) -- a
        # plain replace is safe here, unlike the merge-not-replace fix
        # Buttons needed above.
        self._state["sticks"] = device_state["sticks"]
        self._state["triggers"] = device_state["triggers"]
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
        self.vibration_view.load_state(self._state)
        self.settings_view.load_state(self._state)

        self._set_dirty(False)  # local state now matches the device, not a pending change

    def _load_views_from_state(self) -> None:
        self._sync_profile_combo()
        self._sync_report_rate_combo()
        self.buttons_view.load_state(self._state)
        self.sticks_view.load_state(self._state)
        self.triggers_view.load_state(self._state)
        self.vibration_view.load_state(self._state)
        self.settings_view.load_state(self._state)
        self._set_dirty(False)

    def _sync_profile_combo(self) -> None:
        """Reflect self._state["controller_slot"] in the combo without
        re-triggering _on_profile_changed (which would otherwise fire a
        redundant read/no-op write for a value that just came FROM state,
        not from the user picking a new one)."""
        self._loading_profile_combo = True
        try:
            idx = self.profile_combo.findData(self._state.get("controller_slot") or 1)
            self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._loading_profile_combo = False

    def _on_profile_changed(self, _index: int) -> None:
        if self._loading_profile_combo:
            return
        slot = self.profile_combo.currentData()
        self._state["controller_slot"] = slot
        if self._connection_state == "connected" and not self._syncing:
            self.request_read_from_device()

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
