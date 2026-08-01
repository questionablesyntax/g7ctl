"""System tray icon: reflects DeviceWatcher connection state.

Icons live in g7ctlc/assets/. As of 2026-07-29, all four states use
an abstract gamepad-outline glyph (icon_gray/orange/green/red.png), recolored
per state -- not derived from any GameSir product photo or artwork, replacing
the earlier AI-rendered controller-on-dock icons that carried unclear
derivative-work/copyright status. Note the new glyph set is itself
AI-generated (Google Gemini, per the source filenames) -- it resolves the
product-photo derivative-work risk but not the separate "AI output may not
be independently copyrightable" question, which is still open for this art.
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
    "disconnected": "icon_gray.png",
    "connecting": "icon_orange.png",
    "connected": "icon_green.png",
    "paused": "icon_red.png",
    "no_controller": "icon_orange.png",
}
_STATE_LABELS = {
    "disconnected": "Disconnected",
    "connecting": "Connecting…",
    "connected": "Connected -- controller not usable as a gamepad until released",
    "paused": "Released (click Reconnect to resume)",
    "no_controller": "Dongle detected, no controller responding",
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
        self._icons = {state: _state_icon(fname) for state, fname in _STATE_ICON_FILES.items()}

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
            self.release_action.setEnabled(True)
            self.sync_action.setEnabled(True)
        elif state == "paused":
            self.release_action.setText("Reconnect")
            self.release_action.setEnabled(True)
            self.sync_action.setEnabled(False)
        else:
            self.release_action.setEnabled(False)
            self.sync_action.setEnabled(False)

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
