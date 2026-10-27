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

    def test_conflict_on_the_fresh_reread_escalates_to_needs_review(self):
        """Exactly B2's own case: drafted against 500, the device now
        shows 250 (changed while released) -- DESIGN-SPEC.md 10.3: "If it
        finds a conflict... it escalates to the full review sheet," not a
        plain failure. The fast path must not write the user's drafted
        value over that silently either way."""
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        reviews = []
        w.needs_review.connect(lambda job, fresh: reviews.append((job, fresh)))
        intent = ApprovedIntent(("report_rate_hz",), 1000, REPORT_RATE_FIELD, profile=2)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state",
                                return_value={"report_rate_hz": 250}):
            w._do_execute(session, [intent], baseline_state={"report_rate_hz": 500},
                           connection_generation=1)

        self.assertEqual(session.sent, [])
        self.assertEqual(results, [])  # no execute_finished -- needs_review instead
        self.assertEqual(len(reviews), 1)
        job, fresh_state = reviews[0]
        self.assertEqual(len(job.conflicts), 1)
        self.assertEqual(fresh_state, {"report_rate_hz": 250})

    def test_more_than_three_rows_escalates_even_with_no_conflict(self):
        """DESIGN-SPEC.md 10.3: "Any change touching shared scope, or
        more than three rows, always uses the sheet" -- regardless of
        whether prepare() found anything wrong."""
        from g7ctlc import watcher as watcher_mod
        from pyg7.field_spec import VIBRATION_LEVEL_FIELDS

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        reviews = []
        w.needs_review.connect(lambda job, fresh: reviews.append((job, fresh)))
        intents = [
            ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2),
            ApprovedIntent(("vibration", "right_grip"), 75, VIBRATION_LEVEL_FIELDS["right_grip"], profile=2),
            ApprovedIntent(("vibration", "left_trigger"), 75, VIBRATION_LEVEL_FIELDS["left_trigger"], profile=2),
            ApprovedIntent(("vibration", "right_trigger"), 75, VIBRATION_LEVEL_FIELDS["right_trigger"], profile=2),
        ]
        fresh = {"vibration": {"left_grip": 25, "right_grip": 25, "left_trigger": 25, "right_trigger": 25}}
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state", return_value=fresh):
            w._do_execute(session, intents, baseline_state=fresh, connection_generation=1)

        self.assertEqual(session.sent, [])
        self.assertEqual(results, [])
        self.assertEqual(len(reviews), 1)
        job, _fresh_state = reviews[0]
        self.assertEqual(job.conflicts, ())  # no conflict -- escalated purely on row count
        self.assertEqual(len(job.outcomes), 4)

    def test_a_single_no_conflict_dock_row_writes_directly_without_the_sheet(self):
        """Dock is shared scope, but scope membership alone no longer
        forces needs_review() -- tried 2026-10-26, dropped the same day
        after it meant a single-field, no-conflict Dock write always
        popped the sheet (reported on hardware as a sizing bug, but the
        real objection once the sheet rendered correctly was that it
        showed up every time at all). Same escalation rule as every
        other scope now: a real conflict or more than three rows."""
        from g7ctlc import watcher as watcher_mod
        from pyg7.field_spec import DOCK_FIELDS

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        reviews = []
        w.needs_review.connect(lambda job, fresh: reviews.append((job, fresh)))
        intent = ApprovedIntent(("dock_led_brightness",), 75, DOCK_FIELDS["dock_led_brightness"], profile=1)
        session = TracingFakeSession()
        fresh = {"dock_led_brightness": 50}
        post_write = {"dock_led_brightness": 75}

        with mock.patch.object(watcher_mod.state_mod, "read_state", side_effect=[fresh, post_write]):
            w._do_execute(session, [intent], baseline_state={"dock_led_brightness": 50},
                           connection_generation=1)

        self.assertEqual(reviews, [])
        self.assertEqual(len(session.sent), 1)  # a real write landed, not just prepared
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0][0])  # success

    def _multi_scope_batch(self, dock_fresh):
        from pyg7.field_spec import DOCK_FIELDS, VIBRATION_LEVEL_FIELDS

        intents = [
            ApprovedIntent(("vibration", key), 75, VIBRATION_LEVEL_FIELDS[key], profile=2)
            for key in ("left_grip", "right_grip", "left_trigger")
        ] + [ApprovedIntent(("dock_led_brightness",), 100, DOCK_FIELDS["dock_led_brightness"], profile=1)]
        baseline = {"vibration": {"left_grip": 25, "right_grip": 25, "left_trigger": 25},
                    "dock_led_brightness": 50}
        fresh = {"vibration": dict(baseline["vibration"]), "dock_led_brightness": dock_fresh}
        return intents, baseline, fresh

    def test_a_multi_scope_batch_over_three_rows_writes_directly_without_the_sheet(self):
        """2026-10-26, after the first hardware run: a 4-field
        "Write all changes" across three pages opened the sheet purely
        for being >3 rows. The sheet is a soft-error surface -- row count
        alone isn't one when the batch spans more than one scope (the
        >3-rows rule stays a single-scope concept; see the test above
        for that)."""
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        reviews = []
        w.needs_review.connect(lambda job, fresh: reviews.append(job))
        intents, baseline, fresh = self._multi_scope_batch(dock_fresh=50)
        post_write = {"vibration": {"left_grip": 75, "right_grip": 75, "left_trigger": 75},
                      "dock_led_brightness": 100}
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state", side_effect=[fresh, post_write]), \
                mock.patch("pyg7.workflow.time.sleep"):
            w._do_execute(session, intents, baseline_state=baseline, connection_generation=1)

        self.assertEqual(reviews, [])
        self.assertEqual(len(session.sent), 4)  # all four really written
        self.assertTrue(results[0][0])

    def test_a_multi_scope_batch_with_a_real_conflict_still_escalates(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        reviews = []
        w.needs_review.connect(lambda job, fresh: reviews.append(job))
        # Dock was 50 when drafted, 100 wanted, but is 25 on the controller now.
        intents, baseline, fresh = self._multi_scope_batch(dock_fresh=25)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state", return_value=fresh):
            w._do_execute(session, intents, baseline_state=baseline, connection_generation=1)

        self.assertEqual(session.sent, [])  # nothing written yet
        self.assertEqual(results, [])
        self.assertEqual(len(reviews), 1)
        self.assertEqual(len(reviews[0].conflicts), 1)

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


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class DoExecuteReviewedTest(unittest.TestCase):
    """DeviceWatcher._do_execute_reviewed() -- the ReviewSheet's own Write
    action, running execute() directly against an already-prepared job
    (no second read/prepare). Mirrors DoExecuteTest's own mocking shape.
    """
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

    def _prepared_job(self, desired=500, baseline=1000, fresh=1000):
        from pyg7.workflow import DraftRevision, prepare

        intent = ApprovedIntent(("report_rate_hz",), desired, REPORT_RATE_FIELD, profile=2)
        return prepare("reviewed", DraftRevision("reviewed", 1), 1, [intent],
                        baseline_state={"report_rate_hz": baseline}, fresh_state={"report_rate_hz": fresh})

    def test_happy_path_writes_the_prepared_job_and_confirms_read_back(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        job = self._prepared_job()
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state", return_value={"report_rate_hz": 500}):
            w._do_execute_reviewed(session, job, connection_generation=1, force_conflicts=False)

        self.assertEqual(len(session.sent), 1)
        self.assertEqual(len(results), 1)
        ok, msg, read_back = results[0]
        self.assertTrue(ok)
        self.assertTrue(read_back.all_confirmed)

    def test_force_conflicts_writes_the_desired_value_despite_the_conflict(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        # drafted against 1000, device now shows 250 -- a real conflict
        job = self._prepared_job(desired=500, baseline=1000, fresh=250)
        self.assertEqual(len(job.conflicts), 1)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state", return_value={"report_rate_hz": 500}):
            w._do_execute_reviewed(session, job, connection_generation=1, force_conflicts=True)

        self.assertEqual(len(session.sent), 1)  # the user's own approved write still lands
        ok, _msg, read_back = results[0]
        self.assertTrue(ok)

    def test_without_force_conflicts_an_outstanding_conflict_reports_failure_and_writes_nothing(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        w._connection_generation = 1
        results = self._results(w)
        job = self._prepared_job(desired=500, baseline=1000, fresh=250)
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state"):
            w._do_execute_reviewed(session, job, connection_generation=1, force_conflicts=False)

        self.assertEqual(session.sent, [])
        ok, msg, read_back = results[0]
        self.assertFalse(ok)
        self.assertIsNone(read_back)
        self.assertIn("unresolved conflict", msg.lower())

    def test_stale_connection_generation_writes_nothing(self):
        from g7ctlc import watcher as watcher_mod

        w = self._watcher()
        results = self._results(w)
        job = self._prepared_job()
        session = TracingFakeSession()

        with mock.patch.object(watcher_mod.state_mod, "read_state"):
            w._do_execute_reviewed(session, job, connection_generation=99, force_conflicts=False)

        self.assertEqual(session.sent, [])
        ok, msg, read_back = results[0]
        self.assertFalse(ok)
        self.assertIn("connection changed", msg.lower())


if __name__ == "__main__":
    unittest.main()
