"""SticksView's S6 per-field draft slice (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the fourth slice, same per-side
shape as triggers_view.py's but with all 13 of
`pyg7.field_spec.STICK_FIELDS`' "simple" settings, including the
visibility-gated Advanced Mapping rows and `output_mode`'s own
`_output_mode_configured` interaction. `curve_points` and
`direction_bindings` are deliberately out of scope -- see
sticks_view.py's own module docstring for why.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod
from pyg7.field_spec import STICK_FIELDS


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class SticksFieldTouchedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, side="left", **side_overrides):
        from g7ctlc.views.sticks_view import SticksView

        state = state_mod.default_state_dict("test")
        state["controller_slot"] = 2
        state["sticks"][side].update(side_overrides)
        view = SticksView()
        view.load_state(state)
        return view, state

    def test_moving_trajectory_emits_fieldTouched_with_the_right_path_field_and_profile(self):
        view, state = self._view_with_state("left", trajectory="circle")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["left"].trajectory.set_value("raw")

        self.assertGreaterEqual(len(touches), 1)
        for path, field, desired, profile in touches:
            self.assertEqual(path, ("sticks", "left", "trajectory"))
            self.assertIs(field, STICK_FIELDS["left"]["trajectory"])
            self.assertEqual(desired, "raw")
            self.assertEqual(profile, 2)

    def test_moving_deadzone_initial_emits_the_nested_path(self):
        view, state = self._view_with_state("left")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["left"].dz_initial.setValue(10)

        self.assertEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("sticks", "left", "deadzone", "initial"))
        self.assertIs(field, STICK_FIELDS["left"]["deadzone_initial"])
        self.assertEqual(desired, 10)

    def test_toggling_invert_x_emits_fieldTouched_with_a_bool(self):
        view, state = self._view_with_state("left")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["left"].invert_x.setChecked(True)

        self.assertEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("sticks", "left", "advanced_mapping", "invert_x"))
        self.assertIs(field, STICK_FIELDS["left"]["invert_x"])
        self.assertTrue(desired)

    def test_changing_output_mode_emits_fieldTouched_and_marks_configured(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        idx = side.output_mode.findData("mouse")
        side.output_mode.setCurrentIndex(idx)

        self.assertEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("sticks", "left", "advanced_mapping", "output_mode"))
        self.assertIs(field, STICK_FIELDS["left"]["output_mode"])
        self.assertEqual(desired, "mouse")
        self.assertTrue(side._output_mode_configured)

    def test_output_mode_gates_sensitivity_overlap_dpi_row_visibility(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        # Default output_mode is "left_stick" -- sensitivity visible, the
        # other two are not.
        self.assertFalse(side._row_widgets["sensitivity"].isHidden())
        self.assertTrue(side._row_widgets["overlap_area"].isHidden())
        self.assertTrue(side._row_widgets["dpi"].isHidden())

        side.output_mode.setCurrentIndex(side.output_mode.findData("directional"))
        self.assertTrue(side._row_widgets["sensitivity"].isHidden())
        self.assertFalse(side._row_widgets["overlap_area"].isHidden())
        self.assertTrue(side._row_widgets["dpi"].isHidden())

    def test_mark_and_revert_appear_only_after_a_real_touch(self):
        view, state = self._view_with_state("left", trajectory="circle")
        side = view.sides["left"]
        self.assertTrue(side._was_labels["trajectory"].isHidden())
        self.assertTrue(side._revert_buttons["trajectory"].isHidden())

        side.trajectory.set_value("raw")

        self.assertFalse(side._was_labels["trajectory"].isHidden())
        self.assertIn("Circle", side._was_labels["trajectory"].text())
        self.assertFalse(side._revert_buttons["trajectory"].isHidden())
        self.assertTrue(side.trajectory.is_edited())

    def test_revert_restores_the_loaded_value_and_hides_the_mark(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        side.dz_initial.setValue(40)

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        side._revert_setting("deadzone_initial")

        self.assertEqual(side.dz_initial.value(), 0)
        self.assertEqual(state["sticks"]["left"]["deadzone"]["initial"], 0)
        self.assertTrue(side._was_labels["deadzone_initial"].isHidden())
        self.assertFalse(side.dz_initial.is_edited())
        self.assertEqual(reverted, [("sticks", "left", "deadzone", "initial")])

    def test_revert_output_mode_restores_unconfigured_state(self):
        """output_mode started genuinely unconfigured (None in state) --
        reverting after touching it must restore BOTH the display default
        AND `_output_mode_configured = False`, not just the display."""
        view, state = self._view_with_state("left")  # advanced_mapping.output_mode is None
        side = view.sides["left"]
        self.assertFalse(side._output_mode_configured)

        side.output_mode.setCurrentIndex(side.output_mode.findData("mouse"))
        self.assertTrue(side._output_mode_configured)

        side._revert_setting("output_mode")

        self.assertFalse(side._output_mode_configured)
        self.assertEqual(side.output_mode.currentData(), "left_stick")  # side-aware default
        self.assertIsNone(state["sticks"]["left"]["advanced_mapping"]["output_mode"])

    def test_revert_does_not_itself_re_fire_fieldTouched(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        side.dz_max.setValue(60)
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))
        side._revert_setting("deadzone_max")
        self.assertEqual(touches, [])

    def test_a_fresh_load_state_clears_every_mark(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        side.sensitivity.setValue(20)
        self.assertFalse(side._was_labels["sensitivity"].isHidden())

        state2 = state_mod.default_state_dict("test2")
        view.load_state(state2)

        self.assertTrue(side._was_labels["sensitivity"].isHidden())
        self.assertFalse(side.sensitivity.is_edited())

    def test_graphical_curve_editor_endpoint_drag_marks_all_four_deadzone_fields(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a[0]))

        side._on_editor_endpoints(5, 95, 10, 90)

        for suffix in (("deadzone", "initial"), ("deadzone", "max"),
                       ("anti_deadzone", "initial"), ("anti_deadzone", "max")):
            self.assertIn(("sticks", "left") + suffix, touches)

    def test_touching_left_side_does_not_touch_right_side(self):
        view, state = self._view_with_state("left")
        view.sides["left"].trajectory.set_value("raw")
        self.assertFalse(view.sides["right"].trajectory.is_edited())


if __name__ == "__main__":
    unittest.main()
