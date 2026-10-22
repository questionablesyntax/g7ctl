"""System tray icon: reflects DeviceWatcher connection state.

A5 of the redesign, decision D4: shape-coded states replace the
rendered-controller-with-a-coloured-dot icons used since 2026-08-02.
DIRECTION-A.md section 7 item 6: "Today's tray colours (black/yellow/
green/red) put red on released, which is the safe, playable state.
Proposed tray instead: a filled signal dot = held; no dot = released; a
hollow ring = connecting / no controller; a red dot with a cut = error.
Shape carries the state, so the 16px icon passes without colour vision."

Drawn with QPainter rather than new raster artwork: the real illustrated
controller is Track D's job (its own gated phase, a quality bar, not
this one), and these are small abstract status badges, not a redo of
that asset. "No dot" is read as "no signal-coloured dot" rather than a
literally blank icon (an icon with nothing on it stops being usable as
a tray icon) -- a plain, muted filled circle for "released", distinct
in both shape-weight and colour from the hollow ring "pending" states.
"""
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .palette import DARK_PALETTE, Palette

if TYPE_CHECKING:
    # Only for type checking -- importing MainWindow at module load time
    # would be circular (main_window.py imports _state_icon from this
    # module for the window/taskbar icon).
    from .main_window import MainWindow

_ASSETS_DIR = Path(__file__).parent / "assets"

# Connection state -> shape variant. "connecting", "no_controller" and
# "disconnected" all collapse onto the same hollow-ring "pending" shape --
# DIRECTION-A.md's own wording groups "connecting / no controller", and
# OwnershipBar (A3) already makes the identical call for "disconnected"
# vs. "no_controller" (one ClampBar variant, two different sentences).
_VARIANT_BY_STATE = {
    "disconnected": "pending",
    "connecting": "pending",
    "connected": "held",
    "paused": "released",
    "no_controller": "pending",
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
    """Still used for the static window/taskbar icon (always the
    "disconnected"-era PNG regardless of connection state -- see
    main_window.py's own comment on _app_icon()). The tray's own
    per-state icons are _variant_icon() below now."""
    source = QPixmap(str(_ASSETS_DIR / filename))
    icon = QIcon()
    for size in _ICON_SIZES:
        icon.addPixmap(source.scaled(
            QSize(size, size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
    return icon


def _draw_variant(painter: QPainter, variant: str, size: int, palette: Palette) -> None:
    margin = max(1.0, size * 0.12)
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if variant == "held":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.signal_mark))
        painter.drawEllipse(rect)
    elif variant == "released":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.border_control))
        painter.drawEllipse(rect)
    elif variant == "pending":
        pen = QPen(QColor(palette.border_control))
        pen.setWidthF(max(1.5, size * 0.12))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(pen.widthF() / 2, pen.widthF() / 2,
                                          -pen.widthF() / 2, -pen.widthF() / 2))
    elif variant == "alarm":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.alarm_fill))
        painter.drawEllipse(rect)
        # The cut: a single diagonal stroke through the filled dot, same
        # "shape carries the state" principle -- a colourblind user still
        # sees a circle-with-a-slash, not just a dot in some other red.
        pen = QPen(QColor(palette.surface_ground))
        pen.setWidthF(max(1.5, size * 0.14))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(rect.topLeft(), rect.bottomRight())
    else:  # pragma: no cover - defensive; every real variant is listed above
        raise ValueError(f"unknown tray icon variant: {variant!r}")


def _variant_icon(variant: str, palette: Palette) -> QIcon:
    icon = QIcon()
    for size in _ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            _draw_variant(painter, variant, size, palette)
        finally:
            painter.end()
        icon.addPixmap(pixmap)
    return icon


class TrayIcon(QSystemTrayIcon):
    release_toggled = pyqtSignal(bool)  # True = release to XInput, False = reconnect

    def __init__(
        self, main_window: "MainWindow", palette: Palette = DARK_PALETTE,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.main_window = main_window
        self._state = "disconnected"
        self._syncing = False
        self._has_error = False
        self._palette = palette
        self._build_icons()

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

    def _build_icons(self) -> None:
        # Built once per unique shape variant, not per connection state --
        # "connecting"/"no_controller"/"disconnected" all share "pending"
        # (see _VARIANT_BY_STATE), no reason to draw and register that
        # shape into all nine _ICON_SIZES three separate times.
        by_variant: dict = {}
        self._icons = {}
        for state, variant in _VARIANT_BY_STATE.items():
            if variant not in by_variant:
                by_variant[variant] = _variant_icon(variant, self._palette)
            self._icons[state] = by_variant[variant]
        self._alarm_icon = _variant_icon("alarm", self._palette)

    def set_palette(self, palette: Palette) -> None:
        """Called on a theme change (MainWindow's ThemeController.paletteChanged,
        wired in app.py) -- these are painted pixmaps, not QSS, so a
        regenerated stylesheet alone never reaches them."""
        self._palette = palette
        self._build_icons()
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        icon = self._alarm_icon if self._has_error else self._icons.get(self._state, self._icons["disconnected"])
        self.setIcon(icon)

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "connected":
            # A successful (re)connect supersedes any earlier error -- same
            # rule main_window.py's set_connection_state() already applies
            # to its own error_label.
            self._has_error = False
        self._refresh_icon()
        # Real bug, found in A6's code review (2026-10-22): this used to
        # set the tooltip unconditionally, clobbering set_error()'s own
        # error-message tooltip the moment the connection state changed
        # while that error was still active -- the icon stayed alarm-
        # shaped (see _refresh_icon() above) but the tooltip explaining
        # why reverted to a generic state label. _has_error is only False
        # here if state == "connected" already cleared it above, or no
        # error was ever set, so this is never stale.
        if not self._has_error:
            tooltip = f"G7 Control Center -- {_STATE_LABELS.get(state, state)}"
            self.setToolTip(tooltip)
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

    def set_error(self, message: str) -> None:
        """Connected to DeviceWatcher.error in app.py, same signal
        main_window.py's own set_error() listens to. A non-empty message
        switches the tray to the alarm shape (red dot, cut) regardless of
        connection state; an empty one (or the next successful connect,
        see set_state()) clears it."""
        self._has_error = bool(message)
        self._refresh_icon()
        if self._has_error:
            self.setToolTip(f"G7 Control Center -- {message}")
        else:
            self.setToolTip(f"G7 Control Center -- {_STATE_LABELS.get(self._state, self._state)}")

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

    def _quit(self) -> None:
        # REAL BUG, found 2026-09-17 (Astra and Sol's bug-sweeps,
        # independently), fixed exactly the way app.py's own _shutdown()
        # comment already specified but deferred: "the real fix would be
        # confirming with the user before quitting at all while a sync is
        # in flight (the same pattern Sync Now itself already asks for)."
        # Without this, Quit was available and unconditional even mid-sync
        # -- app.py's bounded 10s wait for the watcher thread could still
        # expire and proceed while a real, heartbeat-paced write to
        # persistent device config was in flight.
        #
        # This was the only real quit path to guard: main_window.py's
        # closeEvent() only hides to tray (setQuitOnLastWindowClosed(False)
        # in app.py), it never quits on its own.
        if self.main_window._syncing:
            if not self.main_window._confirm(
                "Sync in progress",
                "A sync to the controller is still running. Quitting now may leave "
                "a partial write on persistent device config.\n\nQuit anyway?",
            ):
                return
        QApplication.instance().quit()
