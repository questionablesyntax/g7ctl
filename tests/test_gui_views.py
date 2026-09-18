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

    def test_editing_left_stick_does_not_remap_right_stick_output(self):
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep): _StickSideWidget
        # had no idea which side it represented, so its output_mode display
        # fallback for an unconfigured (None) value was hardcoded to
        # "left_stick" for BOTH instances. SticksView._on_edit() sweeps
        # BOTH side widgets' save_into() on any single edit -- so touching
        # only the left stick still read back the right widget's currently-
        # displayed (wrongly-defaulted) output_mode and wrote a real
        # "Right Stick: output_mode=left_stick" step. This mirrors a real
        # device read (both sticks genuinely unconfigured, output_mode=None
        # -- confirmed against tests/fixtures/live_read.json's
        # profile3_factory) round-tripped through the GUI.
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("test")
        state["sticks"]["left"]["advanced_mapping"]["output_mode"] = None
        state["sticks"]["right"]["advanced_mapping"]["output_mode"] = None
        view = SticksView()
        view.load_state(state)

        # Edit ONLY the left stick's sensitivity -- a field with nothing to
        # do with output_mode at all.
        view.sides["left"].sensitivity.setValue(77)

        self.assertIsNone(
            state["sticks"]["right"]["advanced_mapping"]["output_mode"],
            "editing the left stick must not remap the right stick's output_mode")
        self.assertIsNone(
            state["sticks"]["left"]["advanced_mapping"]["output_mode"],
            "an untouched field on the same widget must not gain a value either")

    def test_switching_between_named_presets_refreshes_the_displayed_points(self):
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep):
        # _update_curve_points_enabled() used to only update _last_preset
        # bookkeeping when switching between two NAMED presets -- the
        # combo correctly showed "Concave" but curve_points/curve_editor
        # kept displaying Standard's shape, and a user who then started
        # customizing was actually editing those stale, wrong points.
        from g7ctlc.views.sticks_view import SticksView
        from pyg7.curves import preset_points
        state = state_mod.default_state_dict("test")
        view = SticksView()
        view.load_state(state)
        left = view.sides["left"]

        left.curve.setCurrentIndex(left.curve.findText("standard"))
        self.assertEqual(left.curve_points.points(), preset_points("standard"))

        left.curve.setCurrentIndex(left.curve.findText("concave"))
        self.assertEqual(left.curve_points.points(), preset_points("concave"),
                          "switching to a new named preset must refresh the displayed points")

        # Entering Custom next must preserve what's now actually on screen
        # (Concave's shape), not silently fall back to a stale seed.
        left.curve.setCurrentIndex(left.curve.findText("custom"))
        self.assertEqual(left.curve_points.points(), preset_points("concave"))

    def test_a_brand_new_state_defaults_both_sticks_output_mode_to_unconfigured(self):
        # REAL BUG, found 2026-09-17 (flagged while fixing the B2
        # bug-sweep finding, same night, not part of either model's
        # report): _default_stick_settings() used to hardcode
        # "output_mode": "left_stick" for BOTH sides identically, so a
        # brand-new "New State" (never read from a device) showed the
        # RIGHT stick's Advanced Mapping Output Mode as "Left Stick" from
        # the moment it was loaded -- before any edit, and never matching
        # what a real device's factory-default actually decodes to (None
        # for both sticks, confirmed via tests/fixtures/live_read.json's
        # profile3_factory).
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("brand new")
        self.assertIsNone(state["sticks"]["left"]["advanced_mapping"]["output_mode"])
        self.assertIsNone(state["sticks"]["right"]["advanced_mapping"]["output_mode"])

        view = SticksView()
        view.load_state(state)
        # Side-aware display fallback (B2's own fix) shows the correct
        # per-side default -- confirms this doesn't just leave the field
        # None in state, it displays sensibly too, without writing
        # anything until a real edit happens.
        self.assertEqual(view.sides["left"].output_mode.currentData(), "left_stick")
        self.assertEqual(view.sides["right"].output_mode.currentData(), "right_stick")
        out = {"advanced_mapping": {}}
        view.sides["right"].save_into(out)
        self.assertIsNone(out["advanced_mapping"]["output_mode"],
                          "an unconfigured stick must not save a spurious display value")


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
        # Values are 2026-08-17's felt-tested five (see pyg7.vibration.
        # LEVELS), not arbitrary -- the widget only has five stops now, so a
        # round-trip test needs values it can actually land on.
        from g7ctlc.views.vibration_view import VibrationView
        state = state_mod.default_state_dict("test")
        state["vibration"] = {
            "left_grip": 25, "right_grip": 75,
            "left_trigger": 0, "right_trigger": 100,
            "left_trigger_force": True, "left_trigger_sync": False,
            "right_trigger_force": False, "right_trigger_sync": True,
        }
        view = VibrationView()
        view.load_state(state)

        before = copy.deepcopy(state)
        view._on_edit()  # re-save with no genuine edit -- must reproduce the same values
        self.assertEqual(state["vibration"], before["vibration"])

    def test_off_scale_value_displays_at_its_nearest_stop_without_rewriting_state(self):
        # A value outside the five stops (an older export, hand-edited
        # JSON, or CLI scripting from before this restriction) must not
        # crash the widget. It displays at its nearest neighbor -- but
        # load_state() must not silently coerce the state dict itself; the
        # original value stays until the control is actually touched, at
        # which point _on_edit() overwrites it like any real edit. Sync
        # rejects an untouched off-scale value with a clear error rather
        # than the GUI quietly rewriting a file it didn't create.
        from g7ctlc.views.vibration_view import VibrationView
        state = state_mod.default_state_dict("test")
        state["vibration"]["left_grip"] = 43  # nearest stop is 50

        view = VibrationView()
        view.load_state(state)
        self.assertEqual(view.sliders["left_grip"].value(), 2)  # index of 50 in LEVELS
        self.assertEqual(state["vibration"]["left_grip"], 43, "load_state() must not rewrite the value it was given")

        # Corrected 2026-09-17 (real bug, found by Astra's bug-sweep): this
        # used to call view._on_edit() directly and assert THAT alone
        # normalizes the value -- but _on_edit() firing at all used to be
        # treated as equivalent to "the slider was touched," which is
        # exactly the bug (toggling an unrelated Force/Sync flag also
        # fires _on_edit(), and used to round every slider along with it).
        # Actually moving the slider is what should trigger normalization
        # now -- setValue() to the SAME index is a Qt no-op (no signal
        # fires), so this moves away and back to land a real
        # valueChanged. See test_untouched_off_scale_value_survives_an_
        # unrelated_edit below for the case this really guards against.
        view.sliders["left_grip"].setValue(0)
        view.sliders["left_grip"].setValue(2)
        self.assertEqual(state["vibration"]["left_grip"], 50)

    def test_untouched_off_scale_value_survives_an_unrelated_edit(self):
        # The actual bug: toggling a Force/Sync checkbox (or moving a
        # DIFFERENT slider) used to re-derive EVERY vibration key from its
        # slider's current position, silently rounding an off-scale value
        # someone else set even though nothing about it was touched.
        from g7ctlc.views.vibration_view import VibrationView
        state = state_mod.default_state_dict("test")
        state["vibration"]["left_grip"] = 43  # nearest stop is 50, must stay 43
        view = VibrationView()
        view.load_state(state)

        view.checks["right_trigger_force"].setChecked(True)  # unrelated edit

        self.assertEqual(state["vibration"]["left_grip"], 43,
                          "an untouched slider's exact value must survive an unrelated edit")
        self.assertTrue(state["vibration"]["right_trigger_force"])  # the real edit still landed

    def test_first_edit_after_load_writes_immediately(self):
        # REAL BUG, found 2026-09-18 (Sol's bug-sweep) -- a regression this
        # same fix introduced (2026-09-17, see the class docstring above):
        # valueChanged connects _on_edit BEFORE _mark_slider_touched, and Qt
        # fires same-signal slots in connection order. So the FIRST edit
        # after a load ran _on_edit while the touched flag was still False
        # (set only afterward by the second-connected slot), silently
        # dropping that edit from state -- Sync would then send the OLD
        # value while the slider displayed the new one. The tests above
        # never caught this because they each move a control TWICE (away
        # and back, to get a real signal past a same-value Qt no-op) and
        # only check state after the second move, by which point the
        # touched flag is already set from the first.
        from g7ctlc.views.vibration_view import VibrationView
        state = state_mod.default_state_dict("test")
        state["vibration"]["left_grip"] = 0  # nearest stop is index 0
        view = VibrationView()
        view.load_state(state)

        view.sliders["left_grip"].setValue(2)  # ONE edit -- must land immediately
        self.assertEqual(state["vibration"]["left_grip"], 50,
                          "the first edit after a load must write into state immediately, not require a second edit")


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

    def test_off_scale_brightness_displays_at_its_nearest_stop_without_rewriting_state(self):
        # pyg7/dock_settings.py and `dock-set brightness` accept any 0-100
        # value, but this combo only offers five discrete stops (see
        # BRIGHTNESS_OPTIONS). A value outside those stops -- an older
        # export, hand-edited JSON, or CLI scripting -- must display at its
        # nearest neighbor without load_state() silently coercing the state
        # dict itself. Mirrors vibration_view.py's equivalent off-scale test.
        from g7ctlc.views.settings_view import SettingsView
        state = state_mod.default_state_dict("test")
        state["dock_led_brightness"] = 10  # nearest stop is 0 ("Off")

        view = SettingsView()
        view.load_state(state)
        self.assertEqual(view.brightness.currentIndex(), 0)  # index of 0% in BRIGHTNESS_OPTIONS
        self.assertEqual(state["dock_led_brightness"], 10, "load_state() must not rewrite the value it was given")

        # Corrected 2026-09-17 -- same correction and same reasoning as
        # vibration_view.py's equivalent test; see its own comment.
        # setCurrentIndex() to the SAME index is a Qt no-op (no signal
        # fires), so this moves away and back to land a real
        # currentIndexChanged.
        view.brightness.setCurrentIndex(1)
        view.brightness.setCurrentIndex(0)
        self.assertEqual(state["dock_led_brightness"], 0)

    def test_untouched_off_scale_brightness_survives_an_unrelated_edit(self):
        # REAL BUG, found 2026-09-17 (Astra's bug-sweep): toggling
        # auto_on_off used to re-derive dock_led_brightness from the
        # combo's current (coarse, nearest-stop) selection too, silently
        # rounding an off-scale exact value even though nothing about
        # brightness was touched.
        from g7ctlc.views.settings_view import SettingsView
        state = state_mod.default_state_dict("test")
        state["dock_led_brightness"] = 43  # nearest stop is 50, must stay 43
        view = SettingsView()
        view.load_state(state)

        view.auto_on_off.setChecked(not view.auto_on_off.isChecked())  # unrelated edit

        self.assertEqual(state["dock_led_brightness"], 43,
                          "an untouched brightness value must survive an unrelated edit")

    def test_first_edit_after_load_writes_immediately(self):
        # REAL BUG, found 2026-09-18 (Sol's bug-sweep) -- same regression and
        # same cause as VibrationViewRoundTripTest's identically-named test;
        # see its comment. currentIndexChanged connects _on_edit BEFORE
        # _mark_brightness_touched, so the first edit after a load is
        # silently dropped from state.
        from g7ctlc.views.settings_view import SettingsView
        state = state_mod.default_state_dict("test")
        state["dock_led_brightness"] = 0  # nearest stop is index 0
        view = SettingsView()
        view.load_state(state)

        view.brightness.setCurrentIndex(1)  # ONE edit -- must land immediately
        self.assertEqual(state["dock_led_brightness"], 25,
                          "the first edit after a load must write into state immediately, not require a second edit")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class MainWindowMinimumHeightTest(unittest.TestCase):
    """QTabWidget sizes the whole window's minimum height to fit the
    LARGEST tab page, not just whichever one is visible -- a user
    reported a real, un-resizable-enough window (Reddit, 2026-08-19)
    traced to TriggersView (two CurveEditor widgets, hardcoded 200px
    minimum height each, un-scrolled) alone setting a ~675px floor,
    with VibrationView a secondary contributor (~396px). Measured before
    this fix: the combined QTabWidget's minimumSizeHint was 395x704.
    Regression coverage, not a pixel-exact assertion (fragile across Qt/
    font versions) -- just that nothing drags the floor back up there.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_no_single_tab_forces_a_tall_window(self):
        from PyQt6.QtWidgets import QScrollArea

        from g7ctlc.views.buttons_view import ButtonsView
        from g7ctlc.views.motion_view import MotionView
        from g7ctlc.views.settings_view import SettingsView
        from g7ctlc.views.sticks_view import SticksView
        from g7ctlc.views.triggers_view import TriggersView
        from g7ctlc.views.vibration_view import VibrationView

        views = [ButtonsView(), SticksView(), TriggersView(), MotionView(),
                 VibrationView(), SettingsView()]
        for view in views:
            self.assertTrue(
                view.findChild(QScrollArea) is not None,
                f"{type(view).__name__} has no QScrollArea anywhere in its "
                "tree -- its content can drag the whole window's minimum "
                "height up regardless of which tab is actually visible.")
            self.assertLess(
                view.minimumSizeHint().height(), 300,
                f"{type(view).__name__}'s own minimumSizeHint is unexpectedly "
                "tall -- was it un-wrapped from its QScrollArea?")


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

    def test_every_trigger_curve_point_is_editable(self):
        """The Right Trigger's third point was disabled while its
        page-crossing address was unverified. test62 captured the real
        encoding, so it is writable now and nothing should be greyed out."""
        from g7ctlc.views.triggers_view import TriggersView
        view = TriggersView()
        for side in ("left", "right"):
            ed = view.sides[side].curve_points
            ed.set_points_enabled(True)
            for i, (x, y) in enumerate(ed.rows):
                self.assertTrue(x.isEnabled(), f"{side} point {i+1} x")
                self.assertTrue(y.isEnabled(), f"{side} point {i+1} y")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class CurveEditorTest(unittest.TestCase):
    """Coordinate mapping and handle constraints for the graphical editor.

    The mapping is the part worth pinning: endpoints are 0-100 percentages
    of the full axis while interior points are 0-255 positions *within the
    span the endpoints define*. They are separate coordinate systems, and
    conflating them was a mistake that took several captures to unwind --
    see PROTOCOL.md "A curve is five handles".
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self, dz=(0, 100), adz=(0, 100), points=None):
        from g7ctlc.curve_editor import CurveEditor
        ed = CurveEditor()
        ed.resize(300, 240)
        ed.set_curve(dz[0], dz[1], adz[0], adz[1],
                     points or [[40, 41], [128, 128], [215, 214]])
        return ed

    def test_interior_points_map_within_the_endpoint_span(self):
        # dz 5..50 -> a point at 128/255 sits at 5 + 0.502*45 = 27.6%
        ed = self._editor(dz=(5, 50), adz=(0, 100))
        x_pct, y_pct = ed._point_to_pct(128, 128)
        self.assertAlmostEqual(x_pct, 5 + (128 / 255) * 45, places=3)
        self.assertAlmostEqual(y_pct, (128 / 255) * 100, places=3)

    def test_mapping_round_trips(self):
        ed = self._editor(dz=(5, 50), adz=(10, 90))
        for px, py in ((0, 0), (128, 128), (255, 255), (40, 200)):
            x, y = ed._point_to_pct(px, py)
            self.assertEqual(ed._pct_to_point(x, y), (px, py))

    def test_a_zero_width_span_does_not_divide_by_zero(self):
        """Both endpoints on the same X is reachable by dragging, and every
        interior point then maps to one place -- so the inverse is refused
        rather than crashing."""
        ed = self._editor(dz=(50, 50), adz=(0, 100))
        self.assertEqual(ed._pct_to_point(50, 50)[0], None)

    def test_endpoints_cannot_cross(self):
        ed = self._editor(dz=(20, 60), adz=(10, 90))
        ed._move_endpoint(0, 95, 99)      # shove the bottom endpoint past the top
        self.assertLessEqual(ed._dz[0], ed._dz[1])
        self.assertLessEqual(ed._adz[0], ed._adz[1])
        ed._move_endpoint(1, 0, 0)        # and the top below the bottom
        self.assertLessEqual(ed._dz[0], ed._dz[1])

    def test_interior_points_cannot_cross_their_neighbours(self):
        ed = self._editor(dz=(0, 100), adz=(0, 100))
        ed._move_point(0, 100, 100)       # drag point 1 to the far corner
        pts = ed.points()
        self.assertLessEqual(pts[0][0], pts[1][0])
        self.assertLessEqual(pts[0][1], pts[1][1])

    def test_points_are_not_rescaled_when_an_endpoint_moves(self):
        """Matches the device: halving deadzone_max in Nexus left the stored
        interior points untouched (test64). They are relative to the span,
        so they follow without being rewritten."""
        ed = self._editor(dz=(5, 95), adz=(0, 100))
        before = ed.points()
        ed._move_endpoint(1, 50, 100)
        self.assertEqual(ed.points(), before)

    def test_dragging_only_emits_on_release(self):
        """A signal per mouse-move would queue a device write per pixel."""
        from PyQt6.QtCore import QPointF
        ed = self._editor()
        seen = []
        ed.points_changed.connect(seen.append)
        ed._drag = ("pt", 1)
        ed._move_point(1, 60, 60)
        self.assertEqual(seen, [], "must not emit mid-drag")
        ed.mouseReleaseEvent(None)
        self.assertEqual(len(seen), 1)
        del QPointF

    def test_interior_handles_are_not_grabbable_when_points_are_disabled(self):
        """A non-Custom preset must not let the interior points be dragged,
        since only the endpoints apply there."""
        from PyQt6.QtCore import QPointF
        ed = self._editor()
        ed.set_points_editable(False)
        target = ed._handle_positions()[2][2]      # an interior handle
        self.assertIsNone(ed._hit(QPointF(target)))
        ed.set_points_editable(True)
        self.assertEqual(ed._hit(QPointF(target))[0], "pt")

    def test_plot_rect_is_cached_but_still_tracks_a_real_resize(self):
        """_plot_rect() is called once per handle on every hover mouse-move
        (setMouseTracking), not just drags -- cached to avoid rebuilding a
        QRectF from scratch on that path. The cache must still notice a real
        size change, not go stale and keep answering with the old geometry."""
        from g7ctlc.curve_editor import _MARGIN_B, _MARGIN_L, _MARGIN_R, _MARGIN_T
        ed = self._editor()
        first = ed._plot_rect()
        self.assertIs(ed._plot_rect(), first, "same size -- must reuse the cached rect, not rebuild")

        ed.resize(500, 400)
        second = ed._plot_rect()
        self.assertIsNot(second, first, "a real resize must invalidate the cache")
        self.assertEqual((second.width(), second.height()),
                         (500 - _MARGIN_L - _MARGIN_R, 400 - _MARGIN_T - _MARGIN_B))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class UnconfiguredCurveTest(unittest.TestCase):
    """A profile whose curve block was never written.

    Profiles 3 and 4 on the development controller read `00 00 ...` across
    the whole block, scale byte included. Decoding that as three points at
    the origin put three handles on top of the bottom endpoint -- reported
    as "profiles 3 and 4 don't have interior points on the graph" -- and
    would have written a degenerate curve back on the next sync.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_an_unwritten_block_decodes_as_no_points(self):
        from pyg7 import sticks
        from tests.fakes import blob_with
        # dz/adz present and valid, curve block untouched -- profile 3's shape
        blob = blob_with({0x13F: 10, 0x140: 100, 0x142: 100})
        s = sticks.decode_settings(blob, "left")
        self.assertEqual(s["deadzone"], {"initial": 10, "max": 100})
        self.assertIsNone(s["curve"]["points"],
                          "an unwritten block must not decode as (0,0) x3")

    def test_a_written_block_still_decodes(self):
        from pyg7 import curves, sticks
        from tests.fakes import blob_with
        blob = blob_with({0x145: curves.CURVE_SCALE_CONFIGURED,
                          0x148: 40, 0x149: 41, 0x14A: 128,
                          0x14B: 128, 0x14C: 215, 0x14D: 214})
        s = sticks.decode_settings(blob, "left")
        self.assertEqual(s["curve"]["points"], [[40, 41], [128, 128], [215, 214]])

    def test_the_editor_hides_interior_handles_when_unconfigured(self):
        from g7ctlc.curve_editor import CurveEditor
        ed = CurveEditor()
        ed.resize(300, 240)
        ed.set_curve(10, 100, 0, 100, None)
        kinds = [k for k, _i, _p in ed._handle_positions()]
        self.assertEqual(kinds, ["end", "end"],
                         "only the two endpoints should be drawn")

    def test_selecting_custom_seeds_points_from_the_preset_on_screen(self):
        """Nexus keeps the shape on screen when you switch preset -> Custom;
        starting from three points at the origin would be worse than useless."""
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("t")
        state["sticks"]["left"]["curve"] = {"preset": "concave", "points": None}
        view = SticksView()
        view.load_state(state)
        side = view.sides["left"]
        side.curve.setCurrentText("custom")
        out = {}
        side.save_into(out)
        self.assertEqual(out["curve"]["points"], [[94, 23], [176, 79], [232, 161]],
                         "should seed from Concave, the preset that was showing")

    def test_switching_to_custom_never_emits_changed_with_unseeded_points(self):
        """Real bug, found 2026-09-01: curve.currentIndexChanged used to
        connect _emit_changed() before _update_curve_points_enabled() (Qt
        fires slots in connection order), so switching to "custom" emitted
        `changed` -- which the real app wires straight to save_into(),
        writing into MainWindow's live state -- one signal-fire BEFORE the
        seeding step replaced the widget's placeholder zeros with the
        shown preset's shape. The test above doesn't catch this: it calls
        save_into() manually, after both slots have already run in
        whatever order, so it only ever sees the final, correct widget
        state. This test instead captures what curve_points actually held
        at the moment each `changed` fired, which is what a real listener
        (MainWindow) would have saved."""
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("t")
        state["sticks"]["left"]["curve"] = {"preset": "concave", "points": None}
        view = SticksView()
        view.load_state(state)
        side = view.sides["left"]

        captured = []
        side.changed.connect(lambda: captured.append(side.curve_points.points()))
        side.curve.setCurrentText("custom")

        self.assertTrue(captured, "switching preset must emit changed at least once")
        for points in captured:
            self.assertNotEqual(
                points, [[0, 0], [0, 0], [0, 0]],
                "changed fired with the widget's unseeded placeholder zeros -- "
                "seeding must happen before this signal, not after")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsViewContinuousTriggerTest(unittest.TestCase):
    """Continuous Trigger checkboxes on the Buttons tab.

    Scoped to the data plumbing -- load a state in, edit, read it back out --
    because that is what a headless run can actually prove. Offscreen Qt will
    happily report a widget as visible when nothing was ever painted, so
    nothing here is evidence about how the tab *looks*; the column's
    appearance still needs a human on a real desktop.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        from g7ctlc.views.buttons_view import ButtonsView
        return ButtonsView()

    def test_flags_round_trip(self):
        view = self._view()
        state = state_mod.default_state_dict()
        state["continuous_trigger"] = {"a": True, "y": True}
        view.load_state(state)
        self.assertTrue(view._continuous["a"].isChecked())
        self.assertTrue(view._continuous["y"].isChecked())
        self.assertFalse(view._continuous["b"].isChecked())

        view._continuous["b"].setChecked(True)
        view._continuous["a"].setChecked(False)
        self.assertEqual(state["continuous_trigger"]["b"], True)
        self.assertEqual(state["continuous_trigger"]["a"], False)
        self.assertEqual(state["continuous_trigger"]["y"], True)

    def test_triggers_have_no_checkbox_at_all(self):
        # LT/RT have no button-table record, so offering a checkbox would be
        # offering a control that cannot be written -- see
        # pyg7.buttons.continuous_trigger_offset().
        view = self._view()
        self.assertNotIn("lt", view._continuous)
        self.assertNotIn("rt", view._continuous)

    def test_every_table_slot_the_gui_shows_has_a_checkbox(self):
        from pyg7.buttons import BUTTON_TABLE_SLOTS
        view = self._view()
        for slot in BUTTON_TABLE_SLOTS:
            if slot is not None:
                self.assertIn(slot, view._continuous, f"{slot} has no Continuous Trigger checkbox")

    def test_written_flags_are_accepted_by_validate_state(self):
        # The view writes a bool for every slot, including unbound ones. If
        # that shape didn't validate, the GUI would build states it cannot
        # save -- which is only caught by running the two together.
        view = self._view()
        state = state_mod.default_state_dict()
        view.load_state(state)
        view._continuous["a"].setChecked(True)
        state_mod.validate_state(state)

    def test_shift_layer_hides_the_column(self):
        # Continuous Trigger is per-profile; the Shift layer is device-global. Note
        # this asserts the visibility *flag*, not that anything was painted.
        view = self._view()
        view.set_layer("shift")
        self.assertFalse(view.continuous_header.isVisible())
        view.set_layer("default")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class MotionViewRoundTripTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_custom_curve_points_survive_an_unrelated_edit(self):
        # REAL BUG, found 2026-09-18 (Sol's bug-sweep): save_into() used to
        # set curve["points"] = None UNCONDITIONALLY on every edit --
        # actively discarding real custom points a device read may have
        # successfully decoded (pyg7.motion.decode_settings() does return
        # them when the block is configured; only the WRITE side has no
        # curve_points setting yet). This widget has no point-editor UI of
        # its own, so it can't legitimately claim to know better than
        # whatever was already there.
        from g7ctlc.views.motion_view import MotionView
        state = state_mod.default_state_dict("test")
        points = [[1, 2], [3, 4], [5, 6]]
        state["motion"]["aim"]["curve"] = {"preset": "custom", "points": points}
        view = MotionView()
        view.load_state(state)

        view._on_edit()  # an edit touching fields this widget DOES own

        self.assertEqual(state["motion"]["aim"]["curve"]["points"], points,
                          "an edit to fields this widget owns must not erase "
                          "custom curve points that were already in state")

    def test_a_brand_new_curve_defaults_points_to_none(self):
        # Not a regression guard for the bug above -- confirms the fix
        # didn't just remove the assignment outright: a curve dict that
        # never had a "points" key at all (a fresh state, or an older
        # export predating this section) still gets one, same as before.
        from g7ctlc.views.motion_view import MotionView
        state = state_mod.default_state_dict("test")
        del state["motion"]["aim"]["curve"]
        view = MotionView()
        view.load_state(state)

        view._on_edit()

        self.assertIn("points", state["motion"]["aim"]["curve"])
        self.assertIsNone(state["motion"]["aim"]["curve"]["points"])
