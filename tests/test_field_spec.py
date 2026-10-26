"""Unit tests for FieldSpec/Intent (S3, Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- gate 1 of the three that the agreed
sequencing asks for per migrated category (unit, capture-replay,
hardware noninterference). Capture-replay is
tests/test_state_write_parity.py, already exercising REPORT_RATE_FIELD
indirectly through write_state() and still green after this migration.
The hardware noninterference gate is a real-device run, not a pytest
case -- see Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md's S3 status
note for that result.
"""
import unittest

from pyg7.field_spec import (
    BUTTON_FIELDS,
    CT_FIELDS,
    DOCK_FIELDS,
    DPAD_FIELDS,
    MOTION_FIELDS,
    REPORT_RATE_FIELD,
    STICK_FIELDS,
    TRIGGER_FIELDS,
    VIBRATION_FLAGS_FIELDS,
    VIBRATION_LEVEL_FIELDS,
    FieldSpec,
    Intent,
)
from pyg7.operations import Operation

from .fakes import blob_with


class FieldSpecPlanOperationTest(unittest.TestCase):
    """Generic behaviour against a throwaway FieldSpec, not report rate
    specifically -- report rate has no clear semantics, so these three
    PRESERVE/CLEAR cases need a field that actually supports a clear to
    be worth asserting at all."""

    def setUp(self):
        self.spec = FieldSpec(
            name="throwaway",
            operation_kind="dock_setting",  # any real registry key; unused, not executed here
            decode=lambda blob: blob[0] or None,
            supports_clear=True,
        )

    def test_preserve_never_writes_regardless_of_baseline(self):
        self.assertIsNone(self.spec.plan_operation(Intent.PRESERVE, baseline=5, profile=1))
        self.assertIsNone(self.spec.plan_operation(Intent.PRESERVE, baseline=None, profile=1))

    def test_clear_on_a_field_without_clear_support_raises(self):
        no_clear = FieldSpec(name="x", operation_kind="report_rate", decode=lambda b: None)
        with self.assertRaises(ValueError):
            no_clear.plan_operation(Intent.CLEAR, baseline=5, profile=1)

    def test_clear_on_a_supporting_field_writes_none_as_the_value(self):
        op = self.spec.plan_operation(Intent.CLEAR, baseline=5, profile=1)
        self.assertIsInstance(op, Operation)
        self.assertEqual(op.args, (None,))

    def test_a_value_matching_baseline_is_skipped(self):
        self.assertIsNone(self.spec.plan_operation(7, baseline=7, profile=1))

    def test_a_value_differing_from_baseline_is_written(self):
        op = self.spec.plan_operation(7, baseline=3, profile=1)
        self.assertIsInstance(op, Operation)
        self.assertEqual(op.kind, "dock_setting")
        self.assertEqual(op.args, (7,))

    def test_no_baseline_always_writes_a_real_value(self):
        op = self.spec.plan_operation(7, baseline=None, profile=1)
        self.assertIsInstance(op, Operation)

    def test_custom_compare_is_actually_used(self):
        # A field whose compare() always says "different" writes even
        # when the raw values are equal -- proves compare() is the real
        # decision point, not a dead parameter.
        always_different = FieldSpec(
            name="y", operation_kind="report_rate", decode=lambda b: None,
            compare=lambda a, b: False,
        )
        op = always_different.plan_operation(5, baseline=5, profile=1)
        self.assertIsNotNone(op)


class ReportRateFieldTest(unittest.TestCase):
    """REPORT_RATE_FIELD specifically -- the first real category migrated."""

    def test_decode_reads_the_same_offset_report_rate_py_writes(self):
        from pyg7.report_rate import SETTING_ID
        blob = blob_with({SETTING_ID: 0x02}, size=512)  # 0x02 -> 1000 Hz
        self.assertEqual(REPORT_RATE_FIELD.decode(blob), 1000)

    def test_decode_returns_none_for_an_unrecognized_byte(self):
        from pyg7.report_rate import SETTING_ID
        blob = blob_with({SETTING_ID: 0xFF}, size=512)
        self.assertIsNone(REPORT_RATE_FIELD.decode(blob))

    def test_plan_operation_builds_the_exact_same_operation_set_value_needs(self):
        op = REPORT_RATE_FIELD.plan_operation(500, baseline=1000, profile=3)
        self.assertEqual(op, Operation("report_rate", (500,), {"profile": 3}))

    def test_undeclared_preserves_even_with_a_stale_baseline(self):
        self.assertIsNone(REPORT_RATE_FIELD.plan_operation(Intent.PRESERVE, baseline=1000, profile=1))

    def test_matching_baseline_skips(self):
        self.assertIsNone(REPORT_RATE_FIELD.plan_operation(500, baseline=500, profile=1))


