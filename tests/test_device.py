"""device.py tests: finding the controller and identifying its current USB
identity. No real USB access -- pyg7.device.find_device() is
monkeypatched, so these only exercise the pure decision logic (which PID to
look for, which message to log), not the actual libusb calls.
"""
import unittest
from unittest import mock

from pyg7 import constants, device


class FindNativeIdentityTest(unittest.TestCase):
    def test_delegates_to_find_device_with_the_right_pid(self):
        with mock.patch.object(device, "find_device") as mocked:
            mocked.return_value = "sentinel"
            result = device.find_native_identity()
        mocked.assert_called_once_with(constants.PID_NATIVE)
        self.assertEqual(result, "sentinel")


class EnterVendorModeMissingDeviceTest(unittest.TestCase):
    """enter_vendor_mode()'s early-return path when PID_XINPUT isn't found --
    covers only the message-selection branch. Everything past that point
    (the handshake, waiting for re-enumeration) needs a real device and
    isn't exercised here.
    """

    def _fake_find_device(self, native_present: bool):
        def fake(pid):
            if pid == constants.PID_XINPUT:
                return None
            if pid == constants.PID_NATIVE:
                return object() if native_present else None
            return None
        return fake

    def test_logs_the_native_identity_hint_when_present(self):
        # Regression target: a controller left in its native GameSir
        # identity (found 2026-07-30, held via Menu+Share) used to report
        # the same generic "no device found" as a genuinely unplugged
        # controller -- indistinguishable, and not actionable.
        with mock.patch.object(device, "find_device", side_effect=self._fake_find_device(True)):
            with self.assertLogs(device.log, level="ERROR") as cm:
                dev, via_dongle = device.enter_vendor_mode()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)
        self.assertTrue(any("Menu+Share" in msg for msg in cm.output))

    def test_logs_the_generic_message_when_native_identity_absent_too(self):
        with mock.patch.object(device, "find_device", side_effect=self._fake_find_device(False)):
            with self.assertLogs(device.log, level="ERROR") as cm:
                dev, via_dongle = device.enter_vendor_mode()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)
        self.assertFalse(any("Menu+Share" in msg for msg in cm.output))
        self.assertTrue(any("No device found" in msg for msg in cm.output))


class EnterVendorModeLandingIdentityTest(unittest.TestCase):
    """Which identity the handshake lands on, and whether the caller is told.

    Raised 2026-08-01 from a plain restart of the GUI: the dongle had been
    documented since 2026-07-26 as having no XInput identity and needing no
    handshake, so this function only ever waited for PID_VENDOR. It is
    wrong on both counts -- an idle dongle sits at PID_XINPUT with `xpad`
    bound, takes the same handshake, and re-enumerates as PID_DONGLE (same
    USB port, disconnect at handshake, back ~2s later). The cost was a full
    timeout_s of dead waiting plus an ERROR log on every dongle connect from
    idle, and -- because both call sites then hardcoded via_dongle=False --
    a session running the tighter wired timeouts over the RF link.
    """

    def _run(self, landing_pid, timeout_s=1.0):
        xinput_dev = mock.MagicMock(name="xinput_dev")
        landed_dev = mock.MagicMock(name="landed_dev")

        def fake_find_device(pid):
            if pid == constants.PID_XINPUT:
                return xinput_dev
            if pid == landing_pid:
                return landed_dev
            return None

        with mock.patch.object(device, "find_device", side_effect=fake_find_device), \
             mock.patch("usb.util.claim_interface"), \
             mock.patch("usb.util.release_interface"), \
             mock.patch.object(device.time, "sleep"):
            return device.enter_vendor_mode(timeout_s=timeout_s), landed_dev

    def test_dongle_landing_is_reported_as_via_dongle(self):
        (dev, via_dongle), landed = self._run(constants.PID_DONGLE)
        self.assertIs(dev, landed)
        self.assertTrue(via_dongle)

    def test_wired_landing_is_not_reported_as_via_dongle(self):
        (dev, via_dongle), landed = self._run(constants.PID_VENDOR)
        self.assertIs(dev, landed)
        self.assertFalse(via_dongle)

    def test_no_landing_at_all_still_times_out(self):
        # Short timeout: time.sleep is mocked, so the poll loop spins on the
        # real clock and this is wall-time in the suite.
        with self.assertLogs(device.log, level="ERROR") as cm:
            (dev, via_dongle), _ = self._run(landing_pid=None, timeout_s=0.05)
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)
        self.assertTrue(any("Timed out" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
