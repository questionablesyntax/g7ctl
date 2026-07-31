"""The vendor-mode USB session: claim/release, heartbeat, raw packet send."""
import logging
import time
from typing import Any, Optional

import usb.core
import usb.util

from .constants import (
    CMD_HEARTBEAT,
    CMD_READ,
    EP_IN,
    EP_OUT,
    IFACE,
    READ_CHUNK_LENGTH,
    READ_RESPONSE_MARKER,
    READ_SUBCOMMAND,
    REPORT_ID_READ_RESPONSE,
)

log = logging.getLogger(__name__)


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


def profile_layer_byte(profile: int = 1, shift: bool = False) -> int:
    """Encodes BOTH the target profile (1-4) and the layer (Default/Shift)
    into one byte, used by the Buttons category's write prefix:
    byte = profile + (4 if shift else 0).

    Confirmed: profile1+default=0x01, profile2+default=0x02, profile1+shift=
    0x05. Profiles 3/4 and shift for profiles 2-4 follow the same formula but
    aren't independently confirmed.

    Sticks/Triggers/Vibration/Report Rate do NOT use this combined byte --
    they carry a plain profile number (1-4) in their own prefix's middle
    byte instead (see constants.py's prefix_sticks()/
    prefix_triggers_vibration()). Both schemes target a profile explicitly,
    so no category depends on which profile is physically active. Confirmed
    2026-07-28; see PROTOCOL.md "Profile scoping".
    """
    if not 1 <= profile <= 4:
        raise ValueError("profile must be 1-4")
    return profile + (4 if shift else 0)


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
