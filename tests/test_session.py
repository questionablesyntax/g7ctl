"""VendorSession.send_raw() framing tests.

Every category module funnels its writes through this one method, so its
framing invariants (fixed 64-byte packet, incrementing sequence byte) matter
project-wide, not just for the CLI's `raw` escape hatch that exercises it
most directly.
"""
import unittest

from pyg7.session import (
    READ_CHUNK_TIMEOUT, READ_CHUNK_TIMEOUT_DONGLE,
    SETTLE_HEARTBEATS, SETTLE_HEARTBEATS_DONGLE, VendorSession,
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


class DongleAwareDefaultsTest(unittest.TestCase):
    """Raised 2026-07-30 from real daily use: the dongle's extra RF hop was
    seen making the first read after connecting time out more often than
    wired. VendorSession now scales its settle warmup and read_chunk's
    default timeout based on via_dongle -- these pin that it actually
    changes the numbers used, not just that the constants exist."""

    def test_settle_heartbeat_count_defaults_to_wired(self):
        sess = VendorSession(_FakeDevice(), via_dongle=False)
        sess.settle(interval=0)
        # send_raw increments seq once per heartbeat -- count them via seq.
        self.assertEqual(sess.seq, SETTLE_HEARTBEATS)

    def test_settle_heartbeat_count_relaxed_over_dongle(self):
        sess = VendorSession(_FakeDevice(), via_dongle=True)
        sess.settle(interval=0)
        self.assertEqual(sess.seq, SETTLE_HEARTBEATS_DONGLE)
        self.assertGreater(SETTLE_HEARTBEATS_DONGLE, SETTLE_HEARTBEATS)

    def test_settle_explicit_count_overrides_dongle_default(self):
        sess = VendorSession(_FakeDevice(), via_dongle=True)
        sess.settle(count=3, interval=0)
        self.assertEqual(sess.seq, 3)

    def test_read_chunk_timeout_defaults_to_wired(self):
        dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00")])
        sess = VendorSession(dev, via_dongle=False)
        sess.read_chunk(1, 0, 1)
        # read_chunk passes timeout in milliseconds (derived from a
        # deadline, so a slice of a millisecond of real elapsed time between
        # setting it and computing `remaining` is expected slop, not a bug).
        self.assertAlmostEqual(dev.read_timeouts[-1], int(READ_CHUNK_TIMEOUT * 1000), delta=5)

    def test_read_chunk_timeout_relaxed_over_dongle(self):
        dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00")])
        sess = VendorSession(dev, via_dongle=True)
        sess.read_chunk(1, 0, 1)
        self.assertAlmostEqual(dev.read_timeouts[-1], int(READ_CHUNK_TIMEOUT_DONGLE * 1000), delta=5)
        self.assertGreater(READ_CHUNK_TIMEOUT_DONGLE, READ_CHUNK_TIMEOUT)

    def test_read_chunk_explicit_timeout_overrides_dongle_default(self):
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
    """

    def test_true_when_a_real_read_succeeds(self):
        dev = _FakeReadDevice([_read_response_report(1, 0, 1, b"\x00")])
        sess = VendorSession(dev, via_dongle=True)
        self.assertTrue(sess.probe_controller_live(timeout=0.05))

    def test_false_on_timeout_no_response_ever_arrives(self):
        dev = _FakeReadDevice([])  # every .read() times out immediately
        sess = VendorSession(dev, via_dongle=True)
        self.assertFalse(sess.probe_controller_live(timeout=0.05))

    def test_real_usb_error_still_propagates(self):
        # A genuine USBError (the dongle itself vanishing) is a different,
        # harder failure than "no controller answering" -- the caller's
        # existing USBError handling covers that, so this must NOT be
        # swallowed into a plain False the way a timeout is.
        import usb.core
        exc = usb.core.USBError("no such device")
        exc.errno = 19
        dev = _FakeReadDevice([exc])
        sess = VendorSession(dev, via_dongle=True)
        with self.assertRaises(usb.core.USBError):
            sess.probe_controller_live(timeout=0.05)


if __name__ == "__main__":
    unittest.main()
