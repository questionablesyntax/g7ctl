"""The vendor-mode USB session: claim/release, heartbeat, raw packet send."""
import logging
import time
from typing import Any, NamedTuple, Optional

import usb.core
import usb.util

from .constants import (
    BATTERY_CHARGING_OFFSET,
    BATTERY_MAX,
    BATTERY_OFFSET,
    CMD_DEVICE_INFO,
    CMD_HEARTBEAT,
    CMD_READ,
    EP_IN,
    EP_OUT,
    IFACE,
    INFO_ACTIVE_PROFILE,
    INFO_FIRMWARE,
    INPUT_FRAME_MARKER,
    PROFILE_MAX,
    PROFILE_MIN,
    READ_CHUNK_LENGTH,
    READ_RESPONSE_MARKER,
    READ_SUBCOMMAND,
    REPORT_ID_READ_RESPONSE,
)

log = logging.getLogger(__name__)


class FirmwareInfo(NamedTuple):
    """What CMD_DEVICE_INFO's firmware selector returns.

    `controller` is the parsed version of the first 4-digit group and is
    confirmed against real hardware. `raw` is the whole string and `groups`
    its 4-digit pieces, both carried through undecoded -- newer firmware
    returns more than one group and what the extras mean is not established.
    """
    controller: "Optional[str]"
    raw: str
    groups: tuple


class BatteryStatus(NamedTuple):
    """Charge as reported in the input stream.

    `charging` was briefly shipped as `at_full`, on capture evidence alone:
    the flag read 1 in every sub-100 capture and 0 at exactly 100, which fits
    "not full" and "charging" equally well, because every sub-100 capture in
    the corpus happened to be taken plugged in. The first live read settled
    it in one shot -- 46% over the wireless dongle, on battery, flag 0. "Not
    full" predicts 1 there and is dead; charging predicts 0 and holds for all
    three cases, including a plugged-in 100% reading 0 once charge completes.
    """
    percent: int
    charging: bool


# Warmup pacing for a freshly-claimed session -- see VendorSession.settle().
# 12 x 0.25s (~3s) is what empirically cleared the errno-19 disconnect on a
# just-re-enumerated device; the GUI's older 5-beat value was enough for its
# own slower connect path but not for a CLI invocation that reads immediately.
SETTLE_HEARTBEATS = 12
SETTLE_INTERVAL = 0.25

# Wireless dongle relaxation -- raised 2026-07-30 from real daily use: the
# link through the dongle (controller -> RF -> dongle -> USB) is an extra
# hop the wired path doesn't have, and the first read_chunk() right after
# connecting is the one most often seen timing out over the dongle
# specifically. Doubling both the settle warmup and the default read
# timeout is a judgment call, not a measured minimum -- there's no hard
# data pinning the exact number needed, just that the wired defaults were
# observed to be occasionally too tight for the dongle. Cheap to relax
# further later if this still isn't enough.
SETTLE_HEARTBEATS_DONGLE = 24
READ_CHUNK_TIMEOUT = 2.0
READ_CHUNK_TIMEOUT_DONGLE = 4.0


# The Shift layer's category. ONE byte, for the whole device -- the Shift
# layer is not profile-scoped. See profile_layer_byte() for the evidence.
SHIFT_CATEGORY = 0x05


