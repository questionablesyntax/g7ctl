"""Background device watcher: owns the connect/handshake/heartbeat loop on a
worker thread (via moveToThread in app.py, not a QThread subclass) so
blocking pyusb calls never touch the GUI thread.

A write with no heartbeat before/after gets silently discarded by the
firmware (see pyg7/session.py), so once connected this owns exactly
one long-lived VendorSession heartbeating continuously; request_sync()
queues a state dict to push, request_read() queues a controller slot to
read back -- both run on this same loop/session rather than opening a
separate session per request.

pause()/resume() let the GUI explicitly release the controller back to
XInput mode (stopping heartbeats lets the firmware revert on its own --
see the "isolated write ... device reverts to XInput almost instantly"
note in g7ctl/main.py) without quitting the app or having the watcher
immediately re-grab it on the next poll.
"""
import logging
import queue
import time
from typing import Optional

import usb.core
from PyQt6.QtCore import QObject, pyqtSignal

from pyg7 import state as state_mod
from pyg7.constants import PID_XINPUT
from pyg7.device import enter_vendor_mode, find_device, find_native_identity, find_writable_device
from pyg7.session import VendorSession

log = logging.getLogger(__name__)

POLL_INTERVAL = 1.0        # how often to check for the device while disconnected
HEARTBEAT_INTERVAL = 0.25  # matches the app's observed heartbeat cadence while connected


