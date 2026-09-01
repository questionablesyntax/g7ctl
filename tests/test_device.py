"""device.py tests: finding the controller and identifying its current USB
identity. No real USB access -- usb.core.find() is monkeypatched (as of the
2026-08-29 detection redesign, every finder scans VID-matching devices and
classifies them structurally, rather than looking up known PIDs one at a
time), so these only exercise the pure decision logic (which device gets
picked, which message to log), not the actual libusb calls.
"""
import itertools
import unittest
from unittest import mock

import usb.core

from pyg7 import device

# Representative PIDs for building fake devices below -- test fixture data
# only, not a second copy of variants.py's own registry (which no longer
# exports named PID constants at all -- see its own comment on why: a PID
# is a fact about specific hardware, and the module-level-constant-per-PID
# pattern was retired 2026-09-01 as unwarranted ceremony for that). Most
# tests below don't care which variant a PID belongs to, only its
# structural role (HID-presenting / baseline-wired / baseline-dongle /
# native), so these are named by role, not by SKU.
HID_PID = 0x100a
XID_PID = 0x109b
DONGLE_PID = 0x109c
NATIVE_PID = 0x1022
TRIMODE_XID_PID = 0x1003
TRIMODE_DONGLE_PID = 0x1004
ZZZ_XID_PID = 0x105d


class _FakeIntf:
    def __init__(self, number, klass):
        self.bInterfaceNumber = number
        self.bInterfaceClass = klass


class _FakeDev:
    """Minimal stand-in exposing what has_hid_interface()/
    _has_vendor_interface() read, plus the handful of calls
    switch_to_xid()'s claim/write/release flow makes on whichever device it
    finds pre-handshake (kernel-driver detach/reattach, the handshake
    writes themselves) -- claim_interface()/release_interface() are
    usb.util module functions, mocked separately, not device methods.

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

    def is_kernel_driver_active(self, iface):
        return False

    def detach_kernel_driver(self, iface):
        pass

    def attach_kernel_driver(self, iface):
        pass

    def write(self, endpoint, data):
        return len(data)


def _hid_shaped(pid):
    """Interface 1 is the HID keyboard+mouse composite -- a working gamepad.
    Interface 0 stays vendor-class, same as every usable identity."""
    return _FakeDev(pid, [_FakeIntf(0, 0xFF), _FakeIntf(1, 0x03)],
                    "Xbox 360 Controller for Windows")


def _xid_shaped(pid):
    """Interface 1 is not HID -- vendor class, or the isochronous audio
    pair. Interface 0 stays vendor-class."""
    return _FakeDev(pid, [_FakeIntf(0, 0xFF), _FakeIntf(1, 0xFF)], "GameSir-G7 Pro")


def _native_shaped(pid):
    """Two plain HID-class interfaces, no vendor-specific class-255
    interface anywhere -- the native/GIP identity's real shape (see
    PROTOCOL.md "Device identities"). Interface 1 being HID here, same as
    _hid_shaped(), is exactly why has_hid_interface() alone can't tell this
    apart from a real PID_HID device -- only the absence of any
    vendor-class interface does."""
    return _FakeDev(pid, [_FakeIntf(0, 0x03), _FakeIntf(1, 0x03)], "GameSir-G7 Pro")


def _patched(*devices):
    """Patch usb.core.find() to return exactly this fixed list of fake
    devices, regardless of the kwargs it's called with -- every finder in
    device.py calls it the same way (find_all=True, idVendor=VID) since the
    2026-08-29 redesign, so there's only one call shape to model."""
    return mock.patch("usb.core.find", return_value=list(devices))