def profile_layer_byte(profile: int = 1, shift: bool = False) -> int:
    """The Buttons category's write prefix byte.

    Default layer: the profile number, 0x01-0x04.
    Shift layer:   always 0x05, whatever `profile` says.

    **The Shift layer is device-global.** There is exactly one, shared by
    all four profiles -- the same relationship dock settings have to
    profiles (see dock_settings.py), and the reason `profile` is ignored
    when `shift` is set rather than being an error: a caller asking for
    "profile 3's Shift layer" is asking for the only Shift layer there is,
    and gets it.

    This was originally written as `profile + (4 if shift else 0)`, which
    predicts 0x06/0x07/0x08 for Profiles 2-4. Those categories do not exist.
    The firmware does not reject them either -- it falls back to Profile 1's
    Default-layer blob, so a Shift write aimed at Profile 4 *modified
    Profile 1's Default layer* (hardware-confirmed: remapping Y on category
    0x08 changed Profile 1 at offset 0x90 and nothing else). Reads fell back
    identically, which is why a write-then-read-back test could never catch
    it: both halves of the loop were redirected to the same blob.

    Evidence the single Shift layer is global, not Profile 1's (2026-08-07):

    - All 256 category bytes return exactly six distinct blobs: 0x01-0x04,
      0x05, and 0x20 (dock). The other 250 return blob 1.
    - GameSir Nexus reads exactly those same six and has never emitted
      0x06/0x07/0x08 in any capture we hold.
    - In a capture of Nexus switching profile tabs with no edit, it reads
      the profile's own blob, then **0x05 in full, then dock** -- fetching
      0x05 while displaying Profile 4. That is the shared-resource pattern
      dock already follows, not a per-profile one.
    - Switching the active profile on the controller does not change what
      0x05 returns (byte-identical across a switch to Profile 2, verified
      behaviourally rather than assumed).
    - Confirmed in Nexus directly: a Shift binding set on Profile 1's tab
      appears on Profile 2's tab. Nexus shows a Shift section under every
      profile, which is why per-profile Shift layers are widely assumed --
      but the storage underneath is this one blob.

    Sticks/Triggers/Vibration/Report Rate do NOT use this combined byte --
    they carry a plain profile number (1-4) in their own prefix's middle
    byte instead (see constants.py's prefix_sticks()/
    prefix_triggers_vibration()). Both schemes target a profile explicitly,
    so no category depends on which profile is physically active. Confirmed
    2026-07-28; see PROTOCOL.md "Profile scoping".
    """
    if not 1 <= profile <= 4:
        raise ValueError("profile must be 1-4")
    return SHIFT_CATEGORY if shift else profile


