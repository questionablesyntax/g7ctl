"""Round-trip tests for the category views that aren't Buttons.

Buttons' (and Sticks' Direction Bindings') keycode-picker persistence bug
class lives in test_gui_bindings.py -- this file covers the more mundane
spinbox/combo/checkbox wiring the rest of Sticks plus all of Triggers,
Vibration, and Settings are made of, none of which had any test coverage at
all before this: load a fully-populated, non-default state dict into each
view, save it back out, and confirm every field survived unchanged.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent so
the protocol-library tests stay runnable without Qt installed.
"""
import copy
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class SticksViewRoundTripTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _distinctive_side():
        # Every value deliberately different from default_state_dict()'s
        # defaults, so a field that's silently dropped or left at its
        # default would be caught rather than accidentally matching.
        return {
            "trajectory": "raw",
            "curve": {"preset": "concave", "points": None},
            "deadzone": {"initial": 12, "max": 88},
            "anti_deadzone": {"initial": 7, "max": 91},
            "resolution_bits": 10,
            "advanced_mapping": {
                "output_mode": "mouse",
                "invert_x": True,
                "invert_y": True,
                "sensitivity": 33,
                "overlap_area": 44,
                "dpi": 66,
                "direction_bindings": None,
            },
        }

    def test_scalar_fields_round_trip_both_sides(self):
        # output_mode is "mouse" here, not "directional" -- save_into()
        # deliberately never writes direction_bindings in that case (see
        # test_non_directional_mode_leaves_direction_bindings_untouched
        # below), so it's excluded from this comparison on purpose.
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("test")
        state["sticks"]["left"] = self._distinctive_side()
        state["sticks"]["right"] = self._distinctive_side()
        view = SticksView()
        view.load_state(state)

        out = {"left": {}, "right": {}}
        for side, widget in view.sides.items():
            widget.save_into(out[side])
        for side in ("left", "right"):
            expected = copy.deepcopy(state["sticks"][side])
            del expected["advanced_mapping"]["direction_bindings"]
            self.assertEqual(out[side], expected)

    def test_directional_mode_writes_direction_bindings(self):
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("test")
        side = self._distinctive_side()
        side["advanced_mapping"]["output_mode"] = "directional"
        side["advanced_mapping"]["direction_bindings"] = {
            "up": "w", "down": "s", "left": "a", "right": "d", "ring": "shift",
        }
        state["sticks"]["left"] = side
        view = SticksView()
        view.load_state(state)

        out = {}
        view.sides["left"].save_into(out)
        self.assertEqual(out["advanced_mapping"]["direction_bindings"],
                         side["advanced_mapping"]["direction_bindings"])

    def test_non_directional_mode_leaves_direction_bindings_untouched(self):
        # save_into() only writes direction_bindings when output_mode is
        # "directional" -- confirms the other branch doesn't clobber it with
        # combo data from hidden, stale widgets.
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("test")
        view = SticksView()
        view.load_state(state)

        out = {"advanced_mapping": {"direction_bindings": "should not be touched"}}
        view.sides["left"].save_into(out)
        self.assertEqual(out["advanced_mapping"]["direction_bindings"], "should not be touched")

    def test_output_mode_switches_which_fields_are_visible(self):
        from g7ctlc.views.sticks_view import SticksView
        view = SticksView()
        left = view.sides["left"]

        left.output_mode.setCurrentIndex(left.output_mode.findData("directional"))
        self.assertTrue(left.sensitivity.isHidden())     # only for left_stick/right_stick/mouse
        self.assertFalse(left.overlap_area.isHidden())   # directional-only field, now visible
        self.assertFalse(left.direction_box.isHidden())
        self.assertTrue(left.dpi.isHidden())

        left.output_mode.setCurrentIndex(left.output_mode.findData("mouse"))
        self.assertFalse(left.dpi.isHidden())
        self.assertTrue(left.overlap_area.isHidden())
        self.assertTrue(left.direction_box.isHidden())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class TriggersViewRoundTripTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _distinctive_side():
        return {
            "hair_trigger_mode": "adaptive",
            "curve": {"preset": "s_curve", "points": None},
            "deadzone": {"initial": 15, "max": 80},
            "anti_deadzone": {"initial": 9, "max": 95},
        }

    def test_scalar_fields_round_trip_both_sides(self):
        from g7ctlc.views.triggers_view import TriggersView
        state = state_mod.default_state_dict("test")
        state["triggers"]["left"] = self._distinctive_side()
        state["triggers"]["right"] = self._distinctive_side()
        view = TriggersView()
        view.load_state(state)

        out = {"left": {}, "right": {}}
        for side, widget in view.sides.items():
            widget.save_into(out[side])
        self.assertEqual(out["left"], state["triggers"]["left"])
        self.assertEqual(out["right"], state["triggers"]["right"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class VibrationViewRoundTripTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_levels_and_flags_round_trip(self):
        from g7ctlc.views.vibration_view import VibrationView
        state = state_mod.default_state_dict("test")
        state["vibration"] = {
            "left_grip": 17, "right_grip": 83,
            "left_trigger": 42, "right_trigger": 61,
            "left_trigger_force": True, "left_trigger_sync": False,
            "right_trigger_force": False, "right_trigger_sync": True,
        }
        view = VibrationView()
        view.load_state(state)

        before = copy.deepcopy(state)
        view._on_edit()  # re-save with no genuine edit -- must reproduce the same values
        self.assertEqual(state["vibration"], before["vibration"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class SettingsViewRoundTripTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dock_settings_round_trip(self):
        from g7ctlc.views.settings_view import SettingsView
        state = state_mod.default_state_dict("test")
        state["dock_led_brightness"] = 25
        state["dock_auto_on_off"] = False
        view = SettingsView()
        view.load_state(state)

        before = copy.deepcopy(state)
        view._on_edit()
        self.assertEqual(state["dock_led_brightness"], before["dock_led_brightness"])
        self.assertEqual(state["dock_auto_on_off"], before["dock_auto_on_off"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class CurvePointsEditorTest(unittest.TestCase):
    """The three interior control points of a Custom curve.

    Numeric rather than graphical on purpose: the interpolation between the
    handles is not established, so a drawn curve would misrepresent what the
    controller does. See g7ctlc/widgets.py:CurvePointsEditor.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self):
        from g7ctlc.widgets import CurvePointsEditor
        return CurvePointsEditor()

    def test_points_round_trip(self):
        ed = self._editor()
        ed.load([[10, 20], [100, 110], [200, 210]])
        self.assertEqual(ed.points(), [[10, 20], [100, 110], [200, 210]])

    def test_load_none_gives_zeros(self):
        ed = self._editor()
        ed.load(None)
        self.assertEqual(ed.points(), [[0, 0], [0, 0], [0, 0]])

    def test_reloading_a_higher_curve_is_not_rejected_by_stale_clamps(self):
        """Bounds are narrowed to enforce ordering, so a load has to widen
        them first -- otherwise the previous curve's clamps silently reject
        the new values and the view shows something the device never had."""
        ed = self._editor()
        ed.load([[1, 1], [2, 2], [3, 3]])
        ed.load([[200, 200], [220, 220], [240, 240]])
        self.assertEqual(ed.points(), [[200, 200], [220, 220], [240, 240]])

    def test_ordering_is_enforced_against_the_upper_neighbour(self):
        """Matches Nexus, which clamps a dragged point to its neighbours.
        The firmware does NOT require this -- P1=(0,0) with P3=(255,255) was
        accepted on hardware -- so it is a UI choice, not a protocol rule."""
        ed = self._editor()
        ed.load([[10, 10], [100, 100], [200, 200]])
        ed.rows[0][0].setValue(255)          # shove point 1's x past point 2's
        self.assertLessEqual(ed.points()[0][0], ed.points()[1][0])

    def test_ordering_is_enforced_against_the_lower_neighbour(self):
        ed = self._editor()
        ed.load([[10, 10], [100, 100], [200, 200]])
        ed.rows[2][1].setValue(0)            # shove point 3's y below point 2's
        self.assertGreaterEqual(ed.points()[2][1], ed.points()[1][1])

    def test_points_are_disabled_unless_the_preset_is_custom(self):
        ed = self._editor()
        ed.set_points_enabled(False)
        self.assertFalse(ed.rows[0][0].isEnabled())
        ed.set_points_enabled(True)
        self.assertTrue(ed.rows[0][0].isEnabled())

    def test_an_unwritable_last_point_stays_disabled_even_when_enabled(self):
        """Right Trigger's third point crosses a page boundary and pyg7
        refuses it, so the field must never become editable -- otherwise the
        refusal surfaces as a sync that dies halfway through."""
        ed = self._editor()
        ed.set_last_point_writable(False, "unverified encoding")
        ed.set_points_enabled(True)
        self.assertTrue(ed.rows[0][0].isEnabled(), "first point should still work")
        self.assertFalse(ed.rows[2][0].isEnabled())
        self.assertFalse(ed.rows[2][1].isEnabled())
        self.assertIn("unverified", ed.rows[2][0].toolTip())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class CurvePointsInViewsTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_custom_curve_round_trips_through_the_sticks_view(self):
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("t")
        state["sticks"]["left"]["curve"] = {"preset": "custom",
                                            "points": [[20, 30], [100, 110], [200, 210]]}
        view = SticksView()
        view.load_state(state)
        out = {}
        view.sides["left"].save_into(out)
        self.assertEqual(out["curve"]["preset"], "custom")
        self.assertEqual(out["curve"]["points"], [[20, 30], [100, 110], [200, 210]])

    def test_a_non_custom_preset_reports_no_points(self):
        """Nexus exposes point editing only under Custom, and whether the
        firmware honours a point write under a named preset is untested --
        so a named preset declares no points rather than writing some."""
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("t")
        state["sticks"]["left"]["curve"] = {"preset": "concave",
                                            "points": [[20, 30], [100, 110], [200, 210]]}
        view = SticksView()
        view.load_state(state)
        out = {}
        view.sides["left"].save_into(out)
        self.assertIsNone(out["curve"]["points"])

    def test_the_right_trigger_third_point_is_disabled(self):
        from g7ctlc.views.triggers_view import TriggersView
        view = TriggersView()
        right = view.sides["right"].curve_points
        left = view.sides["left"].curve_points
        right.set_points_enabled(True)
        left.set_points_enabled(True)
        self.assertFalse(right.rows[2][0].isEnabled())
        self.assertTrue(left.rows[2][0].isEnabled(),
                        "only the RIGHT trigger's third point is unwritable")
