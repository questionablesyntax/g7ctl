"""QApplication bootstrap: wires the device watcher, main window, and tray
icon together.

Closing the window hides it rather than quitting (tray-app behavior) --
use the tray menu's Quit to actually exit.
"""
import argparse
import ctypes
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import __version__
from .main_window import MainWindow
from .theme import STYLESHEET
from .tray import TrayIcon
from .watcher import DeviceWatcher

# Same XDG_CONFIG_HOME convention main_window.py's _GEOMETRY_PATH already
# uses -- one config directory for this app, not a second convention for
# the log file.
_LOG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "g7ctl" / "g7ctlc.log"
)
# Placeholder, not measured against real debug-level chattiness over a
# real session -- starting point per DEBUGGING-INFRA-PLAN-2026-09-01.md,
# revisit if it turns out too small (truncates useful history) or too
# large (unbounded growth was the thing worth avoiding in the first
# place).
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3

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


def _parse_args(argv: list) -> argparse.Namespace:
    """`-v`/`--verbose` only -- parse_known_args() so Qt's own flags
    (-style, -platform, ...) pass through untouched to QApplication(sys.argv)
    below rather than being rejected as unrecognized by this parser."""
    parser = argparse.ArgumentParser(prog="g7ctlc", add_help=True)
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Log at DEBUG level instead of INFO, in both the log file and stderr -- "
             "diagnostic detail not needed for normal use, but worth attaching to a "
             "bug report alongside the log file itself. See also `g7ctl diag`.")
    args, _unknown = parser.parse_known_args(argv)
    return args


def _configure_logging(verbose: bool) -> None:
    """Stderr always (matches the pre-2026-09-01 behavior, since a
    terminal launch should still see it live); a rotating file always too
    -- the GUI has no visible console for the normal desktop-icon launch
    path, so without a durable file, raising the level here doesn't
    actually help anyone but a user who happened to launch from a
    terminal and think to redirect it. See DEBUGGING-INFRA-PLAN-2026-09-01.md.
    """
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            _LOG_PATH, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT))
    except OSError:
        # Best-effort: a log file this process can't create (read-only
        # home, permissions, disk full) must not stop the app from
        # launching at all -- stderr alone still works, same as before
        # this existed. Logged once the (stderr-only) handler is in place
        # below, not raised.
        logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
        logging.warning("could not open log file %s -- logging to stderr only", _LOG_PATH,
                        exc_info=True)
        return
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)


def _install_crash_hook(main_window: "MainWindow") -> None:
    """A slot exception -- same-thread or the watcher thread's own
    cross-thread queued signals alike -- does NOT abort this app on the
    installed PyQt6 version (6.11.0): confirmed empirically 2026-09-01
    (both shapes tested directly, not assumed from documentation -- see
    DEBUGGING-INFRA-PLAN-2026-09-01.md's phase 3), not just hoped for.
    Qt's own default handling already prints a traceback and keeps the
    event loop running; what's missing without this is a durable record
    of it anywhere -- the default traceback only ever reaches whatever
    terminal happened to launch this, invisible on the normal
    desktop-icon launch path and gone the moment that terminal closes.

    Installed once real app state exists (main_window, for a dialog
    parent) -- not around QApplication's own construction, which fails
    fast and is already visible via stderr/the log immediately.
    """
    previous_hook = sys.excepthook

    def _hook(exc_type: type, exc_value: BaseException, exc_tb) -> None:
        logging.critical(
            "Unhandled exception in a Qt slot -- the app is still running, "
            "but this specific action may not have completed. Log file: %s",
            _LOG_PATH, exc_info=(exc_type, exc_value, exc_tb))
        previous_hook(exc_type, exc_value, exc_tb)
        _show_crash_dialog(main_window, exc_type, exc_value)

    sys.excepthook = _hook


def _show_crash_dialog(parent, exc_type: type, exc_value: BaseException) -> None:
    QMessageBox.critical(
        parent, "Something went wrong",
        f"{exc_type.__name__}: {exc_value}\n\n"
        "The app is still running, but this specific action may not have "
        f"completed. Details were written to {_LOG_PATH} -- "
        "attach it if you use Help → Report an Issue.")


def main() -> int:
    args = _parse_args(sys.argv[1:])
    # The protocol library and the watcher thread report progress through
    # logging rather than print(). Includes the logger name -- unlike the
    # CLI, here the records come from a background thread and knowing
    # which component spoke is worth the extra prefix.
    _configure_logging(args.verbose)
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
    _install_crash_hook(window)

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
