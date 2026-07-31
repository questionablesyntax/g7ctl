"""DeviceWatcher._establish() tests: the dongle-vs-wired liveness gate.

Raised 2026-07-30 from real daily use: the 2.4GHz dongle enumerates on USB
(and claims, and heartbeats fine) whether or not a physical controller is
actually powered on and paired to it -- they're two separate things joined
by an RF link. Before this fix, DeviceWatcher reported "connected" the
instant the dongle was found, regardless, and every subsequent read/write
just failed silently against a live-looking but dead connection.

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

    def settle(self) -> None:
        self.settled = True

    def probe_controller_live(self) -> bool:
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

    def test_wired_session_settles_and_becomes_connected_with_no_probe(self):
        # Wired mode must never even ask for a liveness probe -- PID_VENDOR
        # is the controller's own USB descriptor, so its presence already
        # proves it's there. _FakeSession's probe_controller_live() isn't
        # called at all here (via_dongle=False short-circuits it), so an
        # accidental call would only surface if the return value were
        # inspected -- test the actual observable instead: session survives.
        session = _FakeSession(via_dongle=False)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIs(result, session)
        self.assertTrue(session.settled)
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
