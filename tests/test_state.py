"""State schema and diff-sync tests.

Two things matter here:

  * validate_state() is the only thing standing between a hand-edited or
    imported JSON file and a write to persistent device config.
  * _build_steps()'s baseline diffing decides what actually gets written.
    Its failure mode is silent -- too many steps just wastes time, but too
    FEW means a setting the user changed never reaches the device.

The fixtures under tests/fixtures/ are genuine read_state() output captured
from the development controller, so the decoders are exercised against real
device data and not only against hand-built blobs.

One correction to that, 2026-08-07: `profile3_factory`'s "shift" section was
captured back when read_state() read category 0x07 for it, which the firmware
answers with Profile 1's *Default* layer -- so the fixture recorded Profile
1's bindings as though they were Profile 3's Shift layer. It reads `{}` now,
matching what read_state() reports when it has no address for a Shift
layer. The rest of the
fixture is untouched and still genuine. See pyg7/session.py's
profile_layer_byte() for the hardware evidence.
"""
import json
import pathlib
import unittest

from pyg7 import state as state_mod

FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "live_read.json").read_text())


class ReadStateIncludeDockTest(unittest.TestCase):
    """Dock settings are device-global, not profile-scoped (see
    pyg7/dock_settings.py), so re-reading them on every profile switch is
    pure waste -- read_state()'s `include_dock` lets a caller (the GUI's
    DeviceWatcher) skip that ~10-chunk read once it already has a
    known-good value from earlier in the same connection.
    """

    def _session(self):
        from .fakes import FakeSession
        return FakeSession(bytes(1024))

    def test_include_dock_true_reads_the_dock_blob_and_decodes_it(self):
        from pyg7.constants import DOCK_READ_CATEGORY
        sess = self._session()
        state = state_mod.read_state(sess, slot=1, include_dock=True, interval=0, pre_heartbeats=0)
        self.assertIsNotNone(state["dock_led_brightness"])
        self.assertIsNotNone(state["dock_auto_on_off"])
        categories_read = {category for category, _offset, _len in sess.reads}
        self.assertIn(DOCK_READ_CATEGORY, categories_read)

    def test_include_dock_false_skips_the_dock_blob_entirely(self):
        from pyg7.constants import DOCK_READ_CATEGORY
        sess = self._session()
        state = state_mod.read_state(sess, slot=1, include_dock=False, interval=0, pre_heartbeats=0)
        self.assertIsNone(state["dock_led_brightness"])
        self.assertIsNone(state["dock_auto_on_off"])
        categories_read = {category for category, _offset, _len in sess.reads}
        self.assertNotIn(DOCK_READ_CATEGORY, categories_read)

    def test_include_dock_false_result_still_validates(self):
        sess = self._session()
        state = state_mod.read_state(sess, slot=1, include_dock=False, interval=0, pre_heartbeats=0)
        state_mod.validate_state(state)  # must not raise -- None dock fields are valid


