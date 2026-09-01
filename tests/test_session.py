"""VendorSession.send_raw() framing tests.

Every category module funnels its writes through this one method, so its
framing invariants (fixed 64-byte packet, incrementing sequence byte) matter
project-wide, not just for the CLI's `raw` escape hatch that exercises it
most directly.
"""
import unittest

from pyg7.constants import CMD_HEARTBEAT, CMD_WRITE
from pyg7.session import (
    READ_CHUNK_TIMEOUT,
    SETTLE_HEARTBEATS,
    VendorSession,
)


class _FakeDevice:
    """Stands in for the pyusb Device -- just records what .write() got."""

    def __init__(self):
        self.written = []

    def write(self, endpoint, data):
        self.written.append((endpoint, bytes(data)))
        return len(data)


class SendRawTest(unittest.TestCase):
    def setUp(self):
        self.dev = _FakeDevice()
        self.sess = VendorSession(self.dev)

    def test_packet_is_always_64_bytes(self):
        self.sess.send_raw(0x3C, bytes([1, 2, 3]))
        _endpoint, sent = self.dev.written[0]
        self.assertEqual(len(sent), 64)

    def test_header_and_payload_placement(self):
        self.sess.send_raw(0x3C, bytes([0xAA, 0xBB]))
        _endpoint, sent = self.dev.written[0]
        self.assertEqual(sent[0], 0x0F)   # fixed report ID
        self.assertEqual(sent[1], 0x00)   # fixed
        self.assertEqual(sent[3], 0x3C)   # CMD
        self.assertEqual(sent[4:6], bytes([0xAA, 0xBB]))

    def test_sequence_increments_and_wraps(self):
        for _ in range(3):
            self.sess.send_raw(0x02, b"")
        seqs = [sent[2] for _endpoint, sent in self.dev.written]
        self.assertEqual(seqs, [1, 2, 3])

    def test_rejects_a_60_byte_payload_boundary(self):
        # 60 bytes of payload + 4-byte header = exactly one 64-byte packet --
        # the largest a real write (Swap Left Stick and D-pad's long form)
        # actually sends. Must succeed.
        self.sess.send_raw(0x3C, bytes(60))
        self.assertEqual(len(self.dev.written), 1)

    def test_rejects_an_oversized_payload(self):
        # Regression: send_raw() used to slice-assign the payload into a
        # fixed 64-byte bytearray with no length check at all, so an
        # oversized payload silently grew the buffer past 64 bytes instead
        # of failing -- an undefined-behavior packet on the wire rather than
        # a clean rejection. Every category module funnels through this
        # method, so this is a whole-library invariant, not just a guard on
        # the CLI's `raw` escape hatch.
        with self.assertRaises(ValueError):
            self.sess.send_raw(0x3C, bytes(61))
        self.assertEqual(self.dev.written, [])  # must fail before ever writing


