"""Unit tests for pyg7.workflow -- S4's prepare/execute (Projects/g7ctl/
redesign/IMPLEMENTATION-PLAN.md, Track S), built from reviews/
FEASIBILITY.md's B2/M1 recommendation. The real bug this exists to fix:
B2's reproduction -- a field changed on the controller while released
gets silently reverted by a stale-baseline diff. These tests assert the
three-way classification and the staleness guard directly; hardware
confirmation that execute() produces the exact same Operations
plan_operation() already produces live is in Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md's S4 status note.
"""
import unittest

from pyg7.field_spec import REPORT_RATE_FIELD, Intent
from pyg7.workflow import (
    ApprovedIntent,
    Classification,
    DraftRevision,
    ExecutionResult,
    FieldOutcome,
    StaleJobError,
    execute,
    prepare,
    read_back,
)

from .fakes import TracingFakeSession


def _intent(path, desired, field_spec=REPORT_RATE_FIELD, profile=1):
    return ApprovedIntent(path=path, desired=desired, field=field_spec, profile=profile)


class ApprovedIntentTest(unittest.TestCase):
    def test_preserve_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            _intent(("report_rate_hz",), Intent.PRESERVE)


class PrepareClassificationTest(unittest.TestCase):
    """Three-way comparison: fresh vs. desired vs. the draft-time
    baseline. The real case B2 names: baseline=50, user wants 70 (a
    button edit elsewhere, this field untouched in the draft), but
    something else changed it to 90 on the device while released."""

    def test_fresh_matches_desired_is_already_satisfied(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 1000})
        self.assertEqual(job.outcomes[0].classification, Classification.ALREADY_SATISFIED)

    def test_fresh_matches_baseline_is_clean(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 500})
        self.assertEqual(job.outcomes[0].classification, Classification.CLEAN)

    def test_fresh_differs_from_both_is_conflict(self):
        # Exactly B2's own example: drafted against 50, device is now 90
        # (changed while released), user wants 70.
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 250})
        self.assertEqual(job.outcomes[0].classification, Classification.CONFLICT)

    def test_clear_intent_already_satisfied_when_fresh_is_none(self):
        from pyg7.field_spec import MOTION_FIELDS

        intent = _intent(("motion", "aim", "activate_button"), Intent.CLEAR,
                          field_spec=MOTION_FIELDS["aim"]["activate_button"])
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"motion": {"aim": {"activate_button": "native_a"}}},
                       fresh_state={"motion": {"aim": {"activate_button": None}}})
        self.assertEqual(job.outcomes[0].classification, Classification.ALREADY_SATISFIED)

    def test_uses_the_fields_own_canonical_comparator(self):
        # Curve points: different Python shapes of the same curve must
        # not look like a conflict just because `==` would say unequal.
        from pyg7.field_spec import STICK_FIELDS

        intent = _intent(("sticks", "left", "curve", "points"), [[0, 0], [50, 60], [100, 100]],
                          field_spec=STICK_FIELDS["left"]["curve_points"])
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"sticks": {"left": {"curve": {"points": [0, 0, 50, 60, 100, 100]}}}},
                       fresh_state={"sticks": {"left": {"curve": {"points": [0, 0, 50, 60, 100, 100]}}}})
        self.assertEqual(job.outcomes[0].classification, Classification.ALREADY_SATISFIED)


class PreparedJobPropertiesTest(unittest.TestCase):
    def test_ready_to_execute_is_false_with_any_conflict(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 250})
        self.assertEqual(job.outcomes[0].classification, Classification.CONFLICT)
        self.assertFalse(job.ready_to_execute)

    def test_ready_to_execute_is_true_with_zero_conflicts(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 500})
        self.assertTrue(job.ready_to_execute)

    def test_writable_excludes_already_satisfied(self):
        satisfied = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [satisfied],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 1000})
        self.assertEqual(job.writable, ())