class ValidateStateTest(unittest.TestCase):
    def setUp(self):
        self.state = state_mod.default_state_dict("test")

    def test_default_state_is_valid(self):
        state_mod.validate_state(self.state)  # must not raise

    def test_rejects_non_dict(self):
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state([])

    def test_rejects_wrong_schema_version(self):
        self.state["schema_version"] = 99
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_rejects_missing_section(self):
        del self.state["vibration"]
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_rejects_bad_controller_slot(self):
        self.state["controller_slot"] = 5
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_allows_null_controller_slot(self):
        self.state["controller_slot"] = None
        state_mod.validate_state(self.state)

    def test_rejects_unknown_button(self):
        self.state["buttons"]["default"]["l9"] = "f1"
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_rejects_unknown_layer(self):
        self.state["buttons"]["turbo"] = {}
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_shift_bindings_are_valid_on_every_profile(self):
        """The Shift layer is device-global, so declaring Shift bindings is
        valid whichever profile the state targets -- they all address the
        same layer. validate_state() used to refuse these for Profiles 2-4,
        back when the write would have corrupted Profile 1."""
        for profile in (1, 2, 3, 4):
            with self.subTest(profile=profile):
                self.state["controller_slot"] = profile
                self.state["buttons"]["shift"] = {"y": "f1"}
                state_mod.validate_state(self.state)  # must not raise

    def test_allows_empty_shift_layer_on_any_profile(self):
        for profile in (1, 2, 3, 4):
            with self.subTest(profile=profile):
                self.state["controller_slot"] = profile
                self.state["buttons"]["shift"] = {}
                state_mod.validate_state(self.state)

    def test_rejects_unknown_keycode_name(self):
        self.state["buttons"]["default"]["a"] = "hyperspace"
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_accepts_raw_hex_keycode(self):
        # decode_button_table() emits these for keycodes with no name yet,
        # and real hardware produces them -- they must survive validation.
        self.state["buttons"]["default"]["a"] = "0x11"
        state_mod.validate_state(self.state)

    def test_rejects_out_of_range_raw_hex_keycode(self):
        # A keycode is one wire byte. "1ff" (511) used to pass here and only
        # fail deep inside write_state()/remap() with an opaque error.
        self.state["buttons"]["default"]["a"] = "1ff"
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_accepts_unbound_button(self):
        self.state["buttons"]["default"]["a"] = None
        state_mod.validate_state(self.state)

    def test_rejects_out_of_range_percent(self):
        self.state["vibration"]["left_grip"] = 150
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_rejects_bad_report_rate(self):
        self.state["report_rate_hz"] = 750
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_report_rate_is_optional(self):
        # Additive field: older exported files predate it and must still load.
        del self.state["report_rate_hz"]
        state_mod.validate_state(self.state)

    def test_rejects_bad_resolution_bits(self):
        self.state["sticks"]["left"]["resolution_bits"] = 16
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_rejects_bad_dock_brightness(self):
        self.state["dock_led_brightness"] = 101
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)

    def test_rejects_incomplete_direction_bindings(self):
        self.state["sticks"]["left"]["advanced_mapping"]["direction_bindings"] = {
            "up": "w", "down": "s", "left": "a", "right": "d",  # no "ring"
        }
        with self.assertRaises(state_mod.StateError):
            state_mod.validate_state(self.state)


class LiveFixtureTest(unittest.TestCase):
    """Real read_state() output must survive validation and re-writing."""

    def test_live_reads_validate(self):
        for name, state in FIXTURES.items():
            with self.subTest(profile=name):
                state_mod.validate_state(state)

    def test_live_read_is_a_true_noop_against_itself(self):
        # Syncing a state back to the device it was just read from must
        # produce zero writes. This is the property the whole diff-sync
        # exists for, and the one users notice when it breaks.
        for name, state in FIXTURES.items():
            with self.subTest(profile=name):
                steps, skipped = state_mod._build_steps(state, baseline=state)
                self.assertEqual(steps, [], f"{name}: expected no writes, got {len(steps)}")
                self.assertGreater(skipped, 0)

    def test_paddle_native_keycodes_decode_with_their_confirmed_names(self):
        # Profile 3's factory-default paddle bindings (l4/r4/l5/r5) used to
        # decode as unnamed raw hex (0x11/0x12/0x1f/0x20) -- all four were
        # resolved and named (native_l4/native_r4/native_l5/native_r5)
        # 2026-07-30 via GameSir Nexus's own translation of a scratch-profile
        # write. Pinned against this real
        # hardware fixture so a table edit that breaks the naming is caught.
        state = FIXTURES["profile3_factory"]
        b = state["buttons"]["default"]
        self.assertEqual(b["l4"], "native_l4")
        self.assertEqual(b["r4"], "native_r4")
        self.assertEqual(b["l5"], "native_l5")
        self.assertEqual(b["r5"], "native_r5")

    def test_unnamed_keycodes_survive_a_round_trip(self):
        # Guards the bug class in general (a keycode with no name in
        # KNOWN_KEYCODES must not be dropped or turned into an unbind on its
        # way back out), independent
        # of any specific value -- l4/r4/l5/r5 no longer demonstrate this
        # (see the test above), so this uses a synthetic value guaranteed to
        # stay outside KNOWN_KEYCODES.
        import copy
        state = copy.deepcopy(FIXTURES["profile3_factory"])
        state["buttons"]["default"]["l4"] = "0xab"
        steps, _ = state_mod._build_steps(state, baseline=None)
        labels = [label for label, _fn in steps]
        self.assertTrue(any("0xab" in label for label in labels))
        self.assertFalse(any("unbind" in label and "l4" in label for label in labels))