class SendAddressedTest(unittest.TestCase):
    """VendorSession.send_addressed() -- added 2026-09-01 after a real bug:
    Right Trigger's curve block (setting_id 0xF8, 10 bytes of data) spans
    0xF8..0x101, crossing the 0xFF/0x100 page boundary that plain
    send_raw()-based callers were assuming couldn't happen. See
    pyg7.curves.curve_point_payloads()'s own comment for the hardware
    capture this reproduces.
    """

    def setUp(self):
        self.dev = _FakeDevice()
        self.sess = VendorSession(self.dev)

    def test_non_crossing_write_is_a_single_packet_unchanged(self):
        # setting_id 0x44 (Left Stick's curve) + 10 bytes stays well under
        # 0x100 -- must behave exactly like a plain send_raw() call, one
        # packet, no heartbeat.
        prefix = bytes([0x03, 0x01, 0x00])
        data = bytes(range(10))
        self.sess.send_addressed(prefix, 0x44, data)
        self.assertEqual(len(self.dev.written), 1)
        _endpoint, sent = self.dev.written[0]
        self.assertEqual(sent[4:7], prefix)
        self.assertEqual(sent[7], 0x44)         # setting_id
        self.assertEqual(sent[8], len(data))    # LEN, derived not hardcoded
        self.assertEqual(sent[9:19], data)

    def test_crossing_write_splits_at_the_page_boundary_with_a_heartbeat_between(self):
        # Right Trigger's curve: setting_id 0xF8, 10 bytes of data
        # (index, scale, origin x2, P1 x2, P2 x2, P3 x2) -- P3 specifically
        # lands past 0xFF. Uses real hardware-confirmed P3 bytes (e4 82)
        # from the 2026-08-08 capture (test62): dragging Right Trigger's
        # third curve point emitted `03 01 01 00 02 e4 82` on the wire --
        # page 1, offset 0x00, a 2-byte payload. This test reproduces that
        # exact second packet, not just a plausible-looking one.
        prefix = bytes([0x03, 0x01, 0x00])   # profile 1, page 0
        index, scale = 0x03, 0x64
        origin = bytes([0x00, 0x00])
        p1, p2, p3 = bytes([0x28, 0x29]), bytes([0x80, 0x80]), bytes([0xE4, 0x82])
        data = bytes([index, scale]) + origin + p1 + p2 + p3
        self.assertEqual(len(data), 10)

        self.sess.send_addressed(prefix, 0xF8, data, interval=0)

        # 3 packets: write, heartbeat, write -- a real heartbeat is required
        # between the two writes (CURVE_POINT_WRITE_INTERVAL's own comment:
        # an unpaced second write right behind the first gets silently
        # dropped on real hardware), so send_addressed() must send one, not
        # just sleep.
        self.assertEqual(len(self.dev.written), 3)
        cmd_bytes = [sent[3] for _endpoint, sent in self.dev.written]
        self.assertEqual(cmd_bytes, [CMD_WRITE, CMD_HEARTBEAT, CMD_WRITE])

        _e1, first = self.dev.written[0]
        self.assertEqual(first[4:7], prefix)          # still page 0
        self.assertEqual(first[7], 0xF8)               # setting_id, unchanged
        self.assertEqual(first[8], 8)                   # LEN: only 8 bytes fit before 0x100
        self.assertEqual(first[9:17], data[:8])

        _e2, second = self.dev.written[2]
        self.assertEqual(second[4:6], prefix[:2])       # same category/profile
        self.assertEqual(second[6], 0x01)               # page incremented 0 -> 1
        self.assertEqual(second[7], 0x00)               # address resets to 0 on the new page
        self.assertEqual(second[8], 2)                  # LEN: the 2 bytes that didn't fit
        self.assertEqual(second[9:11], data[8:])         # P3's own bytes: e4 82
        self.assertEqual(bytes(second[6:11]), bytes([0x01, 0x00, 0x02, 0xE4, 0x82]))

    def test_deadzone_max_crossing_case_also_splits_correctly(self):
        # A second real crossing case, independent of the curve one:
        # setting_id 0xEC (Right Trigger deadzone_max) + 21 bytes (a
        # 1-byte value plus a 20-byte live-read suffix) spans 0xEC..0x101.
        prefix = bytes([0x03, 0x02, 0x00])   # profile 2, page 0
        data = bytes([0x32]) + bytes(range(20))  # value=0x32 + 20-byte suffix
        self.assertEqual(0xEC + len(data), 0x101)

        self.sess.send_addressed(prefix, 0xEC, data, interval=0)

        self.assertEqual(len(self.dev.written), 3)  # write, heartbeat, write
        cmd_bytes = [sent[3] for _endpoint, sent in self.dev.written]
        self.assertEqual(cmd_bytes, [CMD_WRITE, CMD_HEARTBEAT, CMD_WRITE])

        _e1, first = self.dev.written[0]
        self.assertEqual(first[7], 0xEC)
        self.assertEqual(first[8], 20)          # 0x100 - 0xEC = 20 bytes fit
        self.assertEqual(first[9:29], data[:20])

        _e2, second = self.dev.written[2]
        self.assertEqual(second[6], 0x01)       # page incremented
        self.assertEqual(second[7], 0x00)       # address resets
        self.assertEqual(second[8], 1)          # 1 remaining byte
        self.assertEqual(second[9], data[20])