class UnsupportedPidGateTest(unittest.TestCase):
    """_candidate_devices(), added 2026-09-01: every finder skips a PID
    variants.identify_unsupported() confirms belongs to a different GameSir
    product, before any structural check ever runs on it. Patches
    device.identify_unsupported() directly rather than depending on real
    entries existing in variants.UNSUPPORTED_PIDS (empty by design today --
    see variants.py's own comment)."""

    def _unsupported(self, pid, name="GameSir T7 Pro"):
        return mock.patch("pyg7.device.identify_unsupported",
                           side_effect=lambda p: name if p == pid else None)

    def test_find_native_identity_skips_a_known_unsupported_pid(self):
        blocked = _native_shaped(0xBEEF)
        with self._unsupported(0xBEEF), _patched(blocked):
            self.assertIsNone(device.find_native_identity())

    def test_find_hid_device_skips_a_known_unsupported_pid(self):
        blocked = _hid_shaped(0xBEEF)
        with self._unsupported(0xBEEF), _patched(blocked):
            self.assertIsNone(device.find_hid_device())

    def test_find_writable_device_skips_a_known_unsupported_pid(self):
        blocked = _xid_shaped(0xBEEF)
        with self._unsupported(0xBEEF), _patched(blocked):
            dev, via_dongle = device.find_writable_device()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)

    def test_scanning_continues_past_a_rejected_device_to_a_real_one(self):
        # Order matters, same as the existing "gamepad at the baseline PID
        # does not mask the dongle" case: a rejected candidate must not
        # stop the scan before it reaches a genuine one behind it.
        blocked = _xid_shaped(0xBEEF)
        real = _xid_shaped(XID_PID)
        with self._unsupported(0xBEEF), _patched(blocked, real):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, real)
        self.assertFalse(via_dongle)

    def test_an_unlisted_pid_is_never_gated(self):
        # No real entries exist yet -- confirms the gate is a no-op for
        # every genuinely unknown PID, not just documented as one.
        target = _xid_shaped(XID_PID)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)


class FindNativeIdentityTest(unittest.TestCase):
    """Redesigned 2026-08-29: structural (no vendor-class interface
    anywhere), not a hardcoded PID match. See find_native_identity()'s own
    docstring for why: PID_NATIVE is confirmed stable across the two
    variants checked so far (this project's own hardware and a G7 Pro ZZZ
    edition, independently), but that's not the same as guaranteed stable
    for a variant this project hasn't seen yet."""

    def test_finds_a_device_with_no_vendor_interface(self):
        target = _native_shaped(NATIVE_PID)
        with _patched(target):
            self.assertIs(device.find_native_identity(), target)

    def test_skips_a_device_that_has_a_vendor_interface(self):
        with _patched(_xid_shaped(XID_PID)):
            self.assertIsNone(device.find_native_identity())

    def test_returns_none_when_nothing_is_connected(self):
        with _patched():
            self.assertIsNone(device.find_native_identity())

    def test_skips_a_device_whose_descriptors_cant_be_read_yet(self):
        # _has_vendor_interface() returning None ("don't know") must never
        # be misread as "definitely no vendor interface" -- that would
        # misclassify a transiently-unreadable *usable* device as native.
        unreadable = _FakeDev(HID_PID, None)
        with _patched(unreadable):
            self.assertIsNone(device.find_native_identity())

    def test_finds_a_genuinely_unknown_variant(self):
        # The whole point of the redesign: a variant this project has
        # never hardcoded a PID for still works.
        target = _native_shaped(0x9999)
        with _patched(target):
            self.assertIs(device.find_native_identity(), target)


class HasHidInterfaceTest(unittest.TestCase):
    """Renamed 2026-08-29 from PersonalityTest -- this was never a
    "personality" question (see has_hid_interface()'s own corrected
    docstring in pyg7/device.py for the full account). The descriptor
    check itself is real and unchanged: interface 1 shows HID class when
    the keyboard/mouse interface is present, vendor class/isochronous
    audio otherwise. What's retired is reading that as "XInput vs.
    vendor/config" rather than "HID interface present or not".

    Historical note this class used to open with, kept for the record:
    the HID interface moved onto PID_XID's own PID on at least one real
    firmware (v2.4.4), measured 2026-08-18 -- a freshly-plugged
    controller at 3537:109b, iProduct "Xbox 360 Controller for Windows",
    xpad bound and js0 live, streaming XInput report frames -- while
    a PID_HID-only lookup found nothing at all. That's still a real,
    confirmed case; it just isn't evidence of two "personalities" sharing
    one PID, it's the same HID-interface-presence axis showing up under a
    different PID than usual.
    """

    def test_hid_interface_1_present(self):
        self.assertTrue(device.has_hid_interface(_hid_shaped(XID_PID)))

    def test_non_hid_interface_1_absent(self):
        self.assertFalse(device.has_hid_interface(_xid_shaped(XID_PID)))

    def test_unreadable_descriptors_answer_false_not_true(self):
        # "Don't know" must keep the module's previous behaviour rather than
        # making a device invisible to find_writable_device().
        self.assertFalse(device.has_hid_interface(_FakeDev(XID_PID, None)))


