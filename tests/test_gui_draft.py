"""Unit tests for g7ctlc.draft -- the GUI-side observed/draft adapter
built for S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S).
Pure data, no Qt -- mirrors tests/test_workflow.py's own scope boundary
(this module has no dependency on pyg7.session either)."""
import unittest

from g7ctlc.draft import DesiredDraft, FieldMark, ObservedSnapshot
from pyg7.field_spec import REPORT_RATE_FIELD, VIBRATION_LEVEL_FIELDS, Intent


class ObservedSnapshotTest(unittest.TestCase):
    def test_unconfirmed_snapshot_reports_every_path_as_unknown(self):
        snap = ObservedSnapshot({"report_rate_hz": 1000}, confirmed=False)
        self.assertIsNone(snap.get(("report_rate_hz",)))

    def test_confirmed_snapshot_reads_the_real_value(self):
        snap = ObservedSnapshot({"vibration": {"left_grip": 50}}, confirmed=True)
        self.assertEqual(snap.get(("vibration", "left_grip")), 50)

    def test_confirmed_snapshot_missing_path_is_none_not_an_error(self):
        snap = ObservedSnapshot({"vibration": {}}, confirmed=True)
        self.assertIsNone(snap.get(("vibration", "left_grip")))

    def test_imported_flag_is_just_recorded_not_interpreted(self):
        snap = ObservedSnapshot({}, confirmed=True, imported=True)
        self.assertTrue(snap.imported)
        self.assertTrue(snap.confirmed)  # import confirms the state for editing


class DesiredDraftTouchTest(unittest.TestCase):
    def test_touch_records_the_observed_value_at_touch_time(self):
        snap = ObservedSnapshot({"report_rate_hz": 500}, confirmed=True)
        draft = DesiredDraft(snap)
        draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, 1000, profile=2)
        mark = draft.mark_for(("report_rate_hz",))
        self.assertIsInstance(mark, FieldMark)
        self.assertEqual(mark.observed, 500)
        self.assertEqual(mark.desired, 1000)
        self.assertEqual(mark.profile, 2)

    def test_touch_against_unconfirmed_snapshot_records_unknown_observed(self):
        snap = ObservedSnapshot({"report_rate_hz": 500}, confirmed=False)
        draft = DesiredDraft(snap)
        draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, 1000, profile=1)
        self.assertIsNone(draft.mark_for(("report_rate_hz",)).observed)

    def test_touching_the_same_path_twice_replaces_not_accumulates(self):
        snap = ObservedSnapshot({"report_rate_hz": 500}, confirmed=True)
        draft = DesiredDraft(snap)
        draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, 250, profile=1)
        draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, 1000, profile=1)
        self.assertEqual(draft.edit_count, 1)
        self.assertEqual(draft.mark_for(("report_rate_hz",)).desired, 1000)

    def test_preserve_is_rejected_the_same_way_approvedintent_rejects_it(self):
        snap = ObservedSnapshot({}, confirmed=True)
        draft = DesiredDraft(snap)
        with self.assertRaises(ValueError):
            draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, Intent.PRESERVE, profile=1)

    def test_untouch_drops_the_mark(self):
        snap = ObservedSnapshot({"report_rate_hz": 500}, confirmed=True)
        draft = DesiredDraft(snap)
        draft.touch(("report_rate_hz",), REPORT_RATE_FIELD, 1000, profile=1)
        draft.untouch(("report_rate_hz",))
        self.assertFalse(draft.is_touched(("report_rate_hz",)))
        self.assertEqual(draft.edit_count, 0)

    def test_untouch_an_untouched_path_is_a_quiet_no_op(self):
        draft = DesiredDraft(ObservedSnapshot({}, confirmed=True))
        draft.untouch(("report_rate_hz",))  # must not raise

    def test_discard_clears_every_mark(self):
        snap = ObservedSnapshot({"vibration": {"left_grip": 50, "right_grip": 50}}, confirmed=True)
        draft = DesiredDraft(snap)
        draft.touch(("vibration", "left_grip"), VIBRATION_LEVEL_FIELDS["left_grip"], 75, profile=1)
        draft.touch(("vibration", "right_grip"), VIBRATION_LEVEL_FIELDS["right_grip"], 25, profile=1)
        draft.discard()
        self.assertEqual(draft.edit_count, 0)
        self.assertEqual(draft.marks, ())


class DesiredDraftApprovedIntentsTest(unittest.TestCase):
    def test_to_approved_intents_round_trips_every_mark(self):
        from pyg7.workflow import ApprovedIntent

        snap = ObservedSnapshot({"vibration": {"left_grip": 50, "right_grip": 50}}, confirmed=True)
        draft = DesiredDraft(snap)
        draft.touch(("vibration", "left_grip"), VIBRATION_LEVEL_FIELDS["left_grip"], 75, profile=3)
        draft.touch(("vibration", "right_grip"), VIBRATION_LEVEL_FIELDS["right_grip"], 25, profile=3)
        intents = draft.to_approved_intents()
        self.assertEqual(len(intents), 2)
        self.assertTrue(all(isinstance(i, ApprovedIntent) for i in intents))
        by_path = {i.path: i for i in intents}
        self.assertEqual(by_path[("vibration", "left_grip")].desired, 75)
        self.assertEqual(by_path[("vibration", "right_grip")].desired, 25)

    def test_empty_draft_yields_no_intents(self):
        draft = DesiredDraft(ObservedSnapshot({}, confirmed=True))
        self.assertEqual(draft.to_approved_intents(), [])


if __name__ == "__main__":
    unittest.main()
