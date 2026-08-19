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

    def test_other_variant_landing_is_recognized_too(self):
        # Regression target: a reported-but-unconfirmed other-variant vendor
        # PID (see PID_VENDOR_TRIMODE's comment) must not be a wait this
        # function can never win -- it needs to be in the candidate list the
        # post-handshake loop actually checks, same as PID_VENDOR/PID_DONGLE.
        (dev, via_dongle), landed = self._run(constants.PID_VENDOR_TRIMODE)
        self.assertIs(dev, landed)
        self.assertFalse(via_dongle)

    def test_zzz_edition_landing_is_recognized_too(self):
        (dev, via_dongle), landed = self._run(constants.PID_VENDOR_ZZZ)
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


class _FakeIntf:
    def __init__(self, number, klass):
        self.bInterfaceNumber = number
        self.bInterfaceClass = klass


class _FakeDev:
    """Minimal stand-in exposing only what is_xinput_personality() reads.

    `interfaces=None` models a device whose descriptors can't be read at all
    (mid-re-enumeration, or unplugged between the find and the query).
    """
    def __init__(self, pid, interfaces, product=""):
        self.idProduct = pid
        self.product = product
        self.bus = 3
        self.address = 88
        self._interfaces = interfaces

    def get_active_configuration(self):
        if self._interfaces is None:
            raise OSError("descriptors unavailable")
        return self._interfaces


def _xinput_personality(pid):
    """Interface 1 is the HID keyboard+mouse composite -- a working gamepad."""
    return _FakeDev(pid, [_FakeIntf(0, 0xFF), _FakeIntf(1, 0x03)],
                    "Xbox 360 Controller for Windows")


def _vendor_personality(pid):
    """Interface 1 is not HID -- vendor class, or the isochronous audio pair."""
    return _FakeDev(pid, [_FakeIntf(0, 0xFF), _FakeIntf(1, 0xFF)], "GameSir-G7 Pro")


class PersonalityTest(unittest.TestCase):
    """The XInput personality moved onto PID_VENDOR in firmware v2.4.4, so
    the PID stopped identifying which personality is present. Measured
    2026-08-18: a freshly-plugged controller at 3537:109b, iProduct "Xbox 360
    Controller for Windows", xpad bound and js0 live, streaming XInput report
    frames -- while find_device(PID_XINPUT) found nothing at all.
    """

    def test_hid_interface_1_means_xinput_personality(self):
        self.assertTrue(device.is_xinput_personality(_xinput_personality(constants.PID_VENDOR)))

    def test_non_hid_interface_1_means_vendor_personality(self):
        self.assertFalse(device.is_xinput_personality(_vendor_personality(constants.PID_VENDOR)))

    def test_unreadable_descriptors_are_not_reported_as_xinput(self):
        # "Don't know" must keep the module's previous behaviour rather than
        # making a device invisible to find_writable_device().
        self.assertFalse(device.is_xinput_personality(_FakeDev(constants.PID_VENDOR, None)))


class FindWritableDeviceTest(unittest.TestCase):
    def _patched(self, table):
        return mock.patch.object(device, "find_device", side_effect=lambda pid: table.get(pid))

    def test_refuses_a_gamepad_sitting_at_the_vendor_pid(self):
        """The bug. Claiming this detached xpad, took the controller away
        mid-use, and left a heartbeat loop on an endpoint that answers
        nothing -- which looks exactly like a wedge."""
        with self._patched({constants.PID_VENDOR: _xinput_personality(constants.PID_VENDOR)}):
            dev, via_dongle = device.find_writable_device()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)

    def test_still_finds_a_genuine_vendor_mode_device(self):
        target = _vendor_personality(constants.PID_VENDOR)
        with self._patched({constants.PID_VENDOR: target}):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)

    def test_still_finds_the_dongle(self):
        target = _vendor_personality(constants.PID_DONGLE)
        with self._patched({constants.PID_DONGLE: target}):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertTrue(via_dongle)

    def test_a_gamepad_at_the_vendor_pid_does_not_mask_the_dongle(self):
        # Order matters: the wired PID is checked first, and rejecting it
        # must continue to the dongle rather than returning None.
        dongle = _vendor_personality(constants.PID_DONGLE)
        with self._patched({constants.PID_VENDOR: _xinput_personality(constants.PID_VENDOR),
                            constants.PID_DONGLE: dongle}):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, dongle)
        self.assertTrue(via_dongle)

    def test_finds_a_genuine_vendor_mode_device_at_the_other_variant_pid(self):
        target = _vendor_personality(constants.PID_VENDOR_TRIMODE)
        with self._patched({constants.PID_VENDOR_TRIMODE: target}):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)

    def test_finds_a_genuine_vendor_mode_device_at_the_zzz_edition_pid(self):
        # Regression target: xpad binding to interface 0 and Steam showing a
        # working pad is not evidence this PID is the XInput personality --
        # it happens regardless of which personality is present. Only
        # interface 1's descriptor shape (checked by is_xinput_personality())
        # tells the two apart, and this one reads as vendor mode.
        target = _vendor_personality(constants.PID_VENDOR_ZZZ)
        with self._patched({constants.PID_VENDOR_ZZZ: target}):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)


class FindXinputDeviceTest(unittest.TestCase):
    def _patched(self, table):
        return mock.patch.object(device, "find_device", side_effect=lambda pid: table.get(pid))

    def test_finds_it_at_the_classic_pid(self):
        target = _xinput_personality(constants.PID_XINPUT)
        with self._patched({constants.PID_XINPUT: target}):
            self.assertIs(device.find_xinput_device(), target)

    def test_finds_it_at_the_vendor_pid_on_v244_firmware(self):
        """Without this, enter_vendor_mode() reports "no device found" for a
        controller that is plugged in and working."""
        target = _xinput_personality(constants.PID_VENDOR)
        with self._patched({constants.PID_VENDOR: target}):
            self.assertIs(device.find_xinput_device(), target)

    def test_does_not_mistake_a_vendor_mode_device_for_one_needing_a_handshake(self):
        with self._patched({constants.PID_VENDOR: _vendor_personality(constants.PID_VENDOR)}):
            self.assertIsNone(device.find_xinput_device())