class _PermissionDeniedDev(_FakeDev):
    """get_active_configuration() raises the real shape a missing udev rule
    produces -- usb.core.USBError with errno=13 (EACCES), same as
    g7ctl/main.py's _explain_usb_error() already special-cases at the CLI
    level. Distinct from plain _FakeDev(pid, None)'s bare OSError, which
    models the benign mid-re-enumeration/gone case instead."""

    def get_active_configuration(self):
        exc = usb.core.USBError("Access denied")
        exc.errno = 13
        raise exc


class DescriptorReadFailureLoggingTest(unittest.TestCase):
    """Real gap, found by a dedicated active-debugging-infrastructure pass,
    2026-09-01: a failed get_active_configuration() used to be swallowed
    with zero logging at all, in either _interface_classes() or
    _has_vendor_interface() -- indistinguishable from the benign
    transient state their own docstrings reason about. See
    DEBUGGING-INFRA-PLAN-2026-09-01.md."""

    def test_a_permission_error_logs_a_warning_naming_the_real_cause(self):
        with self.assertLogs("pyg7.device", level="WARNING") as ctx:
            result = device._has_vendor_interface(_PermissionDeniedDev(XID_PID, None))
        self.assertIsNone(result)  # still "don't know", behavior unchanged
        self.assertTrue(any("Permission denied" in line and "udev" in line
                            for line in ctx.output))

    def test_a_benign_read_failure_logs_at_debug_not_warning(self):
        with self.assertLogs("pyg7.device", level="DEBUG") as ctx:
            result = device._has_vendor_interface(_FakeDev(XID_PID, None))
        self.assertIsNone(result)
        self.assertTrue(any("could not read" in line for line in ctx.output))
        self.assertFalse(any(r.levelname == "WARNING" for r in ctx.records),
                         "a plain OSError (mid-re-enumeration/gone) must not "
                         "be reported as if it were the permissions case")

    def test_interface_classes_logs_too_not_just_has_vendor_interface(self):
        with self.assertLogs("pyg7.device", level="DEBUG") as ctx:
            result = device._interface_classes(_FakeDev(XID_PID, None), 1)
        self.assertEqual(result, [])
        self.assertTrue(any("could not read" in line for line in ctx.output))


class FindWritableDeviceTest(unittest.TestCase):
    def test_refuses_a_gamepad_sitting_at_the_baseline_pid(self):
        """The bug. Claiming this detached xpad, took the controller away
        mid-use, and left a heartbeat loop on an endpoint that answers
        nothing -- which looks exactly like a wedge."""
        with _patched(_hid_shaped(XID_PID)):
            dev, via_dongle = device.find_writable_device()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)

    def test_still_finds_a_genuine_baseline_device(self):
        target = _xid_shaped(XID_PID)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)

    def test_still_finds_the_dongle(self):
        target = _xid_shaped(DONGLE_PID)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertTrue(via_dongle)

    def test_a_gamepad_at_the_baseline_pid_does_not_mask_the_dongle(self):
        # Order matters: scanning must continue past a rejected candidate
        # (one presenting the HID interface at what would otherwise read
        # as baseline) rather than stopping at the first VID match.
        rejected = _hid_shaped(XID_PID)
        dongle = _xid_shaped(DONGLE_PID)
        with _patched(rejected, dongle):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, dongle)
        self.assertTrue(via_dongle)

    def test_finds_a_genuine_baseline_device_at_the_other_variant_pid(self):
        target = _xid_shaped(TRIMODE_XID_PID)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)

    def test_finds_the_other_variant_dongle(self):
        target = _xid_shaped(TRIMODE_DONGLE_PID)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertTrue(via_dongle)

    def test_finds_a_genuine_baseline_device_at_the_zzz_edition_pid(self):
        # Regression target: xpad binding to interface 0 and Steam showing a
        # working pad is not evidence this PID presents the HID interface --
        # it happens regardless of which identity is present. Only
        # interface 1's descriptor shape (checked by has_hid_interface())
        # tells the two apart, and this one reads as baseline (no HID).
        target = _xid_shaped(ZZZ_XID_PID)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)

    def test_excludes_the_native_identity(self):
        # The native identity has no vendor-class interface at all, so it
        # must never be mistaken for a writable baseline device -- even
        # though has_hid_interface() alone reads its interface 1 as "not
        # HID" too (both interfaces are plain HID there, see
        # _native_shaped()'s own docstring).
        with _patched(_native_shaped(NATIVE_PID)):
            dev, via_dongle = device.find_writable_device()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)

    def test_finds_a_genuinely_unknown_variant_pid(self):
        # The whole point of the redesign: a variant this project has
        # never hardcoded a PID for still works, and gets no confident
        # dongle label (False, not a guess either way).
        target = _xid_shaped(0x9999)
        with _patched(target):
            dev, via_dongle = device.find_writable_device()
        self.assertIs(dev, target)
        self.assertFalse(via_dongle)