class BuildStepsTest(unittest.TestCase):
    def setUp(self):
        self.state = state_mod.default_state_dict("test")
        self.state["controller_slot"] = 2

    def _labels(self, **kwargs):
        steps, _skipped = state_mod._build_steps(self.state, **kwargs)
        return [label for label, _fn in steps]

    def test_without_baseline_everything_is_written(self):
        steps, skipped = state_mod._build_steps(self.state, baseline=None)
        self.assertEqual(skipped, 0)
        self.assertGreater(len(steps), 20)

    def test_identical_baseline_produces_no_steps(self):
        steps, skipped = state_mod._build_steps(self.state, baseline=self.state)
        self.assertEqual(steps, [])
        self.assertGreater(skipped, 0)

    def test_only_the_changed_setting_is_written(self):
        import copy
        baseline = copy.deepcopy(self.state)
        # 75 rather than an arbitrary number: _vibration_steps() enforces
        # vibration.LEVELS on any value it's about to write, so an off-scale
        # stand-in would fail for that reason and stop testing diffing.
        self.state["vibration"]["left_grip"] = 75
        labels = self._labels(baseline=baseline)
        self.assertEqual(labels, ["Vibration: left_grip=75"])

    def test_a_change_in_every_category_produces_exactly_one_write(self):
        """Each category has its own step-builder with its own copy of the
        skip logic, so each needs its own change-detection test.

        Found by mutation testing: breaking the skip condition inside
        _stick_steps() alone was invisible to a suite that only ever changed
        a vibration level, because _vibration_steps() has a separate
        implementation. A diff bug that skips a genuinely-changed setting is
        the worst failure this code has -- the user's edit silently never
        reaches the device.
        """
        import copy
        cases = [
            (["sticks", "left", "deadzone", "initial"], 23, "Left Stick: deadzone.initial=23"),
            (["sticks", "right", "advanced_mapping", "sensitivity"], 77, "Right Stick: sensitivity=77"),
            (["triggers", "left", "deadzone", "max"], 44, "Left Trigger: deadzone.max=44"),
            (["triggers", "right", "hair_trigger_mode"], "fixed", "Right Trigger: hair_trigger_mode=fixed"),
            (["vibration", "right_grip"], 75, "Vibration: right_grip=75"),
            (["report_rate_hz"], 250, "Report rate=250Hz"),
            (["dpad_diagonal_lock"], True, "D-Pad Diagonal Lock=True"),
            (["swap_stick_dpad"], True, "Swap Left Stick and D-pad=True"),
            (["dock_led_brightness"], 25, "Dock LED Brightness=25%"),
            (["dock_auto_on_off"], False, "Dock Auto On/Off=False"),
        ]
        for path, new_value, expected_label in cases:
            with self.subTest(setting=".".join(str(p) for p in path)):
                state = state_mod.default_state_dict("test")
                state["controller_slot"] = 2
                baseline = copy.deepcopy(state)
                target = state
                for key in path[:-1]:
                    target = target[key]
                self.assertNotEqual(target[path[-1]], new_value, "test case must actually change something")
                target[path[-1]] = new_value
                steps, _skipped = state_mod._build_steps(state, baseline=baseline)
                labels = [label for label, _fn in steps]
                self.assertEqual(labels, [expected_label])

    def test_changed_button_produces_a_remap(self):
        import copy
        baseline = copy.deepcopy(self.state)
        baseline["buttons"]["default"]["a"] = "native_a"
        self.state["buttons"]["default"]["a"] = "f12"
        labels = self._labels(baseline=baseline)
        self.assertIn("Button a (default) -> f12", labels)

    def test_none_keycode_produces_an_unbind(self):
        import copy
        baseline = copy.deepcopy(self.state)
        baseline["buttons"]["default"]["a"] = "native_a"
        self.state["buttons"]["default"]["a"] = None
        self.assertIn("Button a (default): unbind", self._labels(baseline=baseline))

    def test_swap_stick_dpad_is_written_and_baseline_diffed(self):
        # Write-enabled 2026-07-28. Same baseline-diffing
        # contract as every other setting: unchanged from baseline -> skipped.
        import copy
        baseline = copy.deepcopy(self.state)
        self.state["swap_stick_dpad"] = True
        labels = self._labels(baseline=baseline)
        self.assertIn("Swap Left Stick and D-pad=True", labels)

        unchanged_labels = self._labels(baseline=self.state)
        self.assertFalse(any("swap" in label.lower() for label in unchanged_labels))

    def test_every_step_targets_the_declared_slot(self):
        from .fakes import FakeSession
        self.state["controller_slot"] = 3
        steps, _ = state_mod._build_steps(self.state, baseline=None)
        for label, write_fn in steps:
            sess = FakeSession(bytes(512))
            write_fn(sess)
            payload = sess.sent[-1][1]
            profile_byte = payload[1]
            if label.startswith("Dock"):
                # Dock settings are device-wide -- fixed 0x20, not a profile.
                self.assertEqual(profile_byte, 0x20, label)
            elif label.startswith("Button"):
                # Buttons pack profile+layer: 3 for default, 7 for shift.
                self.assertIn(profile_byte, (0x03, 0x07), label)
            else:
                self.assertEqual(profile_byte, 0x03, label)