class VendorSession:
    """A claimed USB interface on the vendor-mode device.

    IMPORTANT: writes sent with no heartbeat before/after appear to get
    silently discarded by the firmware -- the device reverts to XInput mode
    almost instantly and the change doesn't stick. Callers should send a few
    heartbeats before and after any write (see cli.py's *_HEARTBEATS/INTERVAL
    pattern), not send an isolated write in isolation.
    """

    def __init__(self, dev: usb.core.Device, via_dongle: bool = False):
        self.dev = dev
        self.via_dongle = via_dongle
        self.seq = 0
        self._claimed = False
        self._detached = False

    def __enter__(self) -> "VendorSession":
        if self.dev.is_kernel_driver_active(IFACE):
            self.dev.detach_kernel_driver(IFACE)
            self._detached = True
        usb.util.claim_interface(self.dev, IFACE)
        self._claimed = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._claimed:
            try:
                usb.util.release_interface(self.dev, IFACE)
            except Exception as e:
                # Not fatal on its own (the device may already be gone), but
                # per device.py's logging philosophy this shouldn't vanish
                # with zero trace anywhere.
                log.debug("release_interface failed: %s", e)
        if self._detached:
            try:
                self.dev.attach_kernel_driver(IFACE)
            except Exception as e:
                log.debug("attach_kernel_driver failed: %s", e)

    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) % 256
        return self.seq

    def send_raw(self, cmd_byte: int, payload: bytes) -> bytes:
        # Every category module funnels through this one call, so this bound
        # is the whole library's actual invariant, not just a guard on the
        # CLI's `raw` escape hatch. Without it, an oversized payload silently
        # grows the bytearray past 64 bytes via slice assignment instead of
        # failing -- producing an undefined-behavior packet on the wire
        # rather than a clean rejection.
        if len(payload) > 60:
            raise ValueError(f"payload too long: {len(payload)} bytes, max 60 (4-byte header + payload = 64)")
        pkt = bytearray(64)
        pkt[0] = 0x0f
        pkt[1] = 0x00
        pkt[2] = self._next_seq()
        pkt[3] = cmd_byte
        pkt[4:4 + len(payload)] = payload
        self.dev.write(EP_OUT, bytes(pkt))
        return bytes(pkt)

    def heartbeat(self) -> bytes:
        return self.send_raw(CMD_HEARTBEAT, bytes([0xf2, 0x00]))

    def settle(self, count: Optional[int] = None, interval: float = SETTLE_INTERVAL) -> None:
        """Warm up a freshly-claimed session before issuing any non-heartbeat
        command. Call this once, right after entering the session.

        A newly-claimed (especially a newly-re-enumerated) device accepts
        heartbeats immediately but is NOT yet ready to service CMD_READ.
        Two independent confirmations:

        - 2026-07-27, GUI: main_window's auto-read-on-connect fires the
          instant the watcher reports "connected" and hit read_chunk()'s
          timeout on the very first chunk, while the connection itself
          stayed up.
        - 2026-07-28, CLI: read_state() issued straight after
          enter_vendor_mode() failed harder still -- USBError errno 19, the
          device dropping off the bus entirely mid-read. The same read run
          after ~3s of settle heartbeats completed all 4 profiles on the
          first attempt with no errors.

        This was previously implemented only inside the GUI's DeviceWatcher,
        which left every other caller (the CLI included) unprotected. It
        lives here now so warmup is a property of the session, not of one
        consumer that happened to get bitten first.

        `count` defaults to `SETTLE_HEARTBEATS_DONGLE` over the dongle and
        `SETTLE_HEARTBEATS` wired -- the extra RF hop the dongle adds was
        observed (real daily use, 2026-07-30) to make the first read after
        connecting time out more often than wired. Pass an explicit `count`
        to override either way.
        """
        if count is None:
            count = SETTLE_HEARTBEATS_DONGLE if self.via_dongle else SETTLE_HEARTBEATS
        for _ in range(count):
            self.heartbeat()
            time.sleep(interval)

    def read_blob(self, category: int, length: int, interval: float = 0.05) -> bytes:
        """Read `length` bytes of `category`'s config blob from offset 0,
        chunked into READ_CHUNK_LENGTH-sized reads with the final chunk
        sized to land exactly on `length` -- matches the real app's observed
        chunking for a full 480-byte blob (8x55 + one 40-byte remainder, see
        PROTOCOL.md "Reading current config"); other lengths use the same
        pattern, confirmed 2026-07-27 via direct testing (Sticks/Triggers/
        Vibration offset mapping) reading the full 480 bytes this way.
        Sends a heartbeat after each chunk, matching the heartbeat-per-write
        pattern writes need (not independently confirmed reads need it too,
        but not worth risking)."""
        blob = bytearray()
        offset = 0
        while offset < length:
            chunk_len = min(READ_CHUNK_LENGTH, length - offset)
            blob.extend(self.read_chunk(category, offset, chunk_len))
            self.heartbeat()
            time.sleep(interval)
            offset += chunk_len
        return bytes(blob)

    def read_live_suffix(self, profile: int, storage_offset: int, length: int,
                          interval: float = 0.05) -> bytes:
        """Read `length` live bytes starting just after `storage_offset`.

        The Deadzone/Anti-deadzone settings use a "long form" write: a big
        payload whose trailing bytes land on storage the setting doesn't
        conceptually own. Sending a suffix captured from some earlier session
        therefore stomps whatever currently lives there -- confirmed to
        include the Curve preset's stored shape data (Sticks) and the side's
        own LT/RT keycode byte (Triggers). Reading the span back immediately
        before each write carries the current contents forward instead,
        which generalises past the two specific fields we catalogued: it
        preserves whatever occupies that span, whether or not we've
        identified it.

        Lived as an identical private `_live_suffix()` in both sticks.py
        and triggers.py before moving here -- it's a session operation, and
        "Swap Left Stick and D-pad" (dpad_options.py) needs the very same
        call. See PROTOCOL.md "Sticks" for the corruption this prevents.
        """
        category = profile_layer_byte(profile, shift=False)
        live = self.read_chunk(category, storage_offset + 1, length)
        self.heartbeat()
        time.sleep(interval)
        return live

    def read_chunk(self, category: int, offset: int, length: int = READ_CHUNK_LENGTH,
                    timeout: Optional[float] = None) -> bytes:
        """Read `length` bytes of `category`'s config blob starting at
        `offset` (see PROTOCOL.md "Reading current config"). `category`
        uses the same profile_layer_byte() scheme as Buttons writes.

        The response comes back on REPORT_ID_READ_RESPONSE, sharing its
        endpoint with an unrelated continuous analog-telemetry stream --
        this reads IN reports until one's echoed [CMD_READ, category,
        offset_hi, offset_lo, length] matches what was requested (the
        response echoes CMD_READ itself but NOT the READ_SUBCOMMAND byte),
        discarding anything else (telemetry frames, or a stale response to
        an earlier request).

        `timeout` defaults to `READ_CHUNK_TIMEOUT_DONGLE` over the dongle
        and `READ_CHUNK_TIMEOUT` wired -- same reasoning as `settle()`'s
        dongle-aware default. Pass an explicit value to override either way.
        """
        if timeout is None:
            timeout = READ_CHUNK_TIMEOUT_DONGLE if self.via_dongle else READ_CHUNK_TIMEOUT
        if not 0 <= offset <= 0xFFFF:
            raise ValueError("offset must fit in 16 bits")
        req_payload = bytes([READ_SUBCOMMAND, category, (offset >> 8) & 0xFF, offset & 0xFF, length])
        self.send_raw(CMD_READ, req_payload)

        echo = bytes([CMD_READ, category, (offset >> 8) & 0xFF, offset & 0xFF, length])
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"no response to read_chunk(category={category:#04x}, offset={offset:#06x}, "
                    f"length={length}) within {timeout}s")
            try:
                report = bytes(self.dev.read(EP_IN, 64, timeout=max(1, int(remaining * 1000))))
            except usb.core.USBError as e:
                if getattr(e, "errno", None) in (110, None) or "timeout" in str(e).lower():
                    continue
                raise
            if (len(report) >= 4 + len(echo) + length
                    and report[0] == REPORT_ID_READ_RESPONSE
                    and report[3] == READ_RESPONSE_MARKER
                    and report[4:4 + len(echo)] == echo):
                return report[4 + len(echo):4 + len(echo) + length]

    def read_input_frame(self, timeout: Optional[float] = None) -> bytes:
        """Return one frame of the device's own input stream.

        While a vendor session is open the device pushes these unprompted on
        REPORT_ID_READ_RESPONSE, sharing that report ID with CMD_READ's
        answers and distinguished by byte 4 (see PROTOCOL.md "The input
        stream on report `0x10`"). Nothing is sent to obtain one -- this only
        reads, so unlike read_chunk() it issues no command at all.

        Raises TimeoutError if no input frame arrives in `timeout`.
        """
        if timeout is None:
            timeout = READ_CHUNK_TIMEOUT_DONGLE if self.via_dongle else READ_CHUNK_TIMEOUT
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"no input frame within {timeout}s")
            try:
                report = bytes(self.dev.read(EP_IN, 64, timeout=max(1, int(remaining * 1000))))
            except usb.core.USBError as e:
                if getattr(e, "errno", None) in (110, None) or "timeout" in str(e).lower():
                    continue
                raise
            if (len(report) > BATTERY_OFFSET
                    and report[0] == REPORT_ID_READ_RESPONSE
                    and report[3] == READ_RESPONSE_MARKER
                    and report[4] == INPUT_FRAME_MARKER):
                return report

    def read_battery(self, timeout: Optional[float] = None) -> "BatteryStatus":
        """Current charge, read straight off the input stream.

        No query exists for this and none is sent -- the value simply rides
        in the frames the device is already pushing (PROTOCOL.md "Battery
        level"). That makes this the cheapest read in the library: no bus
        traffic beyond the heartbeats already holding the session open, and
        no CMD_READ, which is the command implicated in the firmware wedge.

        Raises TimeoutError if no input frame arrives, and ValueError if one
        does but carries an out-of-range percentage -- better to fail loudly
        than to report a plausible-looking wrong charge.
        """
        frame = self.read_input_frame(timeout=timeout)
        percent = frame[BATTERY_OFFSET]
        if percent > BATTERY_MAX:
            raise ValueError(
                f"battery byte out of range: {percent} > {BATTERY_MAX}. "
                "Either the input frame layout changed or this is not an input frame.")
        return BatteryStatus(percent=percent, charging=frame[BATTERY_CHARGING_OFFSET] == 1)

    def read_device_info(self, selector: int, timeout: Optional[float] = None) -> bytes:
        """Raw payload of a CMD_DEVICE_INFO answer (everything after byte 4).

        **Byte 4 is an echo of `selector + 1`, not a length.** Both known
        selectors confirm it -- `0x09` answers `0x0a`, `0x0b` answers `0x0c`
        -- and it does not track payload size: it reads `0x0a` for the
        8-byte firmware string in the July captures and the same `0x0a` for
        today's 16-byte one. Reading it as a length silently truncates.
        Callers get the whole payload region and decide where their own data
        ends.

        **Only pass selectors known to be supported.** An unsupported one
        drops the device out of vendor mode within seconds -- a clean revert
        to PID_XINPUT rather than the CMD_READ wedge, so it recovers in
        software, but it ends the session. See PROTOCOL.md "Device info".
        """
        if timeout is None:
            timeout = READ_CHUNK_TIMEOUT_DONGLE if self.via_dongle else READ_CHUNK_TIMEOUT
        self.send_raw(CMD_DEVICE_INFO, bytes([selector]))
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"no answer to device-info selector {selector:#04x} within {timeout}s")
            try:
                report = bytes(self.dev.read(EP_IN, 64, timeout=max(1, int(remaining * 1000))))
            except usb.core.USBError as e:
                if getattr(e, "errno", None) in (110, None) or "timeout" in str(e).lower():
                    continue
                raise
            # Same report ID as read responses and the input stream; byte 4
            # is a length here rather than an echoed command or the input
            # marker, so both of those have to be excluded explicitly.
            if (len(report) >= 6
                    and report[0] == REPORT_ID_READ_RESPONSE
                    and report[3] == READ_RESPONSE_MARKER
                    and report[4] != INPUT_FRAME_MARKER
                    and report[4] != CMD_READ
                    and report[4] == (selector + 1) & 0xFF):
                return report[5:]

    def read_firmware_version(self, timeout: Optional[float] = None) -> "FirmwareInfo":
        """The controller's firmware version, e.g. "2.4.4".

        The device answers with a UTF-16LE string of 4-digit groups. The
        first group is the controller's firmware and is confirmed: `"0244"`
        against a controller reading v2.4.4, and `"0209"` in captures from
        when it ran v2.0.9.

        Later groups are NOT decoded here, only carried through in `raw`.
        A v2.4.4 controller reached over the dongle answers `"02440152"`,
        and `0152` is also exactly the dongle's `bcdDevice` -- so the second
        group is plausibly the dongle's own firmware, but "plausibly" is not
        good enough to put a number in front of a user. The July captures,
        on older firmware, returned the first group alone.
        """
        payload = self.read_device_info(INFO_FIRMWARE, timeout=timeout)
        # UTF-16LE, NUL-terminated. Length has to come from the terminator
        # because byte 4 is a selector echo, not a length -- see
        # read_device_info(). Trim to an even byte count first so a stray
        # trailing byte can't produce a replacement char.
        text = payload[:len(payload) & ~1].decode("utf-16-le", "replace").split("\x00")[0]
        groups = [text[i:i + 4] for i in range(0, len(text), 4)]
        first = groups[0] if groups else ""
        # "0244" -> "2.4.4". The leading character is padding in both known
        # samples. This cannot express a component above 9, so a future
        # v2.10.0 would have to encode some other way -- return the raw
        # string unparsed rather than inventing a version if it doesn't fit.
        if len(first) == 4 and first.isdigit():
            controller = f"{int(first[1])}.{int(first[2])}.{int(first[3])}"
        else:
            controller = None
        return FirmwareInfo(controller=controller, raw=text, groups=tuple(groups))

    def read_active_profile(self, timeout: Optional[float] = None) -> int:
        """Which profile the controller is physically on, 1-4.

        Not stored in any config blob -- it is device state, and this is the
        channel the device uses to describe itself. Every category targets a
        profile explicitly, so nothing in this library *depends* on the
        active profile; this exists so a UI can stop implying the user is
        editing the profile they are playing on when they are not.

        Raises ValueError on anything outside 1-4 rather than passing a
        nonsense profile number to a caller that will use it to address
        writes.
        """
        payload = self.read_device_info(INFO_ACTIVE_PROFILE, timeout=timeout)
        value = payload[0] if payload else None
        if value is None or not PROFILE_MIN <= value <= PROFILE_MAX:
            raise ValueError(
                f"active profile out of range: {value!r} (expected {PROFILE_MIN}-{PROFILE_MAX}). "
                "Either the device-info layout changed or this is not the active-profile field.")
        return value

    def probe_controller_live(self, timeout: Optional[float] = None) -> bool:
        """Is there an actual controller answering on the other end, not just
        a claimable USB device?

        Raised 2026-07-30 from real dongle use: the 2.4GHz dongle (PID_DONGLE)
        enumerates on USB, and is fully claimable, whether or not a physical
        controller is powered on and paired to it -- the dongle chip and the
        controller are two separate things joined by an RF link, not one USB
        device. `find_writable_device()`/`enter_vendor_mode()` only prove the
        *dongle* is there; heartbeats succeed too, since those are one-way
        writes with no reply to check. None of that proves a controller is
        actually on the other end -- only a real CMD_READ does, since it
        requires an actual response.

        Wired mode doesn't need this: PID_VENDOR is the controller's own USB
        descriptor, so its mere presence already proves the controller itself
        is there. Callers should only bother calling this when
        `self.via_dongle` is true.

        Returns True if a minimal read succeeds, False on timeout (no
        controller answering -- could be powered off, unpaired, or possibly
        switched to its native GameSir identity mid-session (see PROTOCOL.md
        "Device identities"); this can't tell those apart, only that nothing
        answered). A real USBError (the dongle itself vanishing) is not
        caught here -- that's a different, harder failure the caller's
        existing USBError handling already covers.
        """
        try:
            self.read_chunk(profile_layer_byte(1), 0, 1, timeout=timeout)
            return True
        except TimeoutError:
            return False
