"""The floor on how often we may re-enumerate the controller.

Rapid re-enumeration wedges this firmware's read path, and the only thing
that clears a wedge -- holding Share+Menu -- erases every non-native
binding on the active profile and the Shift layer. So the cost of going too
fast is silent data loss, which is why there is a floor at all.

The age is read from sysfs rather than remembered, so these tests point
`SYSFS_USB_ROOT` at a fixture directory.
"""
import os
import unittest
from unittest import mock

from pyg7 import device


class _FakeDev:
    def __init__(self, bus=3, address=7):
        self.bus = bus
        self.address = address


def _make_node(root, name, busnum, devnum, connected_ms=None):
    node = os.path.join(root, name)
    os.makedirs(os.path.join(node, "power"), exist_ok=True)
    for fn, val in (("busnum", busnum), ("devnum", devnum)):
        with open(os.path.join(node, fn), "w") as fh:
            fh.write(f"{val}\n")
    if connected_ms is not None:
        with open(os.path.join(node, "power", "connected_duration"), "w") as fh:
            fh.write(f"{connected_ms}\n")
    return node


class EnumerationAgeTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(device, "SYSFS_USB_ROOT", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_connected_duration_in_seconds(self):
        _make_node(self.tmp.name, "3-7", 3, 7, connected_ms=3394)
        self.assertAlmostEqual(device.seconds_since_enumeration(_FakeDev()), 3.394, places=3)

    def test_matches_on_bus_and_devnum_not_just_the_first_node(self):
        """`devnum` is what pyusb calls `address`; several USB devices are
        always present, so the wrong match would report another device's age."""
        _make_node(self.tmp.name, "1-1", 1, 7, connected_ms=999999)
        _make_node(self.tmp.name, "3-2", 3, 2, connected_ms=888888)
        _make_node(self.tmp.name, "3-7", 3, 7, connected_ms=1000)
        self.assertAlmostEqual(device.seconds_since_enumeration(_FakeDev(3, 7)), 1.0)

    def test_falls_back_to_directory_ctime_without_connected_duration(self):
        """connected_duration depends on CONFIG_PM. The node's own ctime
        tracked it to within a second on real hardware."""
        _make_node(self.tmp.name, "3-7", 3, 7, connected_ms=None)
        age = device.seconds_since_enumeration(_FakeDev())
        self.assertIsNotNone(age)
        self.assertLess(age, 5)

    def test_unknown_device_reports_none(self):
        _make_node(self.tmp.name, "3-7", 3, 7, connected_ms=1000)
        self.assertIsNone(device.seconds_since_enumeration(_FakeDev(9, 9)))

    def test_junk_nodes_are_skipped_not_fatal(self):
        os.makedirs(os.path.join(self.tmp.name, "usb3"), exist_ok=True)  # no busnum/devnum
        _make_node(self.tmp.name, "3-7", 3, 7, connected_ms=2000)
        self.assertAlmostEqual(device.seconds_since_enumeration(_FakeDev()), 2.0)


class PacingTest(unittest.TestCase):
    def _pace(self, age, min_interval=5.0):
        slept = []
        with mock.patch.object(device, "seconds_since_enumeration", return_value=age), \
             mock.patch.object(device.time, "sleep", slept.append):
            device._pace_handshake(_FakeDev(), min_interval)
        return slept

    def test_waits_out_the_remainder_of_the_floor(self):
        self.assertEqual(self._pace(age=1.5), [3.5])

    def test_does_not_wait_when_the_device_has_been_up_a_while(self):
        self.assertEqual(self._pace(age=60.0), [])

    def test_zero_interval_disables_it_entirely(self):
        """--unsafe-no-wait passes 0; it must not even read sysfs."""
        with mock.patch.object(device, "seconds_since_enumeration") as age:
            device._pace_handshake(_FakeDev(), 0)
        age.assert_not_called()

    def test_unknown_age_degrades_to_no_pacing(self):
        """No sysfs (container, odd kernel, not Linux). A safety aid must
        never be the reason a command cannot run."""
        self.assertEqual(self._pace(age=None), [])


class FindStableHidDeviceTest(unittest.TestCase):
    """_find_stable_hid_device() -- from a real incident where a stale
    Device snapshot silently broke pacing during a device that kept
    re-enumerating. See that function's own docstring in pyg7/device.py
    for the full account, including the wire capture that confirmed
    GameSir Nexus's own recovery used a byte-identical handshake and
    differed only in waiting for a stable window first.
    """

    def test_returns_none_immediately_when_no_device_found(self):
        """Must not wait at all -- SwitchToXidMissingDeviceTest in
        test_device.py depends on this being instant, same as the old
        bare find_hid_device() + immediate-return-None it replaced."""
        with mock.patch.object(device, "find_hid_device", return_value=None), \
             mock.patch.object(device.time, "sleep") as sleep:
            result = device._find_stable_hid_device(min_interval=5.0)
        self.assertIsNone(result)
        sleep.assert_not_called()

    def test_zero_min_interval_returns_whatever_was_found_with_no_check(self):
        """--unsafe-no-wait passes 0; must not even read sysfs, same
        contract _pace_handshake() already guarantees."""
        dev = _FakeDev()
        with mock.patch.object(device, "find_hid_device", return_value=dev), \
             mock.patch.object(device, "seconds_since_enumeration") as age:
            result = device._find_stable_hid_device(min_interval=0)
        self.assertIs(result, dev)
        age.assert_not_called()

    def test_already_settled_device_returns_immediately(self):
        dev = _FakeDev()
        with mock.patch.object(device, "find_hid_device", return_value=dev), \
             mock.patch.object(device, "seconds_since_enumeration", return_value=60.0), \
             mock.patch.object(device.time, "sleep") as sleep:
            result = device._find_stable_hid_device(min_interval=5.0)
        self.assertIs(result, dev)
        sleep.assert_not_called()

    def test_unsettled_device_waits_then_returns_it(self):
        """Same device both times (no re-enumeration). Three reads of
        seconds_since_enumeration for one un-settled pass: this function's
        own check, _pace_handshake()'s internal check (the one that decides
        how long to sleep), then this function's re-check of the freshly
        re-found device afterward -- which is what actually confirms it
        settled, not just "we slept the planned amount"."""
        dev = _FakeDev()
        with mock.patch.object(device, "find_hid_device", return_value=dev), \
             mock.patch.object(device, "seconds_since_enumeration", side_effect=[1.0, 1.0, 5.0]), \
             mock.patch.object(device.time, "sleep") as sleep:
            result = device._find_stable_hid_device(min_interval=5.0)
        self.assertIs(result, dev)
        sleep.assert_called_once_with(4.0)

    def test_re_enumeration_during_the_wait_forces_a_fresh_repace(self):
        """The actual regression this item exists for: the device found on
        the first check is NOT the one still there after the pacing sleep
        -- a re-enumeration happened mid-wait. The old code held onto the
        first (by-then-stale) Device object regardless; this must notice
        and return the NEW one, not the stale first one."""
        first_dev = _FakeDev(address=7)
        second_dev = _FakeDev(address=9)  # re-enumerated to a new address
        with mock.patch.object(device, "find_hid_device",
                                side_effect=[first_dev, second_dev]), \
             mock.patch.object(device, "seconds_since_enumeration", side_effect=[1.0, 1.0, 5.0]), \
             mock.patch.object(device.time, "sleep") as sleep:
            result = device._find_stable_hid_device(min_interval=5.0)
        # Settles on the SECOND device, not the stale first one -- this is
        # the whole point: the caller now gets the device that actually
        # exists, not a reference to one that may already be gone.
        self.assertIs(result, second_dev)
        self.assertEqual(sleep.call_count, 1)

    def test_device_vanishing_mid_wait_returns_none(self):
        dev = _FakeDev()
        with mock.patch.object(device, "find_hid_device", side_effect=[dev, None]), \
             mock.patch.object(device, "seconds_since_enumeration", return_value=1.0), \
             mock.patch.object(device.time, "sleep"):
            result = device._find_stable_hid_device(min_interval=5.0)
        self.assertIsNone(result)

    def test_never_settling_gives_up_after_max_wait_s(self):
        """A device stuck re-enumerating forever (the real incident this
        item is from) must not hang -- give up and report None once
        max_wait_s of real time has passed."""
        dev = _FakeDev()
        times = iter([0.0, 0.05, 0.1, 100.0])  # jumps past a tiny max_wait_s
        with mock.patch.object(device, "find_hid_device", return_value=dev), \
             mock.patch.object(device, "seconds_since_enumeration", return_value=0.1), \
             mock.patch.object(device.time, "sleep"), \
             mock.patch.object(device.time, "time", side_effect=lambda: next(times, 100.0)):
            result = device._find_stable_hid_device(min_interval=5.0, max_wait_s=1.0)
        self.assertIsNone(result)


class CliFlagTest(unittest.TestCase):
    def test_flag_maps_to_a_zero_interval(self):
        from g7ctl.main import _min_interval, build_parser
        p = build_parser()
        self.assertEqual(_min_interval(p.parse_args(["list"])),
                         device.HANDSHAKE_MIN_INTERVAL)
        self.assertEqual(_min_interval(p.parse_args(["--unsafe-no-wait", "list"])), 0.0)

    def test_batch_lines_default_to_the_floor(self):
        """Batch/REPL lines are parsed by a second parser that never carries
        the top-level flag. One handshake per batch anyway, so the floor is
        already satisfied -- this just must not raise."""
        from g7ctl.main import _min_interval, _NonExitingArgumentParser, build_parser
        line = build_parser(parser_class=_NonExitingArgumentParser).parse_args(["list"])
        self.assertEqual(_min_interval(line), device.HANDSHAKE_MIN_INTERVAL)