class OffScaleVibrationTest(unittest.TestCase):
    """A vibration level that is in-range (0-100) but not one of
    vibration.LEVELS.

    The five-value restriction is a rule about what is worth *writing* --
    the firmware stores any 0-100 byte faithfully (write 47, read back 47,
    confirmed on hardware). Enforcing it in validate_state() instead broke
    every path that carries a *reading* rather than a declaration: a
    controller left at 47 by an older g7ctl could not be read at all, and
    snapshots this app itself exported could not be re-imported.

    These go through read_state()/load_state()/_build_steps() rather than
    calling the validator directly, because calling the validator directly
    is exactly what hid this: the suite's other vibration tests build steps
    without ever validating, and its validation tests only used values
    (150, 999) that are out of range under either rule.
    """

    def _blob_with(self, left_grip: int) -> bytes:
        from pyg7.constants import FULL_BLOB_LENGTH
        from pyg7.vibration import LEVEL_SETTING_IDS
        blob = bytearray(FULL_BLOB_LENGTH)
        blob[LEVEL_SETTING_IDS["left_grip"]] = left_grip
        return bytes(blob)

    def test_read_state_accepts_a_level_the_device_really_holds(self):
        from .fakes import FakeSession
        state = state_mod.read_state(FakeSession(self._blob_with(47)), slot=1)
        # Reported as-is, not snapped: rounding here would mean a later sync
        # silently wrote a different value than the one on the device.
        self.assertEqual(state["vibration"]["left_grip"], 47)

    def test_an_older_export_still_imports(self):
        import json
        import tempfile
        state = state_mod.default_state_dict("older export")
        state["vibration"]["left_grip"] = 60
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(state, fh)
            path = fh.name
        self.assertEqual(state_mod.load_state(path)["vibration"]["left_grip"], 60)

    def test_writing_an_off_scale_level_is_rejected_before_any_step_runs(self):
        state = state_mod.default_state_dict("test")
        state["vibration"]["left_grip"] = 47
        with self.assertRaises(state_mod.StateError):
            state_mod._build_steps(state, baseline=None)

    def test_an_untouched_off_scale_level_does_not_block_other_writes(self):
        """The case that matters after a read: the device is at 47, the user
        changed something else entirely. That sync has to work -- the 47 is
        skipped as already-matching and never reaches the write rule."""
        import copy
        state = state_mod.default_state_dict("test")
        state["vibration"]["left_grip"] = 47
        baseline = copy.deepcopy(state)
        state["report_rate_hz"] = 250
        labels = [label for label, _fn in state_mod._build_steps(state, baseline=baseline)[0]]
        self.assertEqual(labels, ["Report rate=250Hz"])