class VibrationLevelFieldsTest(unittest.TestCase):
    """VIBRATION_LEVEL_FIELDS -- the second category migrated, and the
    first with more than one field sharing a build_args closure pattern
    (each needs its own setting name baked in, unlike report rate)."""

    def test_all_four_levels_are_present(self):
        self.assertEqual(set(VIBRATION_LEVEL_FIELDS),
                          {"left_grip", "right_grip", "left_trigger", "right_trigger"})

    def test_decode_reads_the_same_offsets_vibration_py_writes(self):
        from pyg7.vibration import LEVEL_SETTING_IDS
        blob = blob_with({sid: 75 for sid in LEVEL_SETTING_IDS.values()}, size=512)
        for name, spec in VIBRATION_LEVEL_FIELDS.items():
            self.assertEqual(spec.decode(blob), 75, name)

    def test_plan_operation_bakes_in_the_right_setting_name(self):
        op = VIBRATION_LEVEL_FIELDS["right_trigger"].plan_operation(50, baseline=0, profile=2)
        self.assertEqual(op, Operation("vibration_setting", ("right_trigger", 50), {"profile": 2}))

    def test_two_fields_dont_cross_contaminate_their_setting_name(self):
        left = VIBRATION_LEVEL_FIELDS["left_grip"].plan_operation(25, baseline=0, profile=1)
        right = VIBRATION_LEVEL_FIELDS["right_grip"].plan_operation(25, baseline=0, profile=1)
        self.assertEqual(left.args[0], "left_grip")
        self.assertEqual(right.args[0], "right_grip")

    def test_matching_baseline_skips(self):
        self.assertIsNone(VIBRATION_LEVEL_FIELDS["left_grip"].plan_operation(50, baseline=50, profile=1))


class VibrationFlagsFieldsTest(unittest.TestCase):
    """VIBRATION_FLAGS_FIELDS -- the coupled-write case this phase
    deliberately left open until now: Force+Sync share one wire byte.
    Mirrors the real bug fixed 2026-09-01 in _vibration_steps() (an
    undeclared half used to write as "off" instead of preserving its
    own baseline) -- these assert the FieldSpec version got the fix
    right too, not just that it compiles."""

    def test_both_declared_combine_directly(self):
        op = VIBRATION_FLAGS_FIELDS["left"].plan_operation(
            {"force": True, "sync": False}, {"force": None, "sync": None}, profile=1)
        self.assertEqual(op.args, ("left_trigger_flags", "on,off"))

    def test_undeclared_half_carries_forward_from_its_own_baseline_not_off(self):
        # Only sync declared; force must resolve to the baseline's real
        # value (True), not a hardcoded "off" -- the exact 2026-09-01 bug.
        op = VIBRATION_FLAGS_FIELDS["right"].plan_operation(
            {"force": Intent.PRESERVE, "sync": True}, {"force": True, "sync": False}, profile=1)
        self.assertEqual(op.args, ("right_trigger_flags", "on,on"))

    def test_undeclared_half_with_no_baseline_falls_back_to_off(self):
        # No honest value to preserve at all (fresh/never-read field) --
        # this is the one case "off" is actually correct.
        op = VIBRATION_FLAGS_FIELDS["left"].plan_operation(
            {"force": Intent.PRESERVE, "sync": True}, {"force": None, "sync": None}, profile=1)
        self.assertEqual(op.args, ("left_trigger_flags", "off,on"))

    def test_resolved_value_matching_baseline_skips(self):
        op = VIBRATION_FLAGS_FIELDS["left"].plan_operation(
            {"force": True, "sync": False}, {"force": True, "sync": False}, profile=1)
        self.assertIsNone(op)

    def test_no_baseline_at_all_always_writes(self):
        op = VIBRATION_FLAGS_FIELDS["left"].plan_operation(
            {"force": True, "sync": False}, {"force": None, "sync": None}, profile=1)
        self.assertIsNotNone(op)


class VibrationFlagsCallSiteTest(unittest.TestCase):
    """The one thing CoupledFieldSpec can't decide by itself: whether
    BOTH halves are undeclared, which _vibration_steps() must skip
    without counting -- see that function's own comment."""

    def test_both_halves_undeclared_skips_without_counting(self):
        from pyg7 import state as state_mod
        steps, skipped = state_mod._vibration_steps(
            {"left_grip": None, "right_grip": None, "left_trigger": None, "right_trigger": None},
            baseline=None, profile=1)
        self.assertEqual(steps, [])
        self.assertEqual(skipped, 0)