class _FakeReadDevice(_FakeDevice):
    """Adds a scriptable .read() on top of _FakeDevice, so read_chunk()-level
    behavior (timeouts, dongle-aware defaults) can be tested without a real
    USB device. `responses` is a queue of either a raw report (bytes) to
    return, or an exception instance to raise -- consumed one per .read()
    call; once exhausted, keeps raising the last exception (or a timeout
    USBError) so a test doesn't need to size the queue exactly.
    """

    def __init__(self, responses=None):
        super().__init__()
        self._responses = list(responses or [])
        self.read_timeouts = []

    def read(self, endpoint, size, timeout=None):
        self.read_timeouts.append(timeout)
        if self._responses:
            item = self._responses.pop(0)
        else:
            import usb.core
            item = usb.core.USBError("timed out")
        if isinstance(item, Exception):
            raise item
        return item


def _read_response_report(category: int, offset: int, length: int, data: bytes) -> bytes:
    """Builds a REPORT_ID_READ_RESPONSE packet read_chunk() will accept for
    the given request, matching session.py's own framing."""
    from pyg7.constants import CMD_READ, READ_RESPONSE_MARKER, REPORT_ID_READ_RESPONSE
    echo = bytes([CMD_READ, category, (offset >> 8) & 0xFF, offset & 0xFF, length])
    pkt = bytearray(64)
    pkt[0] = REPORT_ID_READ_RESPONSE
    pkt[3] = READ_RESPONSE_MARKER
    pkt[4:4 + len(echo)] = echo
    pkt[4 + len(echo):4 + len(echo) + len(data)] = data
    return bytes(pkt)


class ConnectionAgnosticDefaultsTest(unittest.TestCase):
    """Raised 2026-07-30 from real daily use: the dongle's extra RF hop was
    seen making the first read after connecting time out more often than
    wired, so VendorSession used to scale its settle warmup and
    read_chunk's default timeout based on via_dongle. Redesigned
    2026-08-29: real wired/dongle detection turned out not to be possible
    at all (GameSir's own compiled firmware gives both an identical
    descriptor shape -- see pyg7/device.py's module docstring), so guessing
    was retired in favor of always using the more patient values,
    regardless of via_dongle. These pin that the default really is the
    same either way now, not just that the constants exist."""

    def test_settle_heartbeat_count_same_regardless_of_via_dongle(self):
        wired = VendorSession(_FakeDevice(), via_dongle=False)
        wired.settle(interval=0)
        dongle = VendorSession(_FakeDevice(), via_dongle=True)
        dongle.settle(interval=0)
        # send_raw increments seq once per heartbeat -- count them via seq.
        self.assertEqual(wired.seq, SETTLE_HEARTBEATS)
        self.assertEqual(dongle.seq, SETTLE_HEARTBEATS)

    def test_settle_explicit_count_overrides_default(self):
        sess = VendorSession(_FakeDevice(), via_dongle=True)
        sess.settle(count=3, interval=0)
        self.assertEqual(sess.seq, 3)

    def test_read_chunk_timeout_same_regardless_of_via_dongle(self):
        for via_dongle in (False, True):
            with self.subTest(via_dongle=via_dongle):
                dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00")])
                sess = VendorSession(dev, via_dongle=via_dongle)
                sess.read_chunk(1, 0, 1)
                # read_chunk passes timeout in milliseconds (derived from a
                # deadline, so a slice of a millisecond of real elapsed time
                # between setting it and computing `remaining` is expected
                # slop, not a bug).
                self.assertAlmostEqual(dev.read_timeouts[-1], int(READ_CHUNK_TIMEOUT * 1000), delta=5)

    def test_read_chunk_explicit_timeout_overrides_default(self):
        dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00")])
        sess = VendorSession(dev, via_dongle=True)
        sess.read_chunk(1, 0, 1, timeout=0.5)
        self.assertAlmostEqual(dev.read_timeouts[-1], 500, delta=5)