class SparseSubsectionTest(unittest.TestCase):
    """A state dict may legitimately omit an entire sub-section (not just
    hold it as `None`) to mean "leave this alone" -- validate_state() treats
    a missing section that way, and default_state_dict()'s own docstring
    calls the result "ready to hand-edit." _stick_steps()/_trigger_steps()
    used to crash with KeyError on exactly this shape: each write closure
    was built as `lambda sess, v=some_dict["key"]: ...`, and a default-
    argument expression is evaluated eagerly, at lambda-construction time --
    before the surrounding `_add()` helper got a chance to see the value was
    absent and skip the write. `_vibration_steps()` never had this bug (it
    resolves each value into a local first); `_stick_steps()`/
    `_trigger_steps()` now follow the same pattern."""

    def _state_missing(self, *paths):
        state = state_mod.default_state_dict("sparse")
        state["controller_slot"] = 2
        for path in paths:
            target = state
            for key in path[:-1]:
                target = target[key]
            del target[path[-1]]
        return state

    def test_missing_stick_curve_does_not_crash(self):
        state = self._state_missing(["sticks", "left", "curve"])
        state_mod.validate_state(state)  # must not raise -- missing section is valid
        state_mod._build_steps(state, baseline=None)  # must not raise

    def test_missing_stick_deadzone_and_advanced_mapping_does_not_crash(self):
        state = self._state_missing(
            ["sticks", "right", "deadzone"],
            ["sticks", "right", "anti_deadzone"],
            ["sticks", "right", "advanced_mapping"],
        )
        state_mod.validate_state(state)
        state_mod._build_steps(state, baseline=None)

    def test_missing_stick_trajectory_and_resolution_bits_does_not_crash(self):
        state = self._state_missing(
            ["sticks", "left", "trajectory"], ["sticks", "left", "resolution_bits"],
        )
        state_mod.validate_state(state)
        state_mod._build_steps(state, baseline=None)

    def test_missing_trigger_sections_do_not_crash(self):
        state = self._state_missing(
            ["triggers", "left", "hair_trigger_mode"],
            ["triggers", "left", "curve"],
            ["triggers", "right", "deadzone"],
            ["triggers", "right", "anti_deadzone"],
        )
        state_mod.validate_state(state)
        state_mod._build_steps(state, baseline=None)

    def test_present_settings_still_write_when_siblings_are_missing(self):
        # The fix must not turn "missing" into "everything is skipped" --
        # a setting that IS present alongside a missing sibling section
        # still has to produce a write.
        from .fakes import FakeSession
        state = self._state_missing(["sticks", "left", "curve"])
        state["sticks"]["left"]["resolution_bits"] = 10
        steps, _skipped = state_mod._build_steps(state, baseline=None)
        labels = [label for label, _fn in steps]
        self.assertIn("Left Stick: resolution_bits=10", labels)
        for _label, write_fn in steps:
            write_fn(FakeSession(bytes(512)))  # must not raise end to end


class SaveLoadTest(unittest.TestCase):
    def test_round_trip_through_disk(self):
        import tempfile
        state = state_mod.default_state_dict("round trip")
        state["buttons"]["default"]["a"] = "f12"
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            path = fh.name
        state_mod.save_state(path, state)
        loaded = state_mod.load_state(path)
        self.assertEqual(loaded["buttons"]["default"]["a"], "f12")

    def test_save_refuses_an_invalid_state(self):
        import tempfile
        state = state_mod.default_state_dict("bad")
        state["vibration"]["left_grip"] = 999
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            path = fh.name
        with self.assertRaises(state_mod.StateError):
            state_mod.save_state(path, state)


if __name__ == "__main__":
    unittest.main()