class StickAndTriggerFieldsTest(unittest.TestCase):
    """STICK_FIELDS/TRIGGER_FIELDS -- the third category migrated. Both
    sides' simple fields share one factory (_side_field()); these tests
    cover the shape every one of them has to get right, plus the two
    fields that don't fit the plain per-setting-name pattern:
    curve_points (canonical comparator) and direction_bindings (already
    a combined value by the time it reaches a FieldSpec)."""

    def test_every_side_has_every_simple_setting(self):
        expected = {"trajectory", "curve", "curve_points", "deadzone_initial", "deadzone_max",
                    "anti_deadzone_initial", "anti_deadzone_max", "resolution_bits", "output_mode",
                    "invert_x", "invert_y", "sensitivity", "overlap_area", "dpi", "direction_bindings"}
        self.assertEqual(set(STICK_FIELDS["left"]), expected)
        self.assertEqual(set(STICK_FIELDS["right"]), expected)
        self.assertEqual(set(TRIGGER_FIELDS["left"]),
                          {"hair_trigger_mode", "curve", "curve_points",
                           "deadzone_initial", "deadzone_max", "anti_deadzone_initial", "anti_deadzone_max"})

    def test_plan_operation_bakes_in_side_and_setting_name(self):
        op = STICK_FIELDS["right"]["sensitivity"].plan_operation(70, baseline=50, profile=2)
        self.assertEqual(op, Operation("stick_setting", ("right", "sensitivity", 70), {"profile": 2}))
        op2 = TRIGGER_FIELDS["left"]["hair_trigger_mode"].plan_operation("adaptive", baseline="off", profile=1)
        self.assertEqual(op2, Operation("trigger_setting", ("left", "hair_trigger_mode", "adaptive"), {"profile": 1}))

    def test_decode_reads_the_real_nested_shape(self):
        from pyg7.sticks import OUTPUT_MODES, SETTING_IDS, STORAGE_BASE
        blob = blob_with({SETTING_IDS["output_mode"] + STORAGE_BASE: OUTPUT_MODES["mouse"]}, size=512)
        self.assertEqual(STICK_FIELDS["left"]["output_mode"].decode(blob), "mouse")

    def test_curve_points_uses_the_canonical_comparator_not_raw_equality(self):
        # Different Python shapes, same curve -- a list of lists vs a
        # flat list of numbers must compare equal, the exact reason this
        # field doesn't use FieldSpec's plain `a == b` default.
        field = STICK_FIELDS["left"]["curve_points"]
        as_lists = [[0, 0], [50, 60], [100, 100]]
        as_flat = [0, 0, 50, 60, 100, 100]
        self.assertIsNone(field.plan_operation(as_lists, baseline=as_flat, profile=1))

    def test_curve_points_genuinely_different_curves_still_write(self):
        field = STICK_FIELDS["left"]["curve_points"]
        op = field.plan_operation([[0, 0], [50, 60], [100, 100]], baseline=[[0, 0], [50, 40], [100, 100]], profile=1)
        self.assertIsNotNone(op)

    def test_direction_bindings_decode_matches_the_combine_convention(self):
        from pyg7.buttons import resolve_keycode
        from pyg7.sticks import SETTING_IDS, STORAGE_BASE

        db_offset = SETTING_IDS["direction_bindings"] + STORAGE_BASE
        native_up = resolve_keycode("native_dpad_up")
        blob = blob_with({
            db_offset + 0: native_up,  # up: a real binding
            db_offset + 1: 0xFF,       # down: unbound
            db_offset + 2: 0xFF,       # left: unbound
            db_offset + 3: 0xFF,       # right: unbound
            db_offset + 4: 0xFF,       # ring: unbound
        }, size=512)
        decoded = STICK_FIELDS["left"]["direction_bindings"].decode(blob)
        self.assertEqual(decoded, "native_dpad_up,ff,ff,ff,ff")

    def test_direction_bindings_plan_operation_writes_the_combined_string(self):
        field = STICK_FIELDS["right"]["direction_bindings"]
        op = field.plan_operation("ff,ff,native_dpad_left,ff,ff", baseline=None, profile=3)
        self.assertEqual(op, Operation(
            "stick_setting", ("right", "direction_bindings", "ff,ff,native_dpad_left,ff,ff"), {"profile": 3}))

    def test_matching_baseline_skips_for_a_simple_field(self):
        self.assertIsNone(TRIGGER_FIELDS["left"]["deadzone_initial"].plan_operation(10, baseline=10, profile=1))


