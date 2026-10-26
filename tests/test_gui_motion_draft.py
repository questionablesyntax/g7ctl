"""MotionView's S6 per-field draft slice (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the sixth slice, one of the two
categories Track S's own ordering flagged as most irregular. Covers all
the migrated "simple" settings per side, plus Aim-only `invert_roll` and
the two-combo (`output` x `x_axis_output_mode`) visibility gating.
`activate_button` and the direction bindings are deliberately out of
scope -- see motion_view.py's own module docstring for why.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod
from pyg7.field_spec import MOTION_FIELDS


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class MotionFieldTouchedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, side="aim", **side_overrides):
        from g7ctlc.views.motion_view import MotionView

        state = state_mod.default_state_dict("test")
        state["controller_slot"] = 2
        state.setdefault("motion", {"aim": {}, "tilt": {}})
        state["motion"][side].update(side_overrides)
        view = MotionView()
        view.load_state(state)
        return view, state

    def test_moving_sensitivity_scale_emits_fieldTouched_with_the_right_path_field_and_profile(self):
        view, state = self._view_with_state("aim")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["aim"].sensitivity_scale.setValue(10)

        self.assertEqual(len(touches), 1)
        path, field, desired, profile = touches[0]
        self.assertEqual(path, ("motion", "aim", "sensitivity_scale"))
        self.assertIs(field, MOTION_FIELDS["aim"]["sensitivity_scale"])
        self.assertEqual(desired, 10)
        self.assertEqual(profile, 2)

    def test_changing_activate_method_emits_the_right_path(self):
        view, state = self._view_with_state("aim")
        side = view.sides["aim"]
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        side.activate_method.setCurrentIndex(side.activate_method.findData("always_on"))

        self.assertEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("motion", "aim", "activate_method"))
        self.assertIs(field, MOTION_FIELDS["aim"]["activate_method"])
        self.assertEqual(desired, "always_on")

    def test_toggling_invert_roll_only_exists_on_aim(self):
        view, state = self._view_with_state("tilt")
        self.assertIsNone(view.sides["tilt"].invert_roll)
        self.assertNotIn("invert_roll", view.sides["tilt"]._controls)

        aim_view, _ = self._view_with_state("aim")
        self.assertIsNotNone(aim_view.sides["aim"].invert_roll)

    def test_output_mode_gates_overlap_area_and_direction_box(self):
        view, state = self._view_with_state("aim")
        side = view.sides["aim"]
        self.assertTrue(side._row_widgets["overlap_area"].isHidden())
        self.assertTrue(side.direction_box.isHidden())

        side.output.setCurrentIndex(side.output.findData("directional"))
        self.assertFalse(side._row_widgets["overlap_area"].isHidden())
        self.assertFalse(side.direction_box.isHidden())

    def test_x_axis_and_output_mode_together_gate_invert_yaw_and_invert_roll(self):
        view, state = self._view_with_state("aim")
        side = view.sides["aim"]
        # Default: x_axis_output_mode="yaw", output="left_stick" -- neither shows.
        self.assertTrue(side._row_widgets["invert_yaw"].isHidden())
        self.assertTrue(side._row_widgets["invert_roll"].isHidden())

        side.x_axis_output_mode.setCurrentIndex(side.x_axis_output_mode.findData("yaw_roll"))
        self.assertFalse(side._row_widgets["invert_yaw"].isHidden())   # yaw_roll, not directional
        self.assertTrue(side._row_widgets["invert_roll"].isHidden())  # needs directional too

        side.output.setCurrentIndex(side.output.findData("directional"))
        self.assertTrue(side._row_widgets["invert_yaw"].isHidden())   # now directional, so yaw hides
        self.assertFalse(side._row_widgets["invert_roll"].isHidden())  # roll needs both, now shows

    def test_mark_and_revert_appear_only_after_a_real_touch(self):
        view, state = self._view_with_state("aim", activate_method="off")
        side = view.sides["aim"]
        self.assertTrue(side._was_labels["activate_method"].isHidden())
        self.assertTrue(side._revert_buttons["activate_method"].isHidden())

        side.activate_method.setCurrentIndex(side.activate_method.findData("hold_to_activate"))

        self.assertFalse(side._was_labels["activate_method"].isHidden())
        self.assertIn("Off", side._was_labels["activate_method"].text())
        self.assertFalse(side._revert_buttons["activate_method"].isHidden())

    def test_revert_restores_the_loaded_value_and_hides_the_mark(self):
        view, state = self._view_with_state("aim")
        side = view.sides["aim"]
        side.sensitivity_scale.setValue(10)

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        side._revert_setting("sensitivity_scale")

        self.assertEqual(side.sensitivity_scale.value(), 50)
        self.assertEqual(state["motion"]["aim"]["sensitivity_scale"], 50)
        self.assertTrue(side._was_labels["sensitivity_scale"].isHidden())
        self.assertEqual(reverted, [("motion", "aim", "sensitivity_scale")])

    def test_revert_does_not_itself_re_fire_fieldTouched(self):
        view, state = self._view_with_state("aim")
        side = view.sides["aim"]
        side.dz_max.setValue(60)
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))
        side._revert_setting("deadzone_max")
        self.assertEqual(touches, [])

    def test_a_fresh_load_state_clears_every_mark(self):
        view, state = self._view_with_state("aim")
        side = view.sides["aim"]
        side.sensitivity_scale.setValue(20)
        self.assertFalse(side._was_labels["sensitivity_scale"].isHidden())

        state2 = state_mod.default_state_dict("test2")
        view.load_state(state2)

        self.assertTrue(side._was_labels["sensitivity_scale"].isHidden())

    def test_touching_aim_does_not_touch_tilt(self):
        view, state = self._view_with_state("aim")
        view.sides["aim"].sensitivity_scale.setValue(20)
        self.assertFalse(view.sides["tilt"]._touched)


if __name__ == "__main__":
    unittest.main()
