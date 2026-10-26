"""S2 regression test (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md,
Track S) for the absent-vs-null decision DESIGN-SPEC.md 10.4 asked for.

Real bug, not hypothetical (plan section 7, "Partial state JSON clears
Motion bindings"): the CLI's `write-state` never passes a baseline, and
`_motion_steps()` used `dict.get(key)` for its two `allow_none` fields
(`activate_button`, `direction_bindings.*`) -- which can't tell "this key
was never in the file" from "this key is explicitly null." A hand-edited
partial state JSON that simply never mentions `activate_button` had it
read back as an explicit clear and silently wiped the binding. Fixed by
guarding the call with `"activate_button" in s` / `zone not in db`
instead of changing `_add()`'s own allow_none semantics, so every other
field's behaviour (and a fully-populated dict's, e.g. anything the GUI
itself produces) is unchanged.
"""
import copy
import unittest

from pyg7 import state as state_mod


def _motion_setting_kinds(steps):
    return [op.args[1] for _label, op in steps]


class AbsentVersusNullMotionTest(unittest.TestCase):
    """Exercises _motion_steps() directly, one side at a time, to avoid
    Aim/Tilt's own independent (and independently correct) entries
    crowding the assertions -- _build_steps() itself is covered end to
    end by tests/test_state_write_parity.py already."""

    def setUp(self):
        self.aim = state_mod._default_motion_settings("aim")

    def test_activate_button_absent_from_partial_dict_is_not_cleared(self):
        s = copy.deepcopy(self.aim)
        del s["activate_button"]
        steps, _skipped = state_mod._motion_steps("aim", s, baseline=None, profile=1)
        self.assertNotIn("activate_button", _motion_setting_kinds(steps))

    def test_activate_button_present_as_explicit_null_is_still_cleared(self):
        s = copy.deepcopy(self.aim)
        s["activate_button"] = None
        steps, _skipped = state_mod._motion_steps("aim", s, baseline=None, profile=1)
        self.assertIn("activate_button", _motion_setting_kinds(steps))

    def test_activate_button_present_with_a_real_value_is_written(self):
        s = copy.deepcopy(self.aim)
        s["activate_button"] = "native_a"
        steps, _skipped = state_mod._motion_steps("aim", s, baseline=None, profile=1)
        matches = [op for _label, op in steps if op.args[1] == "activate_button"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].args[2], "native_a")

    def test_direction_binding_zone_absent_from_partial_dict_is_not_cleared(self):
        s = copy.deepcopy(self.aim)
        del s["direction_bindings"]["up"]
        steps, _skipped = state_mod._motion_steps("aim", s, baseline=None, profile=1)
        self.assertNotIn("direction_up", _motion_setting_kinds(steps))

    def test_direction_binding_zone_present_as_explicit_null_is_still_cleared(self):
        s = copy.deepcopy(self.aim)
        s["direction_bindings"]["up"] = None
        steps, _skipped = state_mod._motion_steps("aim", s, baseline=None, profile=1)
        self.assertIn("direction_up", _motion_setting_kinds(steps))

    def test_fully_populated_default_motion_settings_is_unaffected(self):
        # Guards the fix itself: _default_motion_settings() (what the GUI
        # always builds from) already has every key present -- this must
        # schedule exactly the same writes as before the fix, not
        # silently start skipping fields the old code used to write.
        steps, skipped = state_mod._motion_steps("aim", self.aim, baseline=None, profile=1)
        self.assertEqual(skipped, 0)
        kinds = _motion_setting_kinds(steps)
        self.assertIn("activate_button", kinds)  # present, value None -> still a real clear
        for zone_kind in ("direction_up", "direction_down", "direction_left", "direction_right"):
            self.assertIn(zone_kind, kinds)


if __name__ == "__main__":
    unittest.main()