class DpadAndDockFieldsTest(unittest.TestCase):
    """DPAD_FIELDS/DOCK_FIELDS -- the fourth and fifth categories
    migrated, both small. The one thing worth a dedicated test: dock
    settings have no `profile=` argument at all, unlike every other
    category migrated so far."""

    def test_dpad_field_names_dont_match_set_value_setting_names(self):
        # decode uses the state-dict key ("dpad_diagonal_lock"); the
        # Operation it builds uses dpad_options.set_value()'s own
        # shorter name ("diagonal_lock") -- this split is deliberate,
        # not a naming inconsistency to "fix".
        op = DPAD_FIELDS["dpad_diagonal_lock"].plan_operation(True, baseline=False, profile=2)
        self.assertEqual(op, Operation("dpad_option", ("diagonal_lock", True), {"profile": 2}))

    def test_dpad_decode_reads_the_state_dict_key(self):
        from pyg7.dpad_options import DIAGONAL_LOCK_SETTING_ID
        blob = blob_with({DIAGONAL_LOCK_SETTING_ID: 1}, size=512)
        self.assertTrue(DPAD_FIELDS["dpad_diagonal_lock"].decode(blob))

    def test_dock_fields_build_no_profile_kwarg_at_all(self):
        op = DOCK_FIELDS["dock_led_brightness"].plan_operation(75, baseline=50, profile=4)
        self.assertEqual(op, Operation("dock_setting", ("brightness", 75), {}))
        op2 = DOCK_FIELDS["dock_auto_on_off"].plan_operation(True, baseline=False, profile=4)
        self.assertEqual(op2, Operation("dock_setting", ("auto_on_off", True), {}))

    def test_dock_decode_reads_the_real_offsets(self):
        from pyg7.constants import DOCK_STORAGE_BASE
        from pyg7.dock_settings import AUTO_ON_OFF_SETTING_ID, BRIGHTNESS_SETTING_ID
        blob = blob_with({
            BRIGHTNESS_SETTING_ID + DOCK_STORAGE_BASE: 60,
            AUTO_ON_OFF_SETTING_ID + DOCK_STORAGE_BASE: 1,
        }, size=512)
        self.assertEqual(DOCK_FIELDS["dock_led_brightness"].decode(blob), 60)
        self.assertTrue(DOCK_FIELDS["dock_auto_on_off"].decode(blob))

    def test_matching_baseline_skips(self):
        self.assertIsNone(DPAD_FIELDS["swap_stick_dpad"].plan_operation(True, baseline=True, profile=1))
        self.assertIsNone(DOCK_FIELDS["dock_led_brightness"].plan_operation(50, baseline=50, profile=1))


class MotionFieldsTest(unittest.TestCase):
    """MOTION_FIELDS -- the sixth category migrated, and the first with
    real Intent.CLEAR usage (activate_button, direction_* zones have a
    genuine 0xFF-on-the-wire clear value, decoded back as Python None).
    These exercise FieldSpec.plan_operation()'s CLEAR path directly,
    independent of the has_baseline disambiguation state.py's _add()
    owns -- see tests/test_state_absent_vs_null.py for that logic
    exercised end to end through _motion_steps() itself."""

    def test_invert_roll_only_exists_on_aim(self):
        self.assertIn("invert_roll", MOTION_FIELDS["aim"])
        self.assertNotIn("invert_roll", MOTION_FIELDS["tilt"])

    def test_activate_button_clear_writes_the_sentinel_none(self):
        op = MOTION_FIELDS["aim"]["activate_button"].plan_operation(Intent.CLEAR, baseline="native_a", profile=1)
        self.assertEqual(op, Operation("motion_setting", ("aim", "activate_button", None), {"profile": 1}))

    def test_activate_button_clear_on_a_field_without_supports_clear_would_raise(self):
        # Sanity check that supports_clear is actually set on this field
        # (every migrated field without it raises on Intent.CLEAR, see
        # FieldSpecPlanOperationTest) -- this one must NOT raise.
        try:
            MOTION_FIELDS["aim"]["activate_button"].plan_operation(Intent.CLEAR, baseline=None, profile=1)
        except ValueError:
            self.fail("activate_button should support Intent.CLEAR")

    def test_direction_zone_clear_bakes_in_the_right_setting_name(self):
        op = MOTION_FIELDS["tilt"]["direction_up"].plan_operation(Intent.CLEAR, baseline="native_dpad_up", profile=3)
        self.assertEqual(op, Operation("motion_setting", ("tilt", "direction_up", None), {"profile": 3}))

    def test_plain_field_plan_operation_bakes_in_side_and_setting_name(self):
        op = MOTION_FIELDS["aim"]["sensitivity_scale"].plan_operation(70, baseline=50, profile=1)
        self.assertEqual(op, Operation("motion_setting", ("aim", "sensitivity_scale", 70), {"profile": 1}))

    def test_decode_reads_the_real_nested_shape(self):
        from pyg7.motion import ACTIVATE_METHODS, SETTING_IDS, STORAGE_BASE

        def off(setting):
            from pyg7.motion import _side_offset
            return _side_offset("aim", setting)

        blob = blob_with(
            {SETTING_IDS["activate_method"] + STORAGE_BASE + off("activate_method"): ACTIVATE_METHODS["hold_to_activate"]},
            size=512)
        self.assertEqual(MOTION_FIELDS["aim"]["activate_method"].decode(blob), "hold_to_activate")