class DeviceWatcher(QObject):
    state_changed = pyqtSignal(str)  # "disconnected" | "connecting" | "connected" | "paused" | "no_controller"
    error = pyqtSignal(str)
    sync_progress = pyqtSignal(int, int, str)  # step, total, label
    sync_finished = pyqtSignal(bool, str)      # success, message
    read_finished = pyqtSignal(bool, str, object)  # success, message, state dict or None

    def __init__(self) -> None:
        super().__init__()
        self._stop = False
        self._paused = False
        self._jobs = queue.Queue()  # ("sync", state_dict) or ("read", slot)
        self._state = "disconnected"
        self._last_error = None
        # Dock settings are device-global (see state_mod.read_state()'s
        # `include_dock` docstring) -- nothing can change them just because
        # a different profile got selected or a read got repeated on this
        # same live connection, so only the first _do_read() per connection
        # actually fetches them. Reset on every fresh _connect() (a *new*
        # connection is still worth one real dock read, in case something
        # changed while disconnected).
        self._dock_known = False

    def request_sync(self, state: dict) -> None:
        """Thread-safe: call from the GUI thread. Applied on this loop's
        session the next time it's free (between heartbeats), never opening
        a separate session for the sync."""
        self._jobs.put(("sync", state))

    def request_read(self, slot: int) -> None:
        """Thread-safe: call from the GUI thread. Reads Profile `slot`'s
        current button bindings back from the device on this loop's
        session the next time it's free -- see pyg7.state.read_state()."""
        self._jobs.put(("read", slot))

    def pause(self) -> None:
        """Thread-safe: call from the GUI thread. Releases the session and
        stops auto-reconnecting until resume() is called. Dropping the
        heartbeat is what lets the controller leave config mode and go back
        to being a gamepad -- on the dongle as much as on the cable, since
        the dongle only bridges the same session through. The visible
        difference is USB-side: wired, the device re-enumerates from 109b
        back to 100a; over the dongle the PID never changes."""
        self._paused = True

    def resume(self) -> None:
        """Thread-safe: call from the GUI thread."""
        self._paused = False

    def stop(self) -> None:
        self._stop = True

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _emit_error(self, message: str) -> None:
        """Dedupe against the last error so a persistent condition (e.g. no
        udev permission) doesn't spam one emission per poll cycle."""
        if message != self._last_error:
            self._last_error = message
            self.error.emit(message)

    def run(self) -> None:
        """Blocking loop -- call this after moveToThread(worker_thread) via
        worker_thread.started.connect(watcher.run)."""
        session = None
        try:
            while not self._stop:
                if self._paused:
                    if session is not None:
                        self._teardown(session)
                        session = None
                    self._set_state("paused")
                    time.sleep(POLL_INTERVAL)
                    continue

                if session is None:
                    try:
                        session = self._establish()
                    except usb.core.USBError as exc:
                        self._emit_error(f"USB error: {exc}")
                        session = None
                    if session is None:
                        time.sleep(POLL_INTERVAL)
                        continue

                try:
                    self._drain_jobs(session)
                    session.heartbeat()
                    time.sleep(HEARTBEAT_INTERVAL)
                except usb.core.USBError as exc:
                    self._emit_error(f"Lost connection: {exc}")
                    self._teardown(session)
                    session = None
                    self._set_state("disconnected")
        finally:
            if session is not None:
                self._teardown(session)

    def _drain_jobs(self, session: VendorSession) -> None:
        try:
            kind, payload = self._jobs.get_nowait()
        except queue.Empty:
            return

        if kind == "sync":
            self._do_sync(session, payload)
        elif kind == "read":
            self._do_read(session, payload)

    def _do_sync(self, session: VendorSession, state: dict) -> None:
        """Reads a fresh baseline from the device first (rsync-style: diff
        against live destination state, not a stale cache) and only writes
        Buttons bindings that actually differ from it -- see
        state_mod.write_state()'s `baseline` param. If the read itself
        fails for a reason short of losing the connection outright (e.g. a
        read_chunk() timeout), falls back to a full write rather than
        aborting the sync -- a real USBError is treated as connection loss
        either way and aborts, matching every other write path here."""
        def on_progress(i, total, label):
            self.sync_progress.emit(i, total, label)

        baseline = None
        slot = state.get("controller_slot") or 1
        try:
            self.sync_progress.emit(0, 0, "Reading current device state…")
            baseline = state_mod.read_state(session, slot=slot)
        except usb.core.USBError as exc:
            self.sync_finished.emit(False, f"Lost connection during sync: {exc}")
            raise  # let the caller's disconnect handling tear the session down
        except Exception as exc:
            # No baseline -- write_state() below just writes everything. Print
            # rather than stay fully silent: a read failure here is usually a
            # flaky connection (seen in practice: a bad cable/port producing
            # USB protocol errors and dropped packets, not a code bug),
            # and it's worth a trace to tell the two apart.
            log.warning("baseline read failed, falling back to full write: %r", exc)
            baseline = None

        try:
            skipped = state_mod.write_state(session, state, on_progress=on_progress, baseline=baseline)
            if baseline is None:
                self.sync_finished.emit(True, "State applied (full write -- no baseline read).")
            else:
                self.sync_finished.emit(True, f"State applied ({skipped} binding(s) already matched, skipped).")
        except usb.core.USBError as exc:
            self.sync_finished.emit(False, f"Lost connection during sync: {exc}")
            raise  # let the caller's disconnect handling tear the session down
        except Exception as exc:
            self.sync_finished.emit(False, f"Sync failed: {exc}")

    def _do_read(self, session: VendorSession, slot: int) -> None:
        # Only the first read per connection pays for the dock-settings
        # blob -- see __init__'s `_dock_known` comment and
        # state_mod.read_state()'s `include_dock` docstring. Every read
        # after that (profile switches especially) skips it; MainWindow's
        # merge logic keeps whatever dock values it already has when this
        # comes back None.
        include_dock = not self._dock_known
        try:
            state = state_mod.read_state(session, slot=slot, include_dock=include_dock)
            self._dock_known = True
            self.read_finished.emit(True, f"Read current bindings from Profile {slot}.", state)
        except usb.core.USBError as exc:
            self.read_finished.emit(False, f"Lost connection during read: {exc}", None)
            raise  # let the caller's disconnect handling tear the session down
        except Exception as exc:
            self.read_finished.emit(False, f"Read failed: {exc}", None)

    def _establish(self) -> Optional[VendorSession]:
        """Wraps _connect() with the warmup + liveness check every fresh
        session needs before it's safe to call "connected". Returns the
        ready-to-use session, or None (having already set the right state)
        if either step fails.

        Splitting this out of run()'s loop body -- rather than setting
        "connected" the instant _connect() returns, as before -- exists
        because settle()/the liveness probe below need to happen first.
        """
        session = self._connect()
        if session is None:
            return None

        # Warm the session up before any queued job can issue a read -- see
        # VendorSession.settle(). Lived directly in run() as _settle() until
        # it turned out the CLI needed the exact same protection.
        session.settle()

        if session.via_dongle and not session.probe_controller_live():
            # Raised 2026-07-30 from real daily use: the dongle enumerates
            # on USB (and claims, and heartbeats fine) whether or not a
            # physical controller is actually powered on and paired to it --
            # they're two separate things joined by an RF link. Without this
            # check the watcher reported "connected" here regardless, and
            # every subsequent read/write just failed. Tear down and keep
            # polling -- this recovers on its own once a controller answers,
            # no different from any other disconnected-and-waiting state.
            # See VendorSession.probe_controller_live() for what this can't
            # tell apart (powered off vs. unpaired vs. possibly switched to
            # its native GameSir identity mid-session).
            self._teardown(session)
            self._set_state("no_controller")
            return None

        self._set_state("connected")
        self._last_error = None
        self._dock_known = False  # a fresh connection earns one real dock read
        return session

    def _connect(self) -> Optional[VendorSession]:
        vdev, via_dongle = find_writable_device()
        if vdev is not None:
            return self._open_session(vdev, via_dongle)

        xdev = find_device(PID_XINPUT)
        if xdev is None:
            # Distinguish "genuinely not connected" from "connected, but in
            # the native GameSir identity this tool can't talk to yet" --
            # see PID_NATIVE's comment in constants.py. _emit_error() already
            # dedupes against the last message, so this won't spam once per
            # poll cycle while the user's deciding what to do.
            if find_native_identity() is not None:
                self._emit_error(
                    "Controller is in its native GameSir identity, not XInput "
                    "mode. Hold Menu+Share on the controller to switch back."
                )
            return None

        self._set_state("connecting")
        vdev = enter_vendor_mode()
        if vdev is None:
            self._set_state("disconnected")
            return None
        return self._open_session(vdev, via_dongle=False)

    @staticmethod
    def _open_session(vdev: usb.core.Device, via_dongle: bool) -> VendorSession:
        session = VendorSession(vdev, via_dongle=via_dongle)
        session.__enter__()
        return session

    @staticmethod
    def _teardown(session: VendorSession) -> None:
        try:
            session.__exit__(None, None, None)
        except Exception:
            pass