class ExecuteTest(unittest.TestCase):
    def test_happy_path_writes_against_fresh_baseline_and_returns_outcomes(self):
        intent = _intent(("report_rate_hz",), 1000, profile=2)
        job = prepare("job1", DraftRevision("d1", 1), 7, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 500})
        sess = TracingFakeSession()
        result = execute(sess, job, DraftRevision("d1", 1), 7)
        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(len(result.executed), 1)
        self.assertEqual(len(sess.sent), 1)  # one real write landed

    def test_already_satisfied_outcomes_are_never_executed(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 1000})
        sess = TracingFakeSession()
        result = execute(sess, job, DraftRevision("d1", 1), 1)
        self.assertEqual(result.executed, ())
        self.assertEqual(sess.sent, [])

    def test_stale_draft_revision_raises_and_writes_nothing(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 500})
        sess = TracingFakeSession()
        with self.assertRaises(StaleJobError):
            execute(sess, job, DraftRevision("d1", 2), 1)  # revision bumped since prepare
        self.assertEqual(sess.sent, [])

    def test_stale_connection_generation_raises_and_writes_nothing(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 500})
        sess = TracingFakeSession()
        with self.assertRaises(StaleJobError):
            execute(sess, job, DraftRevision("d1", 1), 2)  # reconnected since prepare
        self.assertEqual(sess.sent, [])

    def test_unresolved_conflict_blocks_execute_without_force(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 250})
        self.assertEqual(job.outcomes[0].classification, Classification.CONFLICT)
        sess = TracingFakeSession()
        with self.assertRaises(ValueError):
            execute(sess, job, DraftRevision("d1", 1), 1)
        self.assertEqual(sess.sent, [])

    def test_force_conflicts_writes_against_the_fresh_value_not_the_stale_draft(self):
        intent = _intent(("report_rate_hz",), 1000)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 250})
        sess = TracingFakeSession()
        result = execute(sess, job, DraftRevision("d1", 1), 1, force_conflicts=True)
        self.assertEqual(len(result.executed), 1)
        self.assertEqual(len(sess.sent), 1)


class ExecutePacingTest(unittest.TestCase):
    """REAL BUG, found on hardware 2026-10-26: execute() fired every
    operation back-to-back with no heartbeat between them, unlike
    state.write_state(). The first multi-scope "Write all changes" (4
    fields across Vibration/Dock/Sticks) landed two writes, silently lost
    the rest ("2 field(s) read back differently than written"), and the
    controller then dropped off USB. Reproduced against the real device:
    unpaced lost writes 3-4, paced all read back correctly."""

    def _three_vibration_job(self):
        from pyg7.field_spec import VIBRATION_LEVEL_FIELDS

        intents = [
            _intent(("vibration", key), 75, VIBRATION_LEVEL_FIELDS[key], profile=4)
            for key in ("left_grip", "right_grip", "left_trigger")
        ]
        fresh = {"vibration": {"left_grip": 25, "right_grip": 25, "left_trigger": 25}}
        return prepare("j", DraftRevision("d", 1), 1, intents, baseline_state=fresh, fresh_state=fresh)

    def _run(self, job, **kwargs):
        from unittest import mock

        trace = []
        sess = TracingFakeSession(trace=trace)
        with mock.patch("pyg7.workflow.time.sleep", side_effect=lambda s: trace.append(("sleep", s))):
            execute(sess, job, DraftRevision("d", 1), 1, **kwargs)
        return [event[0] for event in trace]

    def test_a_single_write_has_no_pacing_at_all(self):
        job = prepare("j", DraftRevision("d", 1), 1, [_intent(("report_rate_hz",), 1000)],
                       baseline_state={"report_rate_hz": 500}, fresh_state={"report_rate_hz": 500})
        self.assertEqual(self._run(job), ["send_raw"])

    def test_a_heartbeat_gap_goes_between_every_pair_of_writes(self):
        kinds = self._run(self._three_vibration_job())
        self.assertEqual(kinds, [
            "send_raw", "sleep", "heartbeat", "sleep",
            "send_raw", "sleep", "heartbeat", "sleep",
            "send_raw",
        ])

    def test_the_gap_uses_the_caller_supplied_interval(self):
        from unittest import mock

        trace = []
        sess = TracingFakeSession(trace=trace)
        with mock.patch("pyg7.workflow.time.sleep", side_effect=lambda s: trace.append(("sleep", s))):
            execute(sess, self._three_vibration_job(), DraftRevision("d", 1), 1, interval=0.123)
        self.assertEqual({e[1] for e in trace if e[0] == "sleep"}, {0.123})

    def test_interval_zero_disables_pacing(self):
        self.assertEqual(self._run(self._three_vibration_job(), interval=0),
                          ["send_raw", "send_raw", "send_raw"])

    def test_a_skipped_already_satisfied_intent_does_not_trigger_a_gap(self):
        from pyg7.field_spec import VIBRATION_LEVEL_FIELDS

        intents = [
            _intent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=4),
            _intent(("vibration", "right_grip"), 75, VIBRATION_LEVEL_FIELDS["right_grip"], profile=4),
        ]
        # left_grip already satisfied on the device, only right_grip needs a write.
        fresh = {"vibration": {"left_grip": 75, "right_grip": 25}}
        job = prepare("j", DraftRevision("d", 1), 1, intents,
                       baseline_state={"vibration": {"left_grip": 25, "right_grip": 25}}, fresh_state=fresh)
        self.assertEqual(self._run(job), ["send_raw"])