class ProbeControllerLiveTest(unittest.TestCase):
    """VendorSession.probe_controller_live() -- the fix for the dongle
    reporting "connected" even when the physical controller behind it is
    off or unpaired -- the dongle is a separate USB device from the
    controller, joined only by an RF link, and enumerates and heartbeats
    fine on its own regardless of whether a controller is on the other end.

    Also covers a second failure mode found live 2026-08-30, one day after
    this became an unconditional check (2026-08-29 detection redesign):
    errno 19 specifically, on a wired connection fresh off a handshake
    re-enumeration, gets treated the same as a timeout rather than raised.
    """

    def test_true_when_a_real_read_succeeds(self):
        dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00")])
        sess = VendorSession(dev, via_dongle=True)
        self.assertTrue(sess.probe_controller_live(timeout=0.05))

    def test_false_on_timeout_no_response_ever_arrives(self):
        dev = _FakeReadDevice([])  # every .read() times out immediately
        sess = VendorSession(dev, via_dongle=True)
        self.assertFalse(sess.probe_controller_live(timeout=0.05))

    def test_errno_19_is_treated_like_a_timeout_not_raised(self):
        # Caught live, 2026-08-30 (the very next day after this became an
        # unconditional check): a WIRED connection fresh off a handshake-
        # triggered re-enumeration occasionally hit real errno 19 (ENODEV)
        # on exactly this read -- the same "not fully settled yet" quirk
        # settle() already exists to cover, just never previously exercised
        # here since wired connections never ran a forced read at this
        # exact point before. Must return False, the same graceful path a
        # timeout already takes, not raise and force a harder failure path.
        import usb.core
        exc = usb.core.USBError("no such device")
        exc.errno = 19
        dev = _FakeReadDevice([exc])
        sess = VendorSession(dev, via_dongle=False)
        self.assertFalse(sess.probe_controller_live(timeout=0.05))

    def test_other_usb_errors_still_propagate(self):
        # A genuine, different USBError (a permission error, the dongle
        # itself vanishing for some other reason) is still a harder failure
        # than "no controller answering yet" -- the caller's existing
        # USBError handling covers that, so only errno 19 specifically
        # gets swallowed, not USBError as a whole.
        import usb.core
        exc = usb.core.USBError("access denied")
        exc.errno = 13
        dev = _FakeReadDevice([exc])
        sess = VendorSession(dev, via_dongle=True)
        with self.assertRaises(usb.core.USBError):
            sess.probe_controller_live(timeout=0.05)


def _input_frame(percent: int, flag: int = 1, sticks: bytes = b"\x80\x80\x80\x80") -> bytes:
    """An input-stream frame carrying `percent` at BATTERY_OFFSET.

    Mirrors the real framing: report 0x10, marker at byte 3, and byte 4 set
    to INPUT_FRAME_MARKER rather than a CMD_READ echo -- that byte is the
    only thing distinguishing this from a read response on the same pipe.
    """
    from pyg7.constants import (
        BATTERY_CHARGING_OFFSET,
        BATTERY_OFFSET,
        INPUT_FRAME_MARKER,
        READ_RESPONSE_MARKER,
        REPORT_ID_READ_RESPONSE,
    )
    pkt = bytearray(64)
    pkt[0] = REPORT_ID_READ_RESPONSE
    pkt[3] = READ_RESPONSE_MARKER
    pkt[4] = INPUT_FRAME_MARKER
    pkt[5:9] = sticks
    pkt[BATTERY_CHARGING_OFFSET] = flag
    pkt[BATTERY_OFFSET] = percent
    return bytes(pkt)


