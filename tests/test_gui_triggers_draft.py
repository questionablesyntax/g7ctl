"""TriggersView's S6 per-field draft slice (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the third slice, and the first
PER-SIDE one: `fieldTouched`/`fieldReverted` fire with a
`("triggers", side, ...)` path, forwarded from each `_TriggerSideWidget`
up through `TriggersView` itself. `curve_points` is deliberately out of
scope here -- see triggers_view.py's own module docstring for why.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod
from pyg7.field_spec import TRIGGER_FIELDS


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class TriggersFieldTouchedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, side="left", **side_overrides):
        from g7ctlc.views.triggers_view import TriggersView

        state = state_mod.default_state_dict("test")
        state["controller_slot"] = 2
        state["triggers"][side].update(side_overrides)
        view = TriggersView()
        view.load_state(state)
        return view, state

    def test_moving_hair_trigger_mode_emits_fieldTouched_with_the_right_path_field_and_profile(self):
        view, state = self._view_with_state("left", hair_trigger_mode="off")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["left"].hair_trigger_mode.set_value("fixed")

        self.assertGreaterEqual(len(touches), 1)
        for path, field, desired, profile in touches:
            self.assertEqual(path, ("triggers", "left", "hair_trigger_mode"))
            self.assertIs(field, TRIGGER_FIELDS["left"]["hair_trigger_mode"])
            self.assertEqual(desired, "fixed")
            self.assertEqual(profile, 2)

    def test_moving_right_side_curve_preset_emits_the_right_side_and_path(self):
        view, state = self._view_with_state("right")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["right"].curve.set_value("concave")

        self.assertGreaterEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("triggers", "right", "curve", "preset"))
        self.assertIs(field, TRIGGER_FIELDS["right"]["curve"])
        self.assertEqual(desired, "concave")

    def test_moving_deadzone_initial_emits_the_nested_path(self):
        view, state = self._view_with_state("left")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.sides["left"].dz_initial.setValue(10)

        self.assertEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("triggers", "left", "deadzone", "initial"))
        self.assertIs(field, TRIGGER_FIELDS["left"]["deadzone_initial"])
        self.assertEqual(desired, 10)

    def test_mark_and_revert_appear_only_after_a_real_touch(self):
        view, state = self._view_with_state("left", hair_trigger_mode="off")
        side = view.sides["left"]
        self.assertTrue(side._was_labels["hair_trigger_mode"].isHidden())
        self.assertTrue(side._revert_buttons["hair_trigger_mode"].isHidden())

        side.hair_trigger_mode.set_value("adaptive")

        self.assertFalse(side._was_labels["hair_trigger_mode"].isHidden())
        self.assertIn("Off", side._was_labels["hair_trigger_mode"].text())
        self.assertFalse(side._revert_buttons["hair_trigger_mode"].isHidden())
        self.assertTrue(side.hair_trigger_mode.is_edited())

    def test_revert_restores_the_loaded_value_and_hides_the_mark(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        side.dz_initial.setValue(40)

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        side._revert_setting("deadzone_initial")

        self.assertEqual(side.dz_initial.value(), 0)
        self.assertEqual(state["triggers"]["left"]["deadzone"]["initial"], 0)
        self.assertTrue(side._was_labels["deadzone_initial"].isHidden())
        self.assertFalse(side.dz_initial.is_edited())
        self.assertEqual(reverted, [("triggers", "left", "deadzone", "initial")])

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
        side.adz_initial.setValue(20)
        self.assertFalse(side._was_labels["anti_deadzone_initial"].isHidden())

        state2 = state_mod.default_state_dict("test2")
        view.load_state(state2)

        self.assertTrue(side._was_labels["anti_deadzone_initial"].isHidden())
        self.assertFalse(side.adz_initial.is_edited())

    def test_graphical_curve_editor_endpoint_drag_marks_all_four_deadzone_fields(self):
        """_on_editor_endpoints() bypasses valueChanged via blockSignals --
        this is the one path that must mark touched explicitly rather than
        relying on the NumberFields' own signal."""
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a[0]))

        side._on_editor_endpoints(5, 95, 10, 90)

        for suffix in (("deadzone", "initial"), ("deadzone", "max"),
                       ("anti_deadzone", "initial"), ("anti_deadzone", "max")):
            self.assertIn(("triggers", "left") + suffix, touches)

    def test_moving_one_setting_does_not_also_mark_an_unrelated_one(self):
        view, state = self._view_with_state("left")
        side = view.sides["left"]
        side.hair_trigger_mode.set_value("fixed")
        self.assertFalse(side.curve.is_edited())
        self.assertTrue(side._was_labels["curve"].isHidden())

    def test_touching_left_side_does_not_touch_right_side(self):
        view, state = self._view_with_state("left")
        view.sides["left"].hair_trigger_mode.set_value("fixed")
        self.assertFalse(view.sides["right"].hair_trigger_mode.is_edited())


if __name__ == "__main__":
    unittest.main()
