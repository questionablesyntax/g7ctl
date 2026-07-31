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
                result = device.enter_vendor_mode()
        self.assertIsNone(result)
        self.assertTrue(any("Menu+Share" in msg for msg in cm.output))

    def test_logs_the_generic_message_when_native_identity_absent_too(self):
        with mock.patch.object(device, "find_device", side_effect=self._fake_find_device(False)):
            with self.assertLogs(device.log, level="ERROR") as cm:
                result = device.enter_vendor_mode()
        self.assertIsNone(result)
        self.assertFalse(any("Menu+Share" in msg for msg in cm.output))
        self.assertTrue(any("No device found" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