class BatteryTest(unittest.TestCase):
    """Battery rides in the input stream (PROTOCOL.md "Battery level").

    The percentages here are the ones the corpus actually pins: captures
    test55/56 were taken while Nexus displayed 98%, and test57 -- the
    capture that falsified the *previous* battery theory -- displayed 99%.
    """

    def test_reads_percentage_from_the_input_stream(self):
        dev = _FakeReadDevice([_input_frame(99)])
        status = VendorSession(dev).read_battery(timeout=0.5)
        self.assertEqual(status.percent, 99)

    def test_sends_nothing_at_all(self):
        # The point of this decode: no query exists and none is issued. That
        # is what makes battery safe to poll -- it never emits CMD_READ, the
        # command implicated in the firmware wedge.
        dev = _FakeReadDevice([_input_frame(98)])
        VendorSession(dev).read_battery(timeout=0.5)
        self.assertEqual(dev.written, [])

    def test_skips_read_responses_sharing_the_pipe(self):
        # A read response and an input frame arrive on the same report ID,
        # distinguished only by byte 4. Returning the wrong one would decode
        # config bytes as a charge level.
        dev = _FakeReadDevice([
            _read_response_report(1, 0, 1, b"\x00"),
            _input_frame(98),
        ])
        self.assertEqual(VendorSession(dev).read_battery(timeout=0.5).percent, 98)

    def test_battery_is_independent_of_stick_position(self):
        # Verified against the corpus: test64's 29,602 frames all have the
        # sticks off-centre and byte 33 is constant throughout. The original
        # capture filter matched only centred sticks, which would have hidden
        # a positional dependency had one existed.
        dev = _FakeReadDevice([_input_frame(97, sticks=b"\x00\xff\x12\xee")])
        self.assertEqual(VendorSession(dev).read_battery(timeout=0.5).percent, 97)

    def test_charging_flag(self):
        # Live hardware, 2026-08-12: 46% over the wireless dongle with the
        # flag at 0. That one reading killed the "not full" reading this
        # shipped with for an hour -- not full predicts 1 at 46%.
        self.assertTrue(VendorSession(_FakeReadDevice([_input_frame(98, flag=1)]))
                        .read_battery(timeout=0.5).charging)
        self.assertFalse(VendorSession(_FakeReadDevice([_input_frame(46, flag=0)]))
                         .read_battery(timeout=0.5).charging)

    def test_rejects_an_impossible_percentage(self):
        # Byte 33 never exceeded 0x64 across 212,917 corpus frames. If it
        # ever does, the layout changed -- fail loudly rather than report a
        # plausible-looking wrong charge.
        dev = _FakeReadDevice([_input_frame(101)])
        with self.assertRaises(ValueError):
            VendorSession(dev).read_battery(timeout=0.5)

    def test_times_out_when_no_input_frame_arrives(self):
        dev = _FakeReadDevice([])
        with self.assertRaises(TimeoutError):
            VendorSession(dev).read_battery(timeout=0.05)


if __name__ == "__main__":
    unittest.main()


def _info_report(selector: int, payload: bytes) -> bytes:
    """A CMD_DEVICE_INFO answer.

    Byte 4 is `selector + 1`, an echo -- NOT a length. Confirmed on both
    known selectors, and it stays 0x0a for the firmware string whether that
    string is 8 bytes (July captures) or 16 (current firmware). Building the
    fake this way is the point: an earlier version of this helper wrote a
    real length there, which let a parser that truncated on it pass.
    """
    from pyg7.constants import READ_RESPONSE_MARKER, REPORT_ID_READ_RESPONSE
    pkt = bytearray(64)
    pkt[0] = REPORT_ID_READ_RESPONSE
    pkt[3] = READ_RESPONSE_MARKER
    pkt[4] = (selector + 1) & 0xFF
    pkt[5:5 + len(payload)] = payload
    return bytes(pkt)


def _fw(text: str) -> bytes:
    from pyg7.constants import INFO_FIRMWARE
    # NUL-terminated, like the device: the terminator is the only thing that
    # marks where the string ends.
    return _info_report(INFO_FIRMWARE, text.encode("utf-16-le") + b"\x00\x00")


