"""DeviceWatcher._establish() tests: the liveness gate.

Raised 2026-07-30 from real daily use: the 2.4GHz dongle enumerates on USB
(and claims, and heartbeats fine) whether or not a physical controller is
actually powered on and paired to it -- they're two separate things joined
by an RF link. Before this fix, DeviceWatcher reported "connected" the
instant the dongle was found, regardless, and every subsequent read/write
just failed silently against a live-looking but dead connection. Runs
unconditionally as of the 2026-08-29 detection redesign -- wired and dongle
alike, since real wired/dongle detection turned out not to be possible at
all (see pyg7/device.py's find_writable_device() docstring).

_connect() (real USB discovery) is monkeypatched to return a fake
session-like object -- these tests are about what _establish() does with
whatever _connect() hands it, not about USB discovery itself. Runs headless
(offscreen platform); skipped entirely if PyQt6 is absent, same as the other
g7ctlc test modules.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


class _FakeSession:
    """Stands in for VendorSession -- just enough surface for _establish()."""

    def __init__(self, via_dongle: bool, live: bool = True):
        self.via_dongle = via_dongle
        self._live = live
        self.settled = False
        self.torn_down = False
        self.probed = False

    def settle(self) -> None:
        self.settled = True

    def probe_controller_live(self) -> bool:
        self.probed = True
        return self._live

    def __exit__(self, *exc) -> bool:
        self.torn_down = True
        return False


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class EstablishSessionTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self, connect_result):
        from g7ctlc.watcher import DeviceWatcher
        watcher = DeviceWatcher()
        watcher._connect = lambda: connect_result
        return watcher

    def test_wired_session_is_probed_too_and_becomes_connected(self):
        # Redesigned 2026-08-29: the liveness probe now runs
        # unconditionally, wired or dongle alike -- real wired/dongle
        # detection turned out not to be possible at all (confirmed via
        # jieli-re's extracted-firmware corpus: a wired baseline and its
        # dongle counterpart share an identical descriptor shape). This
        # test used to assert the opposite (wired must skip the probe
        # entirely) -- a healthy wired connection just passes it the same
        # way any other read succeeds, at the cost of one harmless extra
        # round trip.
        session = _FakeSession(via_dongle=False)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIs(result, session)
        self.assertTrue(session.settled)
        self.assertTrue(session.probed)
        self.assertFalse(session.torn_down)
        self.assertEqual(watcher._state, "connected")

    def test_dongle_session_with_live_controller_becomes_connected(self):
        session = _FakeSession(via_dongle=True, live=True)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIs(result, session)
        self.assertTrue(session.settled)
        self.assertFalse(session.torn_down)
        self.assertEqual(watcher._state, "connected")

    def test_dongle_session_with_no_controller_is_torn_down_not_connected(self):
        session = _FakeSession(via_dongle=True, live=False)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIsNone(result)
        self.assertTrue(session.settled)  # still warms up before probing
        self.assertTrue(session.torn_down)
        self.assertEqual(watcher._state, "no_controller")

    def test_no_device_found_leaves_state_disconnected(self):
        watcher = self._watcher(None)
        result = watcher._establish()
        self.assertIsNone(result)
        self.assertEqual(watcher._state, "disconnected")  # unchanged from init

    def test_no_controller_state_recovers_once_a_controller_answers(self):
        # The whole point of treating this as "keep polling", not a hard
        # error: a real DeviceWatcher.run() loop retries _establish() on its
        # next iteration whenever session is None -- confirm a fresh
        # _establish() call succeeds cleanly right after a failed one, with
        # nothing left over from the torn-down attempt.
        watcher = self._watcher(_FakeSession(via_dongle=True, live=False))
        self.assertIsNone(watcher._establish())
        self.assertEqual(watcher._state, "no_controller")

        recovered = _FakeSession(via_dongle=True, live=True)
        watcher._connect = lambda: recovered
        result = watcher._establish()
        self.assertIs(result, recovered)
        self.assertEqual(watcher._state, "connected")


if __name__ == "__main__":
    unittest.main()


class _BatterySession:
    """Serves scripted read_battery() results; records nothing else."""

    def __init__(self, results):
        self.via_dongle = False
        self._results = list(results)
        self.calls = 0
        self.timeouts = []

    def read_battery(self, timeout=None):
        self.calls += 1
        self.timeouts.append(timeout)
        item = self._results.pop(0) if self._results else TimeoutError("quiet")
        if isinstance(item, Exception):
            raise item
        return item


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class BatteryPollTest(unittest.TestCase):
    """DeviceWatcher._poll_battery().

    The invariant that matters is not the reading -- it is that a battery
    sample can never take the session down. It rides in the same loop that
    heartbeats, and a heartbeat gap is what makes the firmware drop vendor
    mode.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self):
        from g7ctlc.watcher import DeviceWatcher
        return DeviceWatcher()

    def test_emits_a_reading(self):
        from pyg7.session import BatteryStatus
        w = self._watcher()
        seen = []
        w.battery_changed.connect(lambda p, c: seen.append((p, c)))
        w._poll_battery(_BatterySession([BatteryStatus(46, False)]))
        self.assertEqual(seen, [(46, False)])

    def test_rate_limited_between_polls(self):
        from pyg7.session import BatteryStatus
        w = self._watcher()
        sess = _BatterySession([BatteryStatus(46, False), BatteryStatus(47, False)])
        w._poll_battery(sess)
        w._poll_battery(sess)   # immediately after -- must not sample again
        self.assertEqual(sess.calls, 1)

    def test_unchanged_reading_is_not_re_emitted(self):
        from pyg7.session import BatteryStatus
        w = self._watcher()
        seen = []
        w.battery_changed.connect(lambda p, c: seen.append((p, c)))
        sess = _BatterySession([BatteryStatus(46, False), BatteryStatus(46, False)])
        w._poll_battery(sess)
        w._battery_due = 0.0
        w._poll_battery(sess)
        self.assertEqual(len(seen), 1)

    def test_a_timeout_is_swallowed_not_raised(self):
        # A quiet stream must not look like connection loss -- the run loop
        # treats a raised exception as a reason to tear the session down.
        w = self._watcher()
        w._poll_battery(_BatterySession([TimeoutError("quiet")]))  # must not raise

    def test_a_bad_frame_is_swallowed_not_raised(self):
        w = self._watcher()
        w._poll_battery(_BatterySession([ValueError("battery byte out of range")]))

    def test_a_usb_error_still_propagates(self):
        # Genuine connection loss is the run loop's job, not something to
        # hide behind a missing battery reading.
        import usb.core
        w = self._watcher()
        with self.assertRaises(usb.core.USBError):
            w._poll_battery(_BatterySession([usb.core.USBError("no such device")]))

    def test_read_timeout_is_much_tighter_than_a_config_read(self):
        from g7ctlc.watcher import BATTERY_READ_TIMEOUT
        from pyg7.session import READ_CHUNK_TIMEOUT
        self.assertLess(BATTERY_READ_TIMEOUT, READ_CHUNK_TIMEOUT)

    def test_forgetting_clears_and_lets_the_same_value_re_emit(self):
        # Without this, the change-only emit would suppress an identical
        # reading on reconnect and the label would stay blank.
        from pyg7.session import BatteryStatus
        w = self._watcher()
        seen, gone = [], []
        w.battery_changed.connect(lambda p, c: seen.append((p, c)))
        w.battery_unknown.connect(lambda: gone.append(True))
        sess = _BatterySession([BatteryStatus(46, False), BatteryStatus(46, False)])
        w._poll_battery(sess)
        w._forget_battery()
        w._poll_battery(sess)
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(gone), 1)
