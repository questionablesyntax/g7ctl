"""DeviceWatcher._do_sync() fail-closed test (S2, Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S).

Before this phase, a baseline read failure short of a real USBError (e.g.
a read_chunk() timeout) fell back to a full write -- `baseline=None`,
meaning the entire displayed state gets written over whatever the device
actually has, including anything changed on the controller itself since
the last read (plan section 7's own finding). This asserts the real fix:
that failure now aborts the sync with no write at all. A genuine
USBError's existing behaviour (abort + re-raise, unrelated to this phase)
is asserted too, as the control case this must NOT change.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent,
same as the other g7ctlc test modules.
"""
import os
import unittest
from unittest import mock

import usb.core

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class DoSyncFailClosedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self):
        from g7ctlc.watcher import DeviceWatcher
        return DeviceWatcher()

    def test_a_non_usb_baseline_read_failure_aborts_without_writing(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        results = []
        w.sync_finished.connect(lambda ok, msg: results.append((ok, msg)))

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                side_effect=TimeoutError("no response to read_chunk")):
            with mock.patch.object(watcher_mod.state_mod, "write_state") as write_state:
                w._do_sync(object(), {"controller_slot": 1})
                write_state.assert_not_called()

        self.assertEqual(len(results), 1)
        ok, msg = results[0]
        self.assertFalse(ok)
        self.assertIn("could not read", msg.lower())

    def test_a_real_usb_error_on_the_baseline_read_still_aborts_and_reraises(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        results = []
        w.sync_finished.connect(lambda ok, msg: results.append((ok, msg)))

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                side_effect=usb.core.USBError("device disappeared")):
            with mock.patch.object(watcher_mod.state_mod, "write_state") as write_state:
                with self.assertRaises(usb.core.USBError):
                    w._do_sync(object(), {"controller_slot": 1})
                write_state.assert_not_called()

        self.assertEqual(len(results), 1)
        ok, msg = results[0]
        self.assertFalse(ok)
        self.assertIn("lost connection", msg.lower())


if __name__ == "__main__":
    unittest.main()
