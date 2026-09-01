"""Tests for `g7ctl diag` (roadmap item 46) -- device discovery is faked out
entirely (find_native_identity/find_hid_device/find_writable_device/
switch_to_xid/VendorSession are all monkeypatched on the g7ctl.main
module, same pattern tests/test_cli.py uses), so nothing here touches real
USB. has_hid_interface() is the one real pyg7.device function exercised,
against a minimal fake descriptor shape -- same style test_device.py itself
uses.
"""
import contextlib
import io
import sys
import unittest
from unittest import mock

from g7ctl import main as cli_main
from pyg7.device import HID_INTERFACE_CLASS
from pyg7.variants import PID_DONGLE, PID_NATIVE, PID_XID

from .fakes import FakeSession


class _FakeInterface:
    def __init__(self, number, iclass):
        self.bInterfaceNumber = number
        self.bInterfaceClass = iclass


class _FakeConfig(list):
    """Iterating a real usb.core.Configuration yields every interface,
    including every alt setting -- a plain list of _FakeInterface
    reproduces that shape exactly (see tests/test_device.py)."""


class _FakeDevice:
    def __init__(self, pid, hid_on_iface1, bus=3, address=7,
                 bcddevice=0x0244, iproduct="GameSir-G7 Pro", driver_bound=False):
        self.idProduct = pid
        self.bus = bus
        self.address = address
        self.bcdDevice = bcddevice
        self.iProduct = 3  # a string-descriptor index; real value irrelevant here
        self._iproduct_str = iproduct
        self._driver_bound = driver_bound
        iface1_class = HID_INTERFACE_CLASS if hid_on_iface1 else 0xFF
        self._config = _FakeConfig([
            _FakeInterface(0, 0xFF),
            _FakeInterface(1, iface1_class),
        ])

    def get_active_configuration(self):
        return self._config

    def is_kernel_driver_active(self, iface):
        return self._driver_bound


class _FirmwareSession(FakeSession):
    def __init__(self, label="2.44"):
        super().__init__()
        self._label = label

    def read_firmware_version(self, timeout=None):
        from pyg7.session import FirmwareInfo
        return FirmwareInfo(controller=self._label, raw=self._label, groups=(self._label,))


class _FakeSessionCM:
    def __init__(self, _dev, via_dongle=False):
        self.session = _FirmwareSession()

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


class DiagTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "all_vid_devices": cli_main.all_vid_devices,
            "find_native_identity": cli_main.find_native_identity,
            "find_hid_device": cli_main.find_hid_device,
            "find_writable_device": cli_main.find_writable_device,
            "switch_to_xid": cli_main.switch_to_xid,
            "VendorSession": cli_main.VendorSession,
            "argv": sys.argv,
        }
        # Empty by default -- diag's own raw unsupported-device scan (added
        # 2026-09-01) has nothing to report unless a test overrides this.
        # Patched here, not left calling the real usb.core.find(), for the
        # same reason every other finder below is faked: this suite must
        # not depend on what's actually plugged into the test machine.
        cli_main.all_vid_devices = lambda: []
        cli_main.find_native_identity = lambda: None
        cli_main.find_hid_device = lambda: None
        cli_main.find_writable_device = lambda: (None, False)
        cli_main.switch_to_xid = lambda **k: (None, False)
        cli_main.VendorSession = _FakeSessionCM

    def tearDown(self):
        cli_main.all_vid_devices = self._orig["all_vid_devices"]
        cli_main.find_native_identity = self._orig["find_native_identity"]
        cli_main.find_hid_device = self._orig["find_hid_device"]
        cli_main.find_writable_device = self._orig["find_writable_device"]
        cli_main.switch_to_xid = self._orig["switch_to_xid"]
        cli_main.VendorSession = self._orig["VendorSession"]
        sys.argv = self._orig["argv"]

    def _run(self):
        sys.argv = ["g7ctl", "diag"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli_main.main()
        return out.getvalue()

    def test_nothing_found_says_so_plainly(self):
        report = self._run()
        self.assertIn("No GameSir-VID device found at all", report)

    def test_a_confirmed_unsupported_device_is_named_not_silently_skipped(self):
        # Added 2026-09-01: every other finder now skips a device on
        # variants.UNSUPPORTED_PIDS entirely (pyg7/device.py's
        # _candidate_devices()) -- diag's own raw scan must still surface
        # it, since silently reporting "no device found" for hardware that
        # IS plugged in would be actively misleading.
        blocked = _FakeDevice(0xBEEF, hid_on_iface1=False)
        cli_main.all_vid_devices = lambda: [blocked]
        with mock.patch("g7ctl.main.identify_unsupported",
                         side_effect=lambda pid: "GameSir T7 Pro" if pid == 0xBEEF else None):
            report = self._run()
        self.assertIn("GameSir T7 Pro", report)
        self.assertIn(f"{0xBEEF:04x}", report)
        self.assertIn("not supported", report)
        # Nothing else found it (find_hid_device/find_writable_device are
        # still faked to None/False by setUp), so the generic message
        # should NOT also fire -- a real, named device was reported above.
        self.assertNotIn("No GameSir-VID device found at all", report)

    def test_native_only_advises_the_menu_share_switch_and_stops_there(self):
        cli_main.find_native_identity = lambda: _FakeDevice(PID_NATIVE, hid_on_iface1=False)
        report = self._run()
        self.assertIn("native GameSir identity", report)
        self.assertIn("Menu+Share", report)
        # A real device WAS found -- the generic "nothing found at all"
        # framing would be actively misleading here.
        self.assertNotIn("No GameSir-VID device found at all", report)

    def test_hid_found_sends_handshake_and_reports_both_states(self):
        xdev = _FakeDevice(0x100a, hid_on_iface1=True)
        vdev = _FakeDevice(PID_XID, hid_on_iface1=False)
        cli_main.find_hid_device = lambda: xdev
        cli_main.switch_to_xid = lambda **k: (vdev, False)

        report = self._run()

        self.assertIn("sending the real handshake", report)
        self.assertIn(f"{0x100a:04x}", report)
        self.assertIn(f"{PID_XID:04x}", report)
        self.assertIn("Shadow Ember", report)
        self.assertIn("confirmed", report)
        self.assertIn("Firmware version: 2.44", report)

    def test_handshake_sent_but_no_reenumeration_reports_hid_state_only(self):
        xdev = _FakeDevice(0x100a, hid_on_iface1=True)
        cli_main.find_hid_device = lambda: xdev
        cli_main.switch_to_xid = lambda **k: (None, False)

        report = self._run()

        self.assertIn("no re-enumeration seen", report)
        self.assertIn(f"{0x100a:04x}", report)
        self.assertNotIn("Firmware version:", report)

    def test_readable_without_a_handshake_sends_no_handshake(self):
        already = _FakeDevice(PID_XID, hid_on_iface1=False)
        cli_main.find_writable_device = lambda: (already, False)
        handshake_calls = []
        cli_main.switch_to_xid = lambda **k: handshake_calls.append(1) or (None, False)

        report = self._run()

        self.assertIn("accepts config reads right now", report)
        self.assertIn(f"{PID_XID:04x}", report)
        self.assertEqual(handshake_calls, [])

    def test_readable_state_does_not_claim_it_was_already_left_that_way(self):
        # Regression target: a real, confirmed-wrong report -- this exact
        # branch used to claim "left there by an earlier session" and
        # "already in vendor/config mode" when nothing of the sort could
        # actually be verified. A controller can accept a config read here
        # while it was, a moment before, genuinely and functionally sitting
        # in XInput (xpad bound, working in-game) -- see g7ctl/main.py's
        # _handle_diag() docstring on this branch for the real incident.
        already = _FakeDevice(PID_XID, hid_on_iface1=False, driver_bound=True)
        cli_main.find_writable_device = lambda: (already, False)

        report = self._run()

        self.assertNotIn("already in vendor/config mode", report)
        self.assertNotIn("left there by an earlier session", report)
        self.assertIn("was already presenting the baseline identity before "
                       "this ran", report)
        self.assertIn("Kernel driver bound to interface 0 | yes", report)

    def test_flags_the_known_ambiguous_combination(self):
        # Real, confirmed case (2026-08-28): interface 1 shows no HID
        # alt-setting while a kernel driver is bound (usually read as a
        # live gamepad) -- neither signal alone tells you which is true
        # here. A bug report benefits from being told this combination is
        # known-ambiguous, not just shown the two raw facts side by side
        # with no context.
        already = _FakeDevice(PID_XID, hid_on_iface1=False, driver_bound=True)
        cli_main.find_writable_device = lambda: (already, False)

        report = self._run()

        self.assertIn("Known-ambiguous combination", report)

    def test_does_not_flag_when_the_driver_is_not_bound(self):
        already = _FakeDevice(PID_XID, hid_on_iface1=False, driver_bound=False)
        cli_main.find_writable_device = lambda: (already, False)

        report = self._run()

        self.assertNotIn("Known-ambiguous combination", report)

    def test_unconfirmed_pid_says_so_honestly_not_a_guess(self):
        xdev = _FakeDevice(0x100a, hid_on_iface1=True)
        vdev = _FakeDevice(PID_DONGLE, hid_on_iface1=False)  # not a variant PID
        cli_main.find_hid_device = lambda: xdev
        cli_main.switch_to_xid = lambda **k: (vdev, False)

        report = self._run()

        self.assertIn("not yet confirmed", report)

    def test_iproduct_read_failure_shows_unknown_not_a_traceback(self):
        xdev = _FakeDevice(0x100a, hid_on_iface1=True)
        cli_main.find_hid_device = lambda: xdev
        with mock.patch("g7ctl.main.usb.util.get_string", side_effect=Exception("no backend")):
            report = self._run()
        self.assertIn("(unknown)", report)


class FormatBcdTest(unittest.TestCase):
    """bcdDevice is packed BCD -- each hex nibble is its own decimal digit.
    Regression target: an earlier draft of this feature treated it as a
    plain binary value and printed 0x0244 as "2.68" instead of "2.44"."""

    def test_matches_the_documented_firmware_string(self):
        self.assertEqual(cli_main._format_bcd(0x0244), "2.44")

    def test_single_digit_minor_does_not_mask_the_bug(self):
        self.assertEqual(cli_main._format_bcd(0x0207), "2.07")


if __name__ == "__main__":
    unittest.main()
