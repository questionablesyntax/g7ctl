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
from pyg7.device import (
    HANDSHAKE_MIN_INTERVAL,
    find_hid_device,
    find_native_identity,
    find_writable_device,
    switch_to_xid,
)
from pyg7.session import VendorSession

log = logging.getLogger(__name__)

POLL_INTERVAL = 1.0        # how often to check for the device while disconnected
HEARTBEAT_INTERVAL = 0.25  # matches the app's observed heartbeat cadence while connected

# How long to hold off re-establishing after a failed liveness probe, rather
# than retrying at the normal POLL_INTERVAL cadence.
#
# Raised 2026-08-30 from real daily use, the day after probe_controller_live()
# became unconditional (2026-08-29 detection redesign): a controller landing
# from PID_HID sometimes re-enumerated an extra time or two on its own during
# the settle/probe window, and once visibly hit the same fault this project's
# own churn testing associates with the rapid-re-enumeration wedge (a
# vibration alert plus a re-enumeration) -- it didn't wedge that time, but
# retrying a fresh claim/settle/probe cycle every single POLL_INTERVAL while
# the device is still doing that on its own is exactly the kind of added
# re-enumeration-adjacent activity HANDSHAKE_MIN_INTERVAL already exists to
# pace against for handshake sends specifically. This covers the other path
# that pacing doesn't: re-establishing on an already-baseline device needs no
# handshake at all, so it never went through _pace_handshake(). Reuses
# HANDSHAKE_MIN_INTERVAL's own value rather than inventing a second pacing
# constant -- same reasoning, same firmware behavior being paced against.
PROBE_FAILURE_BACKOFF = HANDSHAKE_MIN_INTERVAL

# How often to sample battery off the input stream. Charge moves on the scale
# of minutes, so this is deliberately lazy -- the cost is not the read (frames
# are already arriving; the first one returns almost immediately) but the risk
# of stalling the heartbeat loop, which is what keeps the session alive.
BATTERY_POLL_INTERVAL = 30.0
# Short on purpose, and much tighter than READ_CHUNK_TIMEOUT. A missed battery
# sample is worth nothing; a heartbeat gap long enough for the firmware to end
# the session costs the whole thing. Timeouts here are swallowed, not raised.
BATTERY_READ_TIMEOUT = 0.3

# The active profile changes only when the user presses a combo on the pad,
# so this is polled lazily too -- but faster than battery, since seeing a
# stale profile indicator right after switching is exactly the confusion
# this is meant to remove.
ACTIVE_PROFILE_INTERVAL = 5.0
ACTIVE_PROFILE_TIMEOUT = 0.5


