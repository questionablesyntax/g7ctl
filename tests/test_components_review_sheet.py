"""ReviewSheet tests, S6's wave-2 escalation path (Projects/g7ctl/
redesign/IMPLEMENTATION-PLAN.md, Track S/DESIGN-SPEC.md 10.3). Runs
headless (offscreen platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QDialog
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.field_spec import REPORT_RATE_FIELD, VIBRATION_LEVEL_FIELDS, Intent
from pyg7.workflow import ApprovedIntent, Classification, DraftRevision, prepare


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class FormatFieldLabelTest(unittest.TestCase):
    def test_joins_and_title_cases_every_path_part(self):
        from g7ctlc.review_sheet import format_field_label

        self.assertEqual(format_field_label(("vibration", "left_grip")), "Vibration, Left Grip")
        self.assertEqual(
            format_field_label(("triggers", "left", "deadzone", "initial")),
            "Triggers, Left, Deadzone, Initial")

    def test_single_element_path(self):
        from g7ctlc.review_sheet import format_field_label

        self.assertEqual(format_field_label(("report_rate_hz",)), "Report Rate Hz")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class FormatFieldValueTest(unittest.TestCase):
    def test_bool(self):
        from g7ctlc.review_sheet import format_field_value

        self.assertEqual(format_field_value(True), "On")
        self.assertEqual(format_field_value(False), "Off")

    def test_known_keycode(self):
        from g7ctlc.review_sheet import format_field_value

        self.assertEqual(format_field_value("native_a"), "Native: A")

    def test_unknown_string_is_title_cased(self):
        from g7ctlc.review_sheet import format_field_value

        self.assertEqual(format_field_value("left_stick"), "Left Stick")

    def test_intent_clear_shows_the_same_wording_as_a_real_unbind(self):
        from g7ctlc.review_sheet import format_field_value
        from g7ctlc.widgets import keycode_display_text

        self.assertEqual(format_field_value(Intent.CLEAR), keycode_display_text(None))

    def test_none_without_keycode_context_is_unknown(self):
        from g7ctlc.review_sheet import format_field_value

        self.assertEqual(format_field_value(None), "Unknown")

    def test_none_with_keycode_context_matches_the_fields_own_unbound_wording(self):
        from g7ctlc.review_sheet import format_field_value
        from g7ctlc.widgets import keycode_display_text

        self.assertEqual(format_field_value(None, keycode=True), keycode_display_text(None))

    def test_plain_int(self):
        from g7ctlc.review_sheet import format_field_value

        self.assertEqual(format_field_value(75), "75")


def _report_rate_job(desired=1000, baseline=500, fresh=500):
    intent = ApprovedIntent(("report_rate_hz",), desired, REPORT_RATE_FIELD, profile=2)
    return prepare("t", DraftRevision("t", 1), 1, [intent],
                    baseline_state={"report_rate_hz": baseline}, fresh_state={"report_rate_hz": fresh})


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ReviewSheetTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.fonts import load_fonts
        from g7ctlc.palette import DARK_PALETTE

        self.palette = DARK_PALETTE
        self.font_load = load_fonts()

    def test_title_names_the_real_change_count(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job()
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        self.assertEqual(sheet.windowTitle(), "Write 1 change to the controller?")
        self.assertEqual(sheet.write_btn.text(), "Write 1 change")

    def test_already_satisfied_outcomes_are_excluded_from_the_count(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job(desired=500, baseline=1000, fresh=500)  # fresh already matches desired
        self.assertEqual(job.outcomes[0].classification, Classification.ALREADY_SATISFIED)
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        self.assertEqual(sheet.windowTitle(), "Write 0 changes to the controller?")
        self.assertFalse(sheet.write_btn.isEnabled())

    def test_conflict_row_shows_the_now_on_controller_value(self):
        """CRITIC.md #4's disposition: "row mark, 'Now 10% on the
        controller', re-review"."""
        from PyQt6.QtWidgets import QLabel

        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job(desired=1000, baseline=500, fresh=250)  # drafted against 500, now 250
        self.assertEqual(job.outcomes[0].classification, Classification.CONFLICT)
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        texts = [lbl.text() for lbl in sheet.findChildren(QLabel)]
        self.assertTrue(any("Changed on the controller" in t and "250" in t for t in texts))

    def test_no_conflict_banner_when_nothing_conflicts(self):
        from PyQt6.QtWidgets import QLabel

        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job()  # CLEAN, no conflict
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        texts = [lbl.text() for lbl in sheet.findChildren(QLabel)]
        self.assertFalse(any("changed on the controller" in t.lower() for t in texts))

    def test_clicking_write_accepts_the_dialog(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job()
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        sheet.write_btn.click()
        self.assertEqual(sheet.result(), QDialog.DialogCode.Accepted)

    def test_clicking_keep_editing_rejects_the_dialog(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job()
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        sheet.keep_editing_btn.click()
        self.assertEqual(sheet.result(), QDialog.DialogCode.Rejected)

    def test_vibration_levels_batch_builds_one_row_per_field(self):
        from g7ctlc.review_sheet import ReviewSheet

        intents = [
            ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2),
            ApprovedIntent(("vibration", "right_grip"), 75, VIBRATION_LEVEL_FIELDS["right_grip"], profile=2),
        ]
        fresh = {"vibration": {"left_grip": 25, "right_grip": 25}}
        job = prepare("t", DraftRevision("t", 1), 1, intents, baseline_state=fresh, fresh_state=fresh)
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        self.assertEqual(sheet.windowTitle(), "Write 2 changes to the controller?")


if __name__ == "__main__":
    unittest.main()
