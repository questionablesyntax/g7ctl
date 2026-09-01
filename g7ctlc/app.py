"""QApplication bootstrap: wires the device watcher, main window, and tray
icon together.

Closing the window hides it rather than quitting (tray-app behavior) --
use the tray menu's Quit to actually exit.
"""
import ctypes
import logging
import sys

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__
from .main_window import MainWindow
from .theme import STYLESHEET
from .tray import TrayIcon
from .watcher import DeviceWatcher

# Matches packaging/g7ctlc.desktop's filename (without the
# extension). Without this, Qt/KWin identify the window/app_id as just
# "python3" (the interpreter running us via `python3 -m g7ctlc`) --
# too generic for window manager rules, taskbar grouping, or alt-tab to
# target reliably, since it'd match literally any Python script.
DESKTOP_FILE_NAME = "g7ctlc"


def _rename_process(name: str = DESKTOP_FILE_NAME) -> None:
    """Set the kernel `comm` name so window managers identify us correctly.

    KWin (and others) derive a window's class from the process's comm name,
    which QApplication.setDesktopFileName() alone doesn't control. Without
    this the app shows up as "python3", so any KWin Window Rule written for
    it matches every Python process on the system.

    Lives here rather than only in the ./g7ctlc launcher script so
    the installed `g7ctlc` console entry point gets it too --
    otherwise desktop integration would silently depend on which of the two
    ways you happened to start the app.

    Best-effort and Linux-only; purely cosmetic, so failures are ignored.
    """
    try:
        libc = ctypes.CDLL(None)
        PR_SET_NAME = 15
        libc.prctl(PR_SET_NAME, name.encode() + b"\0", 0, 0, 0)
    except Exception:
        pass


def main() -> int:
    # The protocol library and the watcher thread report progress through
    # logging rather than print(). Send it to stderr with the logger name
    # attached -- unlike the CLI, here the records come from a background
    # thread and knowing which component spoke is worth the extra prefix.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    _rename_process()

    app = QApplication(sys.argv)
    app.setApplicationName("G7 Control Center")
    app.setApplicationVersion(__version__)
    # Not a real company -- just the string Qt attaches to
    # QStandardPaths/QSettings' default config-file location and surfaces in
    # a few desktop-integration spots (e.g. some window managers' app info).
    # Previously unset entirely.
    app.setOrganizationName("questionablesyntax")
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        logging.warning("no system tray available on this session -- "
                        "connection state is still visible in the main window.")
    tray = TrayIcon(window)
    tray.show()

    thread = QThread()
    watcher = DeviceWatcher()
    watcher.moveToThread(thread)
    thread.started.connect(watcher.run)
    watcher.state_changed.connect(tray.set_state)
    watcher.state_changed.connect(window.set_connection_state)
    window.syncing_changed.connect(tray.set_syncing)
    watcher.error.connect(window.set_error)
    watcher.sync_progress.connect(window.set_sync_progress)
    watcher.sync_finished.connect(window.set_sync_finished)
    watcher.read_finished.connect(window.set_read_finished)
    watcher.battery_changed.connect(window.set_battery)
    watcher.battery_unknown.connect(window.clear_battery)
    watcher.firmware_known.connect(window.set_firmware)
    watcher.active_profile_changed.connect(window.set_active_profile)

    def _on_release_toggled(release: bool) -> None:
        (watcher.pause if release else watcher.resume)()

    window.release_toggled.connect(_on_release_toggled)
    tray.release_toggled.connect(_on_release_toggled)

    def _on_sync_requested(state: dict) -> None:
        # Plain function, not a bound method of `watcher` -- watcher.run() is
        # a blocking loop that never pumps a Qt event queue on its own
        # thread, so connecting straight to a QObject method living there
        # would silently never get dispatched (a queued call needs the
        # receiving thread's event loop running to deliver it). Routing
        # through a plain closure forces a direct call instead, same as
        # pause()/resume() above -- safe here since request_sync() just does
        # a thread-safe queue.Queue.put().
        watcher.request_sync(state)

    window.sync_requested.connect(_on_sync_requested)

    def _on_read_requested(slot: int) -> None:
        # Same reasoning as _on_sync_requested above.
        watcher.request_read(slot)

    window.read_requested.connect(_on_read_requested)

    def _shutdown() -> None:
        window.save_geometry()
        watcher.stop()
        thread.quit()
        # watcher.stop() only sets a flag checked at the top of run()'s
        # loop -- if the watcher thread is currently inside a sync's
        # write_state() call (many small, individually-paced USB writes;
        # plausibly several seconds for a full profile, longer still if a
        # baseline-read timeout forced a full write), the flag isn't seen
        # until that call returns. 2000ms was tight enough to plausibly
        # time out mid-write and let the process tear down with the
        # watcher thread -- and its open USB session -- still running.
        # Widened to give a real in-flight sync a fair chance to finish;
        # still bounded, so a genuinely stuck thread can't hang shutdown
        # forever. Real fix would be confirming with the user before
        # quitting at all while a sync is in flight (the same pattern
        # Sync Now itself already asks for) -- flagged, not done here:
        # that needs restructuring how tray.py's Quit action reaches
        # MainWindow's own _syncing flag, out of scope for just widening
        # this window. At minimum, don't fail silently if it's still not
        # enough.
        if not thread.wait(10_000):
            logging.warning("watcher thread did not stop within 10s of "
                             "quitting -- it may have been mid-write to "
                             "persistent device config when the app exited.")

    app.aboutToQuit.connect(_shutdown)
    thread.start()

    return app.exec()