class FirmwareVersionTest(unittest.TestCase):
    """CMD_DEVICE_INFO selector 0x09 -- the controller's firmware version.

    Both literals here are real: "0209" is what every July capture returned
    (the controller ran v2.0.9 then) and "02440152" is what the same
    controller returned live once it was on v2.4.4, confirmed against the
    version shown on the device itself.
    """

    def test_parses_the_confirmed_value(self):
        dev = _FakeReadDevice([_fw("02440152")])
        self.assertEqual(VendorSession(dev).read_firmware_version().controller, "2.4.4")

    def test_parses_the_older_single_group_form(self):
        dev = _FakeReadDevice([_fw("0209")])
        info = VendorSession(dev).read_firmware_version()
        self.assertEqual(info.controller, "2.0.9")
        self.assertEqual(info.groups, ("0209",))

    def test_extra_groups_are_carried_but_not_decoded(self):
        # The second group is NOT the dongle's firmware: this project's own
        # reference dongle reports v2.0.9 while this field reads 0152. It
        # matches bcdDevice instead. Carried through raw rather than labelled.
        info = VendorSession(_FakeReadDevice([_fw("02440152")])).read_firmware_version()
        self.assertEqual(info.groups, ("0244", "0152"))
        self.assertEqual(info.raw, "02440152")

    def test_unrecognised_format_returns_none_rather_than_inventing_a_version(self):
        info = VendorSession(_FakeReadDevice([_fw("v2.4")])).read_firmware_version()
        self.assertIsNone(info.controller)
        self.assertEqual(info.raw, "v2.4")

    def test_skips_input_frames_on_the_shared_pipe(self):
        dev = _FakeReadDevice([_input_frame(46), _fw("02440152")])
        self.assertEqual(VendorSession(dev).read_firmware_version().controller, "2.4.4")

    def test_skips_read_responses_on_the_shared_pipe(self):
        dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00"), _fw("0209")])
        self.assertEqual(VendorSession(dev).read_firmware_version().controller, "2.0.9")

    def test_sends_the_documented_command_and_selector(self):
        from pyg7.constants import CMD_DEVICE_INFO, INFO_FIRMWARE
        dev = _FakeReadDevice([_fw("0209")])
        VendorSession(dev).read_firmware_version()
        _endpoint, sent = dev.written[0]
        self.assertEqual(sent[3], CMD_DEVICE_INFO)
        self.assertEqual(sent[4], INFO_FIRMWARE)

    def test_times_out_rather_than_hanging(self):
        with self.assertRaises(TimeoutError):
            VendorSession(_FakeReadDevice([])).read_firmware_version(timeout=0.05)


class ActiveProfileTest(unittest.TestCase):
    """CMD_DEVICE_INFO selector 0x0b -- which profile the controller is on.

    Confirmed 2026-08-12: 0x01 on Profile 1 across six readings (three of
    them from July captures) and 0x03 immediately after switching to Profile
    3 with M+A. It is not in any config blob, the input stream or report
    0x20 -- all ruled out with controls before anyone looked at this channel.
    """

    def test_reads_the_profile_number(self):
        for slot in (1, 2, 3, 4):
            dev = _FakeReadDevice([_info_report(0x0b, bytes([slot]))])
            self.assertEqual(VendorSession(dev).read_active_profile(), slot)

    def test_sends_the_documented_selector(self):
        from pyg7.constants import CMD_DEVICE_INFO, INFO_ACTIVE_PROFILE
        dev = _FakeReadDevice([_info_report(0x0b, b"\x01")])
        VendorSession(dev).read_active_profile()
        _endpoint, sent = dev.written[0]
        self.assertEqual(sent[3], CMD_DEVICE_INFO)
        self.assertEqual(sent[4], INFO_ACTIVE_PROFILE)

    def test_rejects_an_out_of_range_profile(self):
        # A caller could address writes with this. Better to fail loudly
        # than hand back a profile number the device cannot have.
        for bad in (0, 5, 0xFF):
            dev = _FakeReadDevice([_info_report(0x0b, bytes([bad]))])
            with self.assertRaises(ValueError):
                VendorSession(dev).read_active_profile()

    def test_skips_the_input_stream_on_the_shared_pipe(self):
        dev = _FakeReadDevice([_input_frame(46), _info_report(0x0b, b"\x02")])
        self.assertEqual(VendorSession(dev).read_active_profile(), 2)
