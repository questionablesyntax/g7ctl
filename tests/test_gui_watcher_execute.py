"""DeviceWatcher._do_execute() -- S6's fast path (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S/DESIGN-SPEC.md 10.3). Mocks
`state_mod.read_state` (as test_gui_watcher_sync.py does for `_do_sync`)
so the fresh-read/read-back values are controlled directly, but passes a
real `TracingFakeSession` for the write itself -- the point of this test
is proving a real `Operation` lands through `FieldSpec.plan_operation()`
and `session.send_addressed()`, not mocking that part away too.

Runs headless; skipped entirely if PyQt6 is absent, same as the other
g7ctlc test modules.
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

from pyg7.field_spec import REPORT_RATE_FIELD
from pyg7.workflow import ApprovedIntent

from .fakes import TracingFakeSession


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class DoExecuteTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self):
        from g7ctlc.watcher import DeviceWatcher

        return DeviceWatcher()

    def _results(self, w):
        results = []
        w.execute_finished.connect(lambda ok, msg, rb: results.append((ok, msg, rb)))
        return results

    def test_empty_draft_writes_nothing_and_reports_success(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        results = self._results(w)
        with mock.patch.object(watcher_mod.state_mod, "read_state") as read_state:
            w._do_execute(TracingFakeSession(), [], baseline_state={}, connection_generation=1)
            read_state.assert_not_called()
        self.assertEqual(results, [(True, "Nothing to write.", None)])

    def test_happy_path_writes_through_a_real_operation_and_confirms_read_back(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        intent = ApprovedIntent(("report_rate_hz",), 500, REPORT_RATE_FIELD, profile=2)
        session = TracingFakeSession()

        fresh = {"report_rate_hz": 1000}
        post_write = {"report_rate_hz": 500}
        with mock.patch.object(watcher_mod.state_mod, "read_state", side_effect=[fresh, post_write]):
            w._do_execute(session, [intent], baseline_state={"report_rate_hz": 1000},
                           connection_generation=1)

        self.assertEqual(len(session.sent), 1)  # exactly one real write landed
        self.assertEqual(len(results), 1)
        ok, msg, read_back = results[0]
        self.assertTrue(ok)
        self.assertTrue(read_back.all_confirmed)
        self.assertIn("written", msg.lower())

    def test_stale_connection_generation_writes_nothing(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 2  # reconnected since the draft was reviewed
        results = self._results(w)
        intent = ApprovedIntent(("report_rate_hz",), 500, REPORT_RATE_FIELD, profile=2)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                return_value={"report_rate_hz": 1000}):
            w._do_execute(session, [intent], baseline_state={"report_rate_hz": 1000},
                           connection_generation=1)  # stale -- captured before the reconnect

        self.assertEqual(session.sent, [])
        self.assertEqual(len(results), 1)
        ok, msg, read_back = results[0]
        self.assertFalse(ok)
        self.assertIsNone(read_back)
        self.assertIn("connection changed", msg.lower())

    def test_conflict_on_the_fresh_reread_writes_nothing(self):
        """Exactly B2's own case: drafted against 500, the device now
        shows 250 (changed while released) -- the fast path must not
        write the user's drafted value over that silently."""
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        intent = ApprovedIntent(("report_rate_hz",), 1000, REPORT_RATE_FIELD, profile=2)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                return_value={"report_rate_hz": 250}):
            w._do_execute(session, [intent], baseline_state={"report_rate_hz": 500},
                           connection_generation=1)

        self.assertEqual(session.sent, [])
        ok, msg, read_back = results[0]
        self.assertFalse(ok)
        self.assertIn("changed on the controller", msg.lower())

    def test_already_satisfied_writes_nothing_and_reports_success(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        intent = ApprovedIntent(("report_rate_hz",), 1000, REPORT_RATE_FIELD, profile=2)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                return_value={"report_rate_hz": 1000}):
            w._do_execute(session, [intent], baseline_state={"report_rate_hz": 500},
                           connection_generation=1)

        self.assertEqual(session.sent, [])
        ok, msg, read_back = results[0]
        self.assertTrue(ok)
        self.assertIn("nothing to write", msg.lower())

    def test_a_real_usb_error_on_the_fresh_read_aborts_and_reraises(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        intent = ApprovedIntent(("report_rate_hz",), 1000, REPORT_RATE_FIELD, profile=2)

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                side_effect=usb.core.USBError("device disappeared")):
            with self.assertRaises(usb.core.USBError):
                w._do_execute(TracingFakeSession(), [intent], baseline_state={"report_rate_hz": 500},
                               connection_generation=1)

        ok, msg, read_back = results[0]
        self.assertFalse(ok)
        self.assertIn("lost connection", msg.lower())


if __name__ == "__main__":
    unittest.main()