class ButtonFieldsTest(unittest.TestCase):
    """BUTTON_FIELDS/ButtonFieldSpec -- the seventh and last category
    migrated, and the only one that needed its own class rather than
    FieldSpec: remap() and unbind() are genuinely different wire
    operations, not one function with a sentinel value."""

    def test_both_layers_have_every_known_button(self):
        from pyg7.buttons import KNOWN_BUTTON_IDS
        self.assertEqual(set(BUTTON_FIELDS["default"]), set(KNOWN_BUTTON_IDS))
        self.assertEqual(set(BUTTON_FIELDS["shift"]), set(KNOWN_BUTTON_IDS))

    def test_a_real_value_builds_button_remap_not_unbind(self):
        op = BUTTON_FIELDS["default"]["a"].plan_operation("native_x", baseline=None, profile=2)
        self.assertEqual(op.kind, "button_remap")
        self.assertEqual(op.kwargs, {"profile": 2, "shift": False})

    def test_clear_builds_button_unbind_not_remap(self):
        from pyg7.buttons import resolve_button_id

        op = BUTTON_FIELDS["default"]["a"].plan_operation(Intent.CLEAR, baseline=None, profile=2)
        self.assertEqual(op.kind, "button_unbind")
        self.assertEqual(op.args, (resolve_button_id("a"),))

    def test_baseline_is_accepted_and_ignored(self):
        # Buttons' own skip-vs-write decision is made entirely by the
        # caller (see the class docstring) -- plan_operation() must build
        # the exact same Operation no matter what baseline is passed.
        op_with_baseline = BUTTON_FIELDS["default"]["a"].plan_operation("native_x", baseline="native_y", profile=2)
        op_without = BUTTON_FIELDS["default"]["a"].plan_operation("native_x", baseline=None, profile=2)
        self.assertEqual(op_with_baseline, op_without)

    def test_shift_layer_field_always_writes_shift_true(self):
        op = BUTTON_FIELDS["shift"]["y"].plan_operation("native_y", baseline=None, profile=1)
        self.assertEqual(op.kwargs["shift"], True)
        op2 = BUTTON_FIELDS["shift"]["y"].plan_operation(Intent.CLEAR, baseline=None, profile=1)
        self.assertEqual(op2.kwargs["shift"], True)

    def test_default_layer_field_always_writes_shift_false(self):
        op = BUTTON_FIELDS["default"]["y"].plan_operation("native_y", baseline=None, profile=1)
        self.assertEqual(op.kwargs["shift"], False)

    def test_decode_reads_the_whole_table_and_picks_this_button(self):
        from pyg7.buttons import KNOWN_KEYCODES

        from .fakes import button_record

        record = button_record(KNOWN_KEYCODES["native_a"])
        blob = bytearray(blob_with({}, size=512))
        blob[0x7A:0x7A + 7] = record  # "a" button's record offset
        self.assertEqual(BUTTON_FIELDS["default"]["a"].decode(bytes(blob)), "native_a")

    def test_continuous_trigger_excludes_the_reserved_none_slot(self):
        self.assertNotIn(None, CT_FIELDS)

    def test_continuous_trigger_is_a_plain_field_no_clear_semantics(self):
        self.assertFalse(CT_FIELDS["lb"].supports_clear)

    def test_continuous_trigger_plan_operation_bakes_in_the_button(self):
        op = CT_FIELDS["rb"].plan_operation(True, baseline=False, profile=3)
        self.assertEqual(op, Operation("continuous_trigger", ("rb", True), {"profile": 3}))

    def test_continuous_trigger_matching_baseline_skips(self):
        self.assertIsNone(CT_FIELDS["lb"].plan_operation(True, baseline=True, profile=1))


if __name__ == "__main__":
    unittest.main()
