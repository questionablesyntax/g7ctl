"""System tray icon: reflects DeviceWatcher connection state.

Icons live in g7ctlc/assets/. As of 2026-08-02 the four states are
icon_black/yellow/green/red.png: a rendered controller whose centre
indicator carries the state colour. The indicator is enlarged ~2.2x from
the source artwork, with a contrasting rim -- at the 16-22px a panel
actually renders a tray icon at, the original dot was ~3px and the states
were not tellable apart. This replaces the abstract gamepad-outline glyph
set used from 2026-07-29.
"""
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

if TYPE_CHECKING:
    # Only for type checking -- importing MainWindow at module load time
    # would be circular (main_window.py imports _STATE_ICON_FILES/
    # _state_icon from this module).
    from .main_window import MainWindow

_ASSETS_DIR = Path(__file__).parent / "assets"
_STATE_ICON_FILES = {
    "disconnected": "icon_black.png",
    "connecting": "icon_yellow.png",
    "connected": "icon_green.png",
    "paused": "icon_red.png",
    "no_controller": "icon_yellow.png",
}
_STATE_LABELS = {
    "disconnected": "Disconnected",
    "connecting": "Connecting…",
    "connected": "Connected -- controller not usable as a gamepad until released",
    "paused": "Released (click Reconnect to resume)",
    # Not dongle-specific since the 2026-08-29 detection redesign made the
    # underlying liveness probe run unconditionally -- a wired connection
    # can land in this state too now (confirmed live 2026-08-30, on a
    # transient errno-19 blip fresh off a handshake re-enumeration -- see
    # VendorSession.probe_controller_live()). This label predated that
    # change and didn't get updated for it -- a real, user-visible bug.
    "no_controller": "No controller responding",
}



# Sizes KDE/KWin's window decoration, the Task Manager, and the tray itself
# are known to request. QIcon(path) alone only registers the source PNG's
# native 512x512 -- confirmed via QIcon.availableSizes() -- and left to
# scale that down to a ~16px title-bar icon itself, KWin was observed
# (2026-07-29, real hardware/desktop) rendering it as a flat solid-color
# square instead of the outline glyph, even though the same source scales
# down cleanly through both Pillow and Qt's own QPixmap.scaled() at
# identical sizes. Registering explicit pre-scaled pixmaps sidesteps
# whatever that external path does with a single huge source.
_ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def _state_icon(filename: str) -> QIcon:
    source = QPixmap(str(_ASSETS_DIR / filename))
    icon = QIcon()
    for size in _ICON_SIZES:
        icon.addPixmap(source.scaled(
            QSize(size, size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
    return icon


class TrayIcon(QSystemTrayIcon):
    release_toggled = pyqtSignal(bool)  # True = release to XInput, False = reconnect

    def __init__(self, main_window: "MainWindow", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.main_window = main_window
        self._state = "disconnected"
        self._syncing = False
        # Built per unique filename, not per state: "connecting" and
        # "no_controller" share icon_yellow.png (_STATE_ICON_FILES above),
        # and _state_icon() re-scales into all 9 _ICON_SIZES on every call --
        # no reason to do that work twice for identical pixmap content.
        by_file: dict = {}
        self._icons = {}
        for state, fname in _STATE_ICON_FILES.items():
            if fname not in by_file:
                by_file[fname] = _state_icon(fname)
            self._icons[state] = by_file[fname]

        menu = QMenu()
        show_action = QAction("Show Window", menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        self.sync_action = QAction("Sync Now", menu)
        self.sync_action.setEnabled(False)
        self.sync_action.setToolTip("Push the current state to the connected controller")
        self.sync_action.triggered.connect(self.main_window.request_sync_now)
        menu.addAction(self.sync_action)

        self.release_action = QAction("Release Device", menu)
        self.release_action.setEnabled(False)
        self.release_action.triggered.connect(self._on_release_clicked)
        menu.addAction(self.release_action)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.set_state("disconnected")

    def set_state(self, state: str) -> None:
        self._state = state
        self.setIcon(self._icons.get(state, self._icons["disconnected"]))
        self.setToolTip(f"G7 Control Center -- {_STATE_LABELS.get(state, state)}")
        if state == "connected":
            self.release_action.setText("Release Device")
            # Real bug, found 2026-09-01: this used to be an unconditional
            # True. main_window.py deliberately disables its own release_btn
            # during a sync/read (request_sync_now()'s own comment: "no
            # reason to let a click through mid-sync"), and
            # _auto_release_if_still_unfocused() separately re-checks
            # _syncing before ever emitting release_toggled -- but the
            # tray's own Release Device action had neither protection,
            # bypassing the one guard every other release-trigger in the
            # app was deliberately hardened with.
            self.release_action.setEnabled(not self._syncing)
            self.sync_action.setEnabled(True)
        elif state == "paused":
            self.release_action.setText("Reconnect")
            self.release_action.setEnabled(True)
            self.sync_action.setEnabled(False)
        else:
            self.release_action.setEnabled(False)
            self.sync_action.setEnabled(False)

    def set_syncing(self, syncing: bool) -> None:
        """Connected to MainWindow.syncing_changed -- set_state() alone
        isn't enough, since connection state stays "connected" throughout
        a sync/read and nothing re-invokes it just because _syncing
        toggles (see MainWindow.syncing_changed's own comment)."""
        self._syncing = syncing
        if self._state == "connected":
            self.release_action.setEnabled(not syncing)

    def _on_release_clicked(self) -> None:
        self.release_toggled.emit(self._state != "paused")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger = a single left-click on the tray icon (right-click opens
        # the context menu set via setContextMenu() and never reaches here).
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self) -> None:
        if self.main_window.isVisible():
            self.main_window.hide()
        else:
            self._show_window()

    def _show_window(self) -> None:
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    @staticmethod
    def _quit() -> None:
        QApplication.instance().quit()