class FindHidDeviceTest(unittest.TestCase):
    def test_finds_it_at_the_classic_pid(self):
        target = _hid_shaped(HID_PID)
        with _patched(target):
            self.assertIs(device.find_hid_device(), target)

    def test_finds_it_at_the_baseline_pid_on_v244_firmware(self):
        """Without this, switch_to_xid() reports "no device found" for a
        controller that is plugged in and working."""
        target = _hid_shaped(XID_PID)
        with _patched(target):
            self.assertIs(device.find_hid_device(), target)

    def test_does_not_mistake_a_baseline_device_for_one_needing_a_handshake(self):
        with _patched(_xid_shaped(XID_PID)):
            self.assertIsNone(device.find_hid_device())

    def test_does_not_mistake_the_native_identity_for_one_needing_a_handshake(self):
        # The native/GIP identity's interface 1 is ALSO HID-class (see
        # PROTOCOL.md "Device identities") -- has_hid_interface() alone
        # can't tell it apart from a real PID_HID device. Regression target
        # for the 2026-08-29 detection redesign: excluded via
        # _has_vendor_interface(), not accidentally matched.
        with _patched(_native_shaped(NATIVE_PID)):
            self.assertIsNone(device.find_hid_device())

    def test_finds_a_genuinely_unknown_variant_pid(self):
        target = _hid_shaped(0x9999)
        with _patched(target):
            self.assertIs(device.find_hid_device(), target)


class SwitchToXidMissingDeviceTest(unittest.TestCase):
    """switch_to_xid()'s early-return path when nothing HID-shaped is
    found -- covers only the message-selection branch. Everything past
    that point (the handshake, waiting for re-enumeration) needs a real
    device and isn't exercised here.
    """

    def test_logs_the_native_identity_hint_when_present(self):
        # Regression target: a controller left in its native GameSir
        # identity (found 2026-07-30, held via Menu+Share) used to report
        # the same generic "no device found" as a genuinely unplugged
        # controller -- indistinguishable, and not actionable.
        native = _native_shaped(NATIVE_PID)
        with _patched(native):
            with self.assertLogs(device.log, level="ERROR") as cm:
                dev, via_dongle = device.switch_to_xid()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)
        self.assertTrue(any("Menu+Share" in msg for msg in cm.output))

    def test_logs_the_generic_message_when_native_identity_absent_too(self):
        with _patched():
            with self.assertLogs(device.log, level="ERROR") as cm:
                dev, via_dongle = device.switch_to_xid()
        self.assertIsNone(dev)
        self.assertFalse(via_dongle)
        self.assertFalse(any("Menu+Share" in msg for msg in cm.output))
        self.assertTrue(any("No G7 Pro device found" in msg for msg in cm.output))