class ButtonFieldExecuteTest(unittest.TestCase):
    """`ButtonFieldSpec` through the REAL prepare()/execute() path, not
    just a direct plan_operation() call -- the actual thing the
    `(desired, profile)` -> `(desired, baseline, profile)` signature fix
    unblocks (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md's Track S
    notes: execute()'s call site is one uniform `plan_operation(desired,
    baseline, profile)` shape for every field type, and the old 2-arg
    form raised TypeError through it)."""

    def test_a_real_remap_executes_through_the_uniform_call_site(self):
        from pyg7.field_spec import BUTTON_FIELDS

        intent = _intent(("buttons", "default", "a"), "native_x",
                          field_spec=BUTTON_FIELDS["default"]["a"], profile=2)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"buttons": {"default": {"a": "native_b"}}},
                       fresh_state={"buttons": {"default": {"a": "native_b"}}})
        self.assertEqual(job.outcomes[0].classification, Classification.CLEAN)
        sess = TracingFakeSession()
        result = execute(sess, job, DraftRevision("d1", 1), 1)
        self.assertEqual(len(result.executed), 1)
        self.assertEqual(len(sess.sent), 1)

    def test_a_clear_intent_executes_an_unbind_through_the_uniform_call_site(self):
        from pyg7.field_spec import BUTTON_FIELDS

        intent = _intent(("buttons", "default", "a"), Intent.CLEAR,
                          field_spec=BUTTON_FIELDS["default"]["a"], profile=1)
        job = prepare("job1", DraftRevision("d1", 1), 1, [intent],
                       baseline_state={"buttons": {"default": {"a": "native_b"}}},
                       fresh_state={"buttons": {"default": {"a": "native_b"}}})
        self.assertEqual(job.outcomes[0].classification, Classification.CLEAN)
        sess = TracingFakeSession()
        result = execute(sess, job, DraftRevision("d1", 1), 1)
        self.assertEqual(len(result.executed), 1)
        self.assertEqual(len(sess.sent), 1)


class ReadBackTest(unittest.TestCase):
    """read_back() -- S5's "read back" step, the one thing the vertical
    slice needs beyond draft/fast-path/prepare/execute. Additional
    traffic, not part of S1's wire-parity gate (FEASIBILITY.md M1)."""

    def _executed(self, path, desired, fresh_value, field_spec=REPORT_RATE_FIELD, profile=1):
        intent = _intent(path, desired, field_spec, profile)
        outcome = FieldOutcome(intent, Classification.CLEAN, baseline_value=None, fresh_value=fresh_value)
        return ExecutionResult(job_id="job1", executed=(outcome,))

    def test_matching_post_write_value_is_confirmed(self):
        result = self._executed(("report_rate_hz",), 1000, fresh_value=500)
        rb = read_back(result, post_write_state={"report_rate_hz": 1000})
        self.assertEqual(len(rb.ok), 1)
        self.assertEqual(rb.mismatched, ())
        self.assertTrue(rb.all_confirmed)

    def test_mismatched_post_write_value_is_flagged_not_silently_accepted(self):
        result = self._executed(("report_rate_hz",), 1000, fresh_value=500)
        rb = read_back(result, post_write_state={"report_rate_hz": 500})  # write didn't take
        self.assertEqual(rb.ok, ())
        self.assertEqual(len(rb.mismatched), 1)
        self.assertFalse(rb.all_confirmed)

    def test_clear_intent_confirmed_when_post_write_value_is_none(self):
        from pyg7.field_spec import MOTION_FIELDS

        result = self._executed(("motion", "aim", "activate_button"), Intent.CLEAR,
                                 fresh_value="native_a", field_spec=MOTION_FIELDS["aim"]["activate_button"])
        rb = read_back(result, post_write_state={"motion": {"aim": {"activate_button": None}}})
        self.assertTrue(rb.all_confirmed)

    def test_curve_points_canonical_comparator_used_for_confirmation(self):
        from pyg7.field_spec import STICK_FIELDS

        result = self._executed(("sticks", "left", "curve", "points"), [[0, 0], [50, 60], [100, 100]],
                                 fresh_value=None, field_spec=STICK_FIELDS["left"]["curve_points"])
        rb = read_back(result, post_write_state={
            "sticks": {"left": {"curve": {"points": [0, 0, 50, 60, 100, 100]}}}})  # same curve, flat shape
        self.assertTrue(rb.all_confirmed)


if __name__ == "__main__":
    unittest.main()