class DeviceWatcher(QObject):
    state_changed = pyqtSignal(str)  # "disconnected" | "connecting" | "connected" | "paused" | "no_controller"
    error = pyqtSignal(str)
    sync_progress = pyqtSignal(int, int, str)  # step, total, label
    sync_finished = pyqtSignal(bool, str)      # success, message
    read_finished = pyqtSignal(bool, str, object)  # success, message, state dict or None
    # percent, charging. Emitted only when the reading changes, so the GUI
    # thread isn't woken every poll to repaint an identical label.
    battery_changed = pyqtSignal(int, bool)
    # No battery reading available (disconnected, or the stream went quiet).
    battery_unknown = pyqtSignal()
    # Firmware version string, read once per connection (it cannot change
    # while the device is attached).
    firmware_known = pyqtSignal(str)
    # Which profile the controller is physically on, 1-4. Polled, because
    # unlike firmware it changes -- the user can switch it on the pad at any
    # time with M+Y/B/A/X.
    active_profile_changed = pyqtSignal(int)

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
        self._firmware_done = False
        self._active_due = 0.0
        self._active_last = None
        self._battery_due = 0.0   # monotonic deadline for the next sample
        self._battery_last = None  # (percent, charging), for change-only emits
        self._probe_backoff_until = 0.0  # see PROBE_FAILURE_BACKOFF

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
        heartbeat is what lets the controller leave its claimed session and
        go back to being a plain gamepad -- on the dongle as much as on the
        cable, since the dongle only bridges the same session through.

        Whether a re-enumeration rides along with that release follows the
        same rule as everywhere else in this project: interface presence
        tracks current bind content, and a re-enumeration only fires when
        reality needs to change to match it. A session that started at
        PID_HID (100a) and still needs HID on release re-enumerates back to
        it; one that never needed HID doesn't move.

        Corrected 2026-08-29 -- this docstring used to claim "over the
        dongle the PID never changes" on release. Wrong: switch_to_xid()'s
        own docstring already documents an idle dongle sitting at 100a and
        re-enumerating to 109c on handshake, so the same round trip should
        mirror coming back out. The wired direction of that round trip is
        directly confirmed; the dongle side is inferred from the same rule,
        not independently tested (hardware currently unavailable) -- see
        PROTOCOL.md's "Wireless dongle" row and FINDINGS.md's still-open
        list."""
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
                        # Drain any job queued before pause() landed --
                        # otherwise it's silently dropped and whoever's
                        # waiting on sync_finished/read_finished (MainWindow's
                        # _syncing flag) never hears back at all, stuck
                        # disabled until an app restart. Real bug, found
                        # 2026-09-01: pause() can land in the up-to-
                        # HEARTBEAT_INTERVAL window between a job being
                        # queued and this loop's next iteration -- e.g.
                        # clicking Release Device right after Sync Now --
                        # and the old code tore the session down here
                        # without ever checking the queue.
                        try:
                            self._drain_jobs(session)
                        except usb.core.USBError as exc:
                            # _do_sync()/_do_read() already emitted their own
                            # *_finished(False, ...) before re-raising this --
                            # same contract the normal (non-paused) path
                            # below relies on. _teardown() right after is
                            # already exception-safe against a session that's
                            # effectively dead at this point.
                            self._emit_error(f"Lost connection: {exc}")
                        self._teardown(session)
                        session = None
                        self._forget_battery()
                    self._set_state("paused")
                    time.sleep(POLL_INTERVAL)
                    continue

                if session is None:
                    # See PROBE_FAILURE_BACKOFF -- skip attempting a fresh
                    # claim entirely while still cooling down from a failed
                    # liveness probe, rather than retrying every
                    # POLL_INTERVAL while the device may still be
                    # re-enumerating on its own.
                    if time.time() < self._probe_backoff_until:
                        time.sleep(POLL_INTERVAL)
                        continue
                    try:
                        session = self._establish()
                    except usb.core.USBError as exc:
                        self._emit_error(f"USB error: {exc}")
                        session = None
                        # Same reasoning as PROBE_FAILURE_BACKOFF -- any
                        # USBError surfacing here (not just the errno-19
                        # case probe_controller_live() already handles
                        # itself) is just as plausibly re-enum-related, so
                        # back off the same way rather than retrying
                        # immediately.
                        self._probe_backoff_until = time.time() + PROBE_FAILURE_BACKOFF
                    if session is None:
                        time.sleep(POLL_INTERVAL)
                        continue

                try:
                    self._drain_jobs(session)
                    session.heartbeat()
                    self._read_firmware_once(session)
                    self._poll_active_profile(session)
                    self._poll_battery(session)
                    time.sleep(HEARTBEAT_INTERVAL)
                except usb.core.USBError as exc:
                    self._emit_error(f"Lost connection: {exc}")
                    self._teardown(session)
                    session = None
                    self._forget_battery()
                    self._set_state("disconnected")
                    # Same reasoning as PROBE_FAILURE_BACKOFF, and likely the
                    # actual dominant path for it in practice (real
                    # 2026-08-30 capture: a sustained 100a<->109b
                    # oscillation, 6 re-enum events across ~36s, polled
                    # externally) -- if a session that started on
                    # HID-needing content loses its heartbeat here, tearing
                    # down releases it, which round-trips it straight back
                    # to PID_HID (confirmed release behavior, see
                    # pause()'s own docstring above). Reconnecting
                    # immediately just re-sends the handshake into that and
                    # repeats the cycle. Back off before retrying, same as
                    # the establish-time failure.
                    self._probe_backoff_until = time.time() + PROBE_FAILURE_BACKOFF
        finally:
            if session is not None:
                self._teardown(session)
            self._forget_battery()

    def _forget_battery(self) -> None:
        """Drop the cached reading when the session goes away.

        Without this, a charge level from a previous connection would sit on
        screen looking live -- and the change-only emit in _poll_battery()
        would suppress the identical value on reconnect, so a stale number
        could outlive several sessions. Also clears the poll deadline so a
        fresh connection samples immediately rather than up to
        BATTERY_POLL_INTERVAL later.
        """
        self._battery_due = 0.0
        self._active_due = 0.0
        self._active_last = None
        self._firmware_done = False
        if self._battery_last is not None:
            self._battery_last = None
            self.battery_unknown.emit()

    def _read_firmware_once(self, session: VendorSession) -> None:
        """Read the firmware version a single time per connection.

        Unlike battery this is not polled: it cannot change while the device
        is attached, and every extra device-info query is a command on a
        channel where unsupported selectors are known to end the session.
        One failure is not retried for the same reason -- the version is
        cosmetic and not worth spending commands on.
        """
        if self._firmware_done:
            return
        self._firmware_done = True
        try:
            info = session.read_firmware_version(timeout=1.0)
        except usb.core.USBError:
            raise
        except Exception as exc:
            log.debug("firmware read skipped: %r", exc)
            return
        if info.controller:
            self.firmware_known.emit(info.controller)

    def _poll_active_profile(self, session: VendorSession) -> None:
        """Sample the active profile, at most every ACTIVE_PROFILE_INTERVAL.

        Polled rather than read once: the user can change it on the pad at
        any moment. Same failure policy as battery -- everything short of a
        real USBError is swallowed, because a stale profile indicator is not
        worth tearing down a working session for.
        """
        now = time.monotonic()
        if now < self._active_due:
            return
        self._active_due = now + ACTIVE_PROFILE_INTERVAL
        try:
            value = session.read_active_profile(timeout=ACTIVE_PROFILE_TIMEOUT)
        except usb.core.USBError:
            raise
        except Exception as exc:
            log.debug("active-profile sample skipped: %r", exc)
            return
        if value != self._active_last:
            self._active_last = value
            self.active_profile_changed.emit(value)

    def _poll_battery(self, session: VendorSession) -> None:
        """Sample charge off the input stream, at most every
        BATTERY_POLL_INTERVAL seconds.

        Deliberately the least intrusive read in this loop. It issues no
        command -- the device pushes these frames unprompted while a session
        is open (PROTOCOL.md "Battery level") -- so unlike a config read it
        cannot contribute to the CMD_READ wedge, and it adds nothing to the
        bus.

        Every failure short of a real USBError is swallowed. A missed sample
        just leaves the last reading on screen; raising here would tear down
        a perfectly good session over a cosmetic label. USBError is left to
        propagate because that genuinely is connection loss, which the run
        loop already handles.
        """
        now = time.monotonic()
        if now < self._battery_due:
            return
        self._battery_due = now + BATTERY_POLL_INTERVAL
        try:
            status = session.read_battery(timeout=BATTERY_READ_TIMEOUT)
        except usb.core.USBError:
            raise
        except Exception as exc:
            # Includes TimeoutError (stream quiet this instant) and
            # ValueError (a frame whose battery byte is out of range).
            log.debug("battery sample skipped: %r", exc)
            return
        reading = (status.percent, status.charging)
        if reading != self._battery_last:
            self._battery_last = reading
            self.battery_changed.emit(status.percent, status.charging)

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

        try:
            # Warm the session up before any queued job can issue a read --
            # see VendorSession.settle(). Lived directly in run() as
            # _settle() until it turned out the CLI needed the exact same
            # protection.
            session.settle()

            if not session.probe_controller_live():
                # Raised 2026-07-30 from real daily use: the dongle
                # enumerates on USB (and claims, and heartbeats fine)
                # whether or not a physical controller is actually powered
                # on and paired to it -- they're two separate things joined
                # by an RF link. Without this check the watcher reported
                # "connected" here regardless, and every subsequent
                # read/write just failed. Tear down and keep polling -- this
                # recovers on its own once a controller answers, no
                # different from any other disconnected-and-waiting state.
                # Runs unconditionally now (2026-08-29 detection redesign)
                # rather than gated on session.via_dongle -- that flag is
                # cosmetic-only as of this redesign. See
                # VendorSession.probe_controller_live() for what this can't
                # tell apart (powered off vs. unpaired vs. possibly switched
                # to its native GameSir identity mid-session).
                self._teardown(session)
                self._set_state("no_controller")
                # See PROBE_FAILURE_BACKOFF: a failure here can mean the
                # device is still re-enumerating on its own (real
                # 2026-08-30 finding, not the "harmless extra read" this
                # was assumed to be the day before) -- back off before
                # run() tries to re-establish, rather than retrying a fresh
                # claim every POLL_INTERVAL while that's still settling.
                self._probe_backoff_until = time.time() + PROBE_FAILURE_BACKOFF
                return None
        except usb.core.USBError:
            # Real bug, found 2026-09-01 (second bug-hunt pass): a
            # USBError raised by settle()/probe_controller_live() itself
            # (not just probe_controller_live() returning False, already
            # handled above) used to propagate straight out of this
            # method with the interface still claimed and the kernel
            # driver still detached -- run()'s own except block only ever
            # discards its local `session` reference, it never gets a
            # chance to tear down the actual object this method created.
            # The next claim attempt could then fail as "device busy"
            # (interface still held by the leaked session), turning a
            # transient bus blip into a stuck disconnected state until
            # the whole USB device is replugged or the process restarts.
            # The caller still needs to see this exception for its own
            # error reporting/backoff, so clean up here and re-raise.
            self._teardown(session)
            raise

        self._set_state("connected")
        self._last_error = None
        self._dock_known = False   # a fresh connection earns one real dock read
        self._firmware_done = False
        self._active_due = 0.0
        self._active_last = None
        self._battery_due = 0.0    # monotonic deadline for the next sample
        self._battery_last = None  # (percent, charging), for change-only emits
        return session

    def _connect(self) -> Optional[VendorSession]:
        vdev, via_dongle = find_writable_device()
        if vdev is not None:
            return self._open_session(vdev, via_dongle)

        # find_hid_device(), not a bare find_device(PID_HID) -- a real gap
        # fixed 2026-08-29: on firmware/variant combinations where the HID
        # interface presents at what's otherwise the baseline PID (already
        # seen in the wild: Tri-mode, ZZZ), a literal PID_HID check finds
        # nothing even though the controller genuinely needs a handshake.
        # The CLI's own connect path already used the thorough check;
        # this brings the GUI in line.
        xdev = find_hid_device()
        if xdev is None:
            # Distinguish "genuinely not connected" from "connected, but in
            # the native GameSir identity this tool can't talk to yet" --
            # see PID_NATIVE's comment in variants.py. _emit_error() already
            # dedupes against the last message, so this won't spam once per
            # poll cycle while the user's deciding what to do.
            if find_native_identity() is not None:
                self._emit_error(
                    "Controller is in its native GameSir identity, not XInput "
                    "mode. Hold Menu+Share on the controller to switch back."
                )
            return None

        self._set_state("connecting")
        vdev, via_dongle = switch_to_xid()
        if vdev is None:
            self._set_state("disconnected")
            return None
        # via_dongle came from the handshake's landing PID, not hardcoded
        # False as it was until 2026-08-01 -- a dongle reached this way got
        # the tighter wired timeouts and skipped the liveness probe.
        return self._open_session(vdev, via_dongle=via_dongle)

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