class SwitchToXidLandingIdentityTest(unittest.TestCase):
    """Which identity the handshake lands on, and whether the caller is told.

    Raised 2026-08-01 from a plain restart of the GUI: the dongle had been
    documented since 2026-07-26 as having no XInput identity and needing no
    handshake, so this function only ever waited for PID_XID. It is
    wrong on both counts -- an idle dongle sits at PID_HID with `xpad`
    bound, takes the same handshake, and re-enumerates as PID_DONGLE (same
    USB port, disconnect at handshake, back ~2s later). The cost was a full
    timeout_s of dead waiting plus an ERROR log on every dongle connect from
    idle, and -- because both call sites then hardcoded via_dongle=False --
    a session running the tighter wired timeouts over the RF link.
    """

    def _run(self, landing_pid, timeout_s=1.0):
        hid_dev = _hid_shaped(HID_PID)
        landed_dev = _xid_shaped(landing_pid) if landing_pid is not None else None

        if landed_dev is not None:
            # First call (the pre-handshake find_hid_device()) sees the
            # HID-shaped device; every call after (the post-handshake
            # find_writable_device() polling loop) sees it landed --
            # models the real re-enumeration the handshake write triggers.
            find_effect = itertools.chain([[hid_dev]], itertools.repeat([landed_dev]))
        else:
            # No landing at all -- stays HID-shaped for the whole timeout.
            find_effect = itertools.repeat([hid_dev])

        with mock.patch("usb.core.find", side_effect=find_effect), \
             mock.patch("usb.util.claim_interface"), \
             mock.patch("usb.util.release_interface"), \
             mock.patch.object(device.time, "sleep"):
            return device.switch_to_xid(timeout_s=timeout_s), landed_dev

    def test_dongle_landing_is_reported_as_via_dongle(self):
        (dev, via_dongle), landed = self._run(DONGLE_PID)
        self.assertIs(dev, landed)
        self.assertTrue(via_dongle)

    def test_wired_landing_is_not_reported_as_via_dongle(self):
        (dev, via_dongle), landed = self._run(XID_PID)
        self.assertIs(dev, landed)
        self.assertFalse(via_dongle)

    def test_landing_on_a_known_variant_names_it_in_the_log(self):
        # Real payoff of identify_variant() (roadmap item 36): a user
        # connecting a confirmed variant sees which one, not just a PID.
        with self.assertLogs(device.log, level="INFO") as logs:
            self._run(TRIMODE_XID_PID)
        self.assertTrue(any("White Trimode" in line for line in logs.output),
                         logs.output)

    def test_landing_on_an_unconfirmed_pid_omits_the_name_not_a_placeholder(self):
        # PID_DONGLE is a real, working baseline identity -- just not one
        # identify_variant() maps to a name (dongle PIDs aren't looked up
        # directly, see its own docstring). Must not print "None" or crash.
        with self.assertLogs(device.log, level="INFO") as logs:
            self._run(DONGLE_PID)
        landing_lines = [line for line in logs.output if "Now at a baseline" in line]
        self.assertEqual(len(landing_lines), 1)
        self.assertNotIn("None", landing_lines[0])

    def test_other_variant_landing_is_recognized_too(self):
        # Regression target: a reported-but-unconfirmed other-variant
        # baseline PID (see PID_XID_TRIMODE's comment) must not be a wait
        # this function can never win.
        (dev, via_dongle), landed = self._run(TRIMODE_XID_PID)
        self.assertIs(dev, landed)
        self.assertFalse(via_dongle)

    def test_other_variant_dongle_landing_is_recognized_too(self):
        (dev, via_dongle), landed = self._run(TRIMODE_DONGLE_PID)
        self.assertIs(dev, landed)
        self.assertTrue(via_dongle)

    def test_zzz_edition_landing_is_recognized_too(self):
        (dev, via_dongle), landed = self._run(ZZZ_XID_PID)
        self.assertIs(dev, landed)
        self.assertFalse(via_dongle)

    def test_landing_on_a_genuinely_unknown_variant_pid_still_works(self):
        # The whole point of the redesign: no hardcoded list needed for
        # detection to recognize a brand-new variant's landing PID.
        (dev, via_dongle), landed = self._run(0x9999)
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
