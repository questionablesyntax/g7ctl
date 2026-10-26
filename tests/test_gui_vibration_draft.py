"""VibrationView's S6 per-field draft slice (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- `fieldTouched`/`fieldReverted` and
the "was X%"/revert UI for the four level fields. The Force/Sync flags
are deliberately out of scope here -- see vibration_view.py's own module
docstring for why.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod
from pyg7.field_spec import VIBRATION_LEVEL_FIELDS


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class VibrationFieldTouchedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, **vibration_overrides):
        from g7ctlc.views.vibration_view import VibrationView

        state = state_mod.default_state_dict("test")
        state["controller_slot"] = 3
        state["vibration"].update(vibration_overrides)
        view = VibrationView()
        view.load_state(state)
        return view, state

    def test_moving_a_level_emits_fieldTouched_with_the_right_path_field_and_profile(self):
        # SegmentedControl's own selectionChanged already fires once per
        # button whose checked state flips within the exclusive group (the
        # old segment unchecking AND the new one checking both toggle it,
        # pre-existing behaviour _mark_slider_touched/_on_edit already
        # tolerate) -- so a single move can legitimately emit fieldTouched
        # more than once. What must hold is that every emission for this
        # move reports the same, correct destination.
        view, state = self._view_with_state(left_grip=25)
        touches = []
        view.fieldTouched.connect(lambda path, field, desired, profile: touches.append((path, field, desired, profile)))

        view.sliders["left_grip"].set_value("75")

        self.assertGreaterEqual(len(touches), 1)
        for path, field, desired, profile in touches:
            self.assertEqual(path, ("vibration", "left_grip"))
            self.assertIs(field, VIBRATION_LEVEL_FIELDS["left_grip"])
            self.assertEqual(desired, 75)
            self.assertEqual(profile, 3)

    def test_mark_and_revert_button_appear_only_after_a_real_touch(self):
        # isHidden(), not isVisible() -- same reasoning as
        # test_components_segmented_control.py's own caption test: this
        # widget is never shown on screen here, and isVisible() answers
        # false for every child of an unshown top-level regardless of
        # setVisible().
        view, state = self._view_with_state(left_grip=25)
        self.assertTrue(view._was_labels["left_grip"].isHidden())
        self.assertTrue(view._revert_buttons["left_grip"].isHidden())

        view.sliders["left_grip"].set_value("75")

        self.assertFalse(view._was_labels["left_grip"].isHidden())
        self.assertIn("25", view._was_labels["left_grip"].text())
        self.assertFalse(view._revert_buttons["left_grip"].isHidden())
        self.assertTrue(view.sliders["left_grip"].is_edited())

    def test_revert_restores_the_loaded_value_and_hides_the_mark(self):
        view, state = self._view_with_state(left_grip=25)
        view.sliders["left_grip"].set_value("75")

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        view._revert_level("left_grip")

        self.assertEqual(view.sliders["left_grip"].value(), "25")
        self.assertEqual(state["vibration"]["left_grip"], 25)
        self.assertTrue(view._was_labels["left_grip"].isHidden())
        self.assertTrue(view._revert_buttons["left_grip"].isHidden())
        self.assertFalse(view.sliders["left_grip"].is_edited())
        self.assertEqual(reverted, [("vibration", "left_grip")])

    def test_revert_does_not_itself_re_fire_fieldTouched(self):
        view, state = self._view_with_state(left_grip=25)
        view.sliders["left_grip"].set_value("75")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))
        view._revert_level("left_grip")
        self.assertEqual(touches, [])

    def test_a_fresh_load_state_clears_every_mark(self):
        view, state = self._view_with_state(left_grip=25)
        view.sliders["left_grip"].set_value("75")
        self.assertFalse(view._was_labels["left_grip"].isHidden())

        state2 = state_mod.default_state_dict("test2")
        view.load_state(state2)

        self.assertTrue(view._was_labels["left_grip"].isHidden())
        self.assertFalse(view.sliders["left_grip"].is_edited())

    def test_manually_dialing_back_to_the_loaded_value_acts_as_an_implicit_revert(self):
        """REAL BUG, found 2026-10-26 (hardware test): bind
        left_grip away from its loaded value, then manually move the
        control back to that SAME value (not via the Revert button) --
        the mark/revert row and the draft ledger both kept claiming an
        outstanding edit even though Write correctly found nothing left
        to do."""
        view, state = self._view_with_state(left_grip=25)
        view.sliders["left_grip"].set_value("75")
        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))

        view.sliders["left_grip"].set_value("25")  # back to the loaded value, not Revert

        # SegmentedControl's own selectionChanged fires once per button
        # whose checked state flips within the exclusive group (the old
        # button unchecking AND the new one checking both toggle it) --
        # same tolerance test_moving_a_level_emits_fieldTouched... already
        # documents for the touch side; the revert side inherits it too.
        self.assertGreaterEqual(len(reverted), 1)
        self.assertEqual(set(reverted), {("vibration", "left_grip")})
        self.assertTrue(view._was_labels["left_grip"].isHidden())
        self.assertTrue(view._revert_buttons["left_grip"].isHidden())
        self.assertFalse(view.sliders["left_grip"].is_edited())

    def test_revert_all_discards_every_touched_field(self):
        """Scope-level "Discard changes" (IMPLEMENTATION-PLAN.md's "Not
        started" list, item 2) -- every touched field reverts, untouched
        fields are left alone."""
        view, state = self._view_with_state(left_grip=25, right_grip=0)
        view.sliders["left_grip"].set_value("75")
        view.sliders["right_grip"].set_value("50")
        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))

        view.revert_all()

        self.assertEqual(set(reverted), {("vibration", "left_grip"), ("vibration", "right_grip")})
        self.assertEqual(view.sliders["left_grip"].value(), "25")
        self.assertEqual(view.sliders["right_grip"].value(), "0")
        self.assertEqual(view._sliders_touched, set())
        self.assertTrue(view._revert_buttons["left_grip"].isHidden())
        self.assertTrue(view._revert_buttons["right_grip"].isHidden())

    def test_revert_path_reverts_one_field_and_leaves_the_other_untouched(self):
        """ReviewSheet's own per-row Revert (IMPLEMENTATION-PLAN.md's
        "Not started" list, item 3)."""
        view, state = self._view_with_state(left_grip=25, right_grip=0)
        view.sliders["left_grip"].set_value("75")
        view.sliders["right_grip"].set_value("50")

        self.assertTrue(view.revert_path(("vibration", "left_grip")))

        self.assertEqual(view.sliders["left_grip"].value(), "25")
        self.assertTrue(view.sliders["right_grip"].is_edited())  # untouched by the revert
        self.assertFalse(view.revert_path(("vibration", "left_grip")))  # already reverted
        self.assertFalse(view.revert_path(("vibration", "unknown_key")))
        self.assertFalse(view.revert_path(("dock_led_brightness",)))  # not this view's path

    def test_unknown_observed_value_shows_as_unknown_not_a_fabricated_number(self):
        from g7ctlc.views.vibration_view import VibrationView

        state = state_mod.default_state_dict("test")
        state["vibration"]["left_grip"] = None  # genuinely unread/unknown
        view = VibrationView()
        view.load_state(state)
        view.sliders["left_grip"].set_value("75")
        self.assertIn("Unknown", view._was_labels["left_grip"].text())


if __name__ == "__main__":
    unittest.main()
