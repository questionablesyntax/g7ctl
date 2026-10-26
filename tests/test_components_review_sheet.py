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
        # CRITIC.md #12's own disposition: zero rows shows "Nothing left
        # to write," not a "Write 0 changes" button -- and the sheet
        # stays open rather than auto-closing.
        self.assertEqual(sheet.windowTitle(), "Nothing left to write.")
        self.assertFalse(sheet.write_btn.isEnabled())
        self.assertFalse(sheet._empty_notice.isHidden())

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
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job()  # CLEAN, no conflict
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        # The banner label always exists now (a later per-row revert can
        # toggle it back on), so visibility -- not mere presence in the
        # widget tree -- is what "no banner" actually means.
        self.assertTrue(sheet._conflict_notice.isHidden())

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


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ReviewSheetRowRevertTest(unittest.TestCase):
    """Per-row revert (IMPLEMENTATION-PLAN.md's "Not started" list, item
    3 -- CRITIC.md #12's own mockup shows one, and its own complaint
    about the sheet "clos[ing] itself under the pointer when the last
    row is reverted")."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.fonts import load_fonts
        from g7ctlc.palette import DARK_PALETTE

        self.palette = DARK_PALETTE
        self.font_load = load_fonts()

    def _two_row_job(self):
        intents = [
            ApprovedIntent(("vibration", "left_grip"), 75, VIBRATION_LEVEL_FIELDS["left_grip"], profile=2),
            ApprovedIntent(("vibration", "right_grip"), 75, VIBRATION_LEVEL_FIELDS["right_grip"], profile=2),
        ]
        fresh = {"vibration": {"left_grip": 25, "right_grip": 25}}
        return prepare("t", DraftRevision("t", 1), 1, intents, baseline_state=fresh, fresh_state=fresh)

    def test_clicking_a_rows_revert_link_emits_the_rows_path(self):
        from g7ctlc.review_sheet import ReviewSheet

        sheet = ReviewSheet(self._two_row_job(), "Profile 2", self.palette, self.font_load)
        reverted = []
        sheet.rowReverted.connect(lambda path: reverted.append(path))

        # Row widgets are [field, was, will_be, revert_btn, (conflict_label)]
        # -- index 3, not -1, since a CONFLICT row appends a 5th widget
        # after the button.
        sheet._row_widgets[("vibration", "left_grip")][3].click()

        self.assertEqual(reverted, [("vibration", "left_grip")])

    def test_reverting_one_row_of_two_narrows_the_job_and_relabels_write(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = self._two_row_job()
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)

        sheet._row_widgets[("vibration", "left_grip")][-1].click()

        self.assertEqual(len(sheet.job.writable), 1)
        self.assertEqual(sheet.job.writable[0].intent.path, ("vibration", "right_grip"))
        self.assertEqual(sheet.windowTitle(), "Write 1 change to the controller?")
        self.assertEqual(sheet.write_btn.text(), "Write 1 change")
        self.assertTrue(sheet.write_btn.isEnabled())
        # The original job the caller passed in is untouched -- only
        # this sheet's own copy narrows.
        self.assertEqual(len(job.writable), 2)

    def test_reverted_rows_widgets_are_hidden(self):
        from g7ctlc.review_sheet import ReviewSheet

        sheet = ReviewSheet(self._two_row_job(), "Profile 2", self.palette, self.font_load)
        widgets = sheet._row_widgets[("vibration", "left_grip")]

        widgets[3].click()  # that row's own Revert button

        for widget in widgets:
            self.assertTrue(widget.isHidden())

    def test_reverting_the_only_row_shows_nothing_left_to_write_without_closing(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job()
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        closed = []
        sheet.accepted.connect(lambda: closed.append("accepted"))
        sheet.rejected.connect(lambda: closed.append("rejected"))

        sheet._row_widgets[("report_rate_hz",)][3].click()

        self.assertEqual(sheet.windowTitle(), "Nothing left to write.")
        self.assertFalse(sheet.write_btn.isEnabled())
        self.assertFalse(sheet._empty_notice.isHidden())
        # Still open, not auto-closed -- CRITIC.md #12's own complaint
        # about the sheet "clos[ing] itself under the pointer when the
        # last row is reverted".
        self.assertEqual(closed, [])

    def test_reverting_the_only_conflicting_row_hides_the_conflict_banner(self):
        from g7ctlc.review_sheet import ReviewSheet

        job = _report_rate_job(desired=1000, baseline=500, fresh=250)  # CONFLICT
        sheet = ReviewSheet(job, "Profile 2", self.palette, self.font_load)
        self.assertFalse(sheet._conflict_notice.isHidden())  # sanity

        sheet._row_widgets[("report_rate_hz",)][3].click()

        self.assertTrue(sheet._conflict_notice.isHidden())


if __name__ == "__main__":
    unittest.main()
