"""Wire-format tests: every payload builder, byte for byte.

These are the highest-value tests in the project. The byte layouts here were
each established by USB capture and confirmed against real hardware, often
over multiple sessions -- but nothing except a person's memory was stopping a
refactor from quietly changing one. A wrong byte doesn't raise; it writes
something unintended to a device's persistent config.

Golden vectors are taken from the payloads recorded in PROTOCOL.md and the
original live USB captures, rather than from what the code currently
produces, so these tests can actually disagree with the implementation.
"""
import unittest
from unittest import mock

from pyg7 import (
    buttons,
    curves,
    dock_settings,
    dpad_options,
    motion,
    report_rate,
    sticks,
    triggers,
    vibration,
)
from pyg7.constants import CMD_WRITE, prefix_sticks, prefix_triggers_vibration
from pyg7.curves import curve_preset_payload
from pyg7.session import SHIFT_CATEGORY, profile_layer_byte

from .fakes import FakeSession, blob_with


class ProfileLayerByteTest(unittest.TestCase):
    """The Buttons category packs profile AND layer into one byte."""

    def test_confirmed_values(self):
        # The three combinations directly confirmed by capture.
        self.assertEqual(profile_layer_byte(1, shift=False), 0x01)
        self.assertEqual(profile_layer_byte(2, shift=False), 0x02)
        self.assertEqual(profile_layer_byte(1, shift=True), 0x05)

    def test_formula_extends_to_all_default_layer_slots(self):
        self.assertEqual(profile_layer_byte(3, shift=False), 0x03)
        self.assertEqual(profile_layer_byte(4, shift=False), 0x04)

    def test_shift_is_one_global_layer_for_every_profile(self):
        """The Shift layer is device-global: 0x05 for all four profiles.

        This assertion has now been wrong twice in opposite directions. It
        first read `profile_layer_byte(4, shift=True) == 0x08`, which the
        formula predicted and the firmware does not implement -- writing it
        modified Profile 1's Default layer. It was then changed to expect a
        refusal for Profiles 2-4, which was safe but still wrong: there is
        one Shift layer, shared, and asking for any profile's gets it.
        Confirmed on the device, in Nexus's own read pattern, and in Nexus's
        UI (a Shift binding set on Profile 1's tab shows on Profile 2's).
        """
        for profile in (1, 2, 3, 4):
            self.assertEqual(profile_layer_byte(profile, shift=True), SHIFT_CATEGORY)
        self.assertEqual(SHIFT_CATEGORY, 0x05)

    def test_default_layer_stays_profile_scoped(self):
        """Only the Shift axis is global -- the Default layer is per profile."""
        for profile in (1, 2, 3, 4):
            self.assertEqual(profile_layer_byte(profile, shift=False), profile)

    def test_rejects_out_of_range(self):
        for bad in (0, 5, -1):
            with self.assertRaises(ValueError):
                profile_layer_byte(bad)


class CategoryPrefixTest(unittest.TestCase):
    """Non-Buttons categories carry a plain profile number in byte 1.

    This is the distinction that went wrong for three days: the middle byte
    is the profile, and hardcoding it to 1 makes every write land in Profile 1
    no matter what the caller asked for.
    """

    def test_sticks_prefix_varies_with_profile(self):
        self.assertEqual(prefix_sticks(1), bytes([0x03, 0x01, 0x01]))
        self.assertEqual(prefix_sticks(2), bytes([0x03, 0x02, 0x01]))
        self.assertEqual(prefix_sticks(4), bytes([0x03, 0x04, 0x01]))

    def test_triggers_prefix_varies_with_profile(self):
        self.assertEqual(prefix_triggers_vibration(1), bytes([0x03, 0x01, 0x00]))
        self.assertEqual(prefix_triggers_vibration(3), bytes([0x03, 0x03, 0x00]))

    def test_prefixes_reject_out_of_range_profiles(self):
        for fn in (prefix_sticks, prefix_triggers_vibration):
            for bad in (0, 5):
                with self.assertRaises(ValueError):
                    fn(bad)

    def test_dock_prefix_is_fixed_not_profile_scoped(self):
        # Dock settings are device-wide; the middle byte is a constant 0x20,
        # NOT a profile. If this ever starts varying, the "global" claim in
        # dock_settings.py is wrong.
        from pyg7.constants import PREFIX_DOCK
        self.assertEqual(PREFIX_DOCK, bytes([0x03, 0x20, 0x01]))


class ButtonWriteTest(unittest.TestCase):
    def test_remap_payload_shape(self):
        sess = FakeSession()
        buttons.remap(sess, buttons.KNOWN_BUTTON_IDS["a"], 0x3E, profile=1, shift=False)
        # 03 [PROFILE+LAYER] 00 [BUTTON_ID...] 01 [KEYCODE], with the button
        # ID in its 2-byte allocate form (compact 0x7B -> 0x7A 0x02).
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0x7A, 0x02, 0x01, 0x3E]))

    def test_remap_uses_write_command(self):
        sess = FakeSession()
        buttons.remap(sess, buttons.KNOWN_BUTTON_IDS["a"], 0x3E)
        self.assertEqual(sess.sent[0][0], CMD_WRITE)

    def test_remap_targets_shift_layer_and_profile(self):
        sess = FakeSession()
        buttons.remap(sess, buttons.KNOWN_BUTTON_IDS["a"], 0x3E, profile=1, shift=True)
        self.assertEqual(sess.only_payload()[1], 0x05)  # profile 1 + shift

    def test_remap_to_shift_uses_0x05_whatever_profile_is_asked_for(self):
        # Used to assert 0x06 for profile 2 (a category that does not exist
        # and corrupts Profile 1). One Shift layer, one category.
        for profile in (1, 2, 3, 4):
            sess = FakeSession()
            buttons.remap(sess, buttons.KNOWN_BUTTON_IDS["a"], 0x3E, profile=profile, shift=True)
            self.assertEqual(sess.only_payload()[1], 0x05)

    def test_unbind_payload_differs_from_remap(self):
        sess = FakeSession()
        buttons.unbind(sess, buttons.KNOWN_BUTTON_IDS["l5"], profile=1)
        # A single trailing 0x00 instead of [0x01, keycode] -- confirmed on L5/R5.
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0xB9, 0x02, 0x00]))

    def test_allocate_form_is_always_used(self):
        # Hardware-confirmed: a compact-form write to a button not allocated
        # this session is silently ignored, so every write uses allocate form.
        self.assertEqual(buttons._to_allocate_form(bytes([0x7B])), bytes([0x7A, 0x02]))
        # Already-2-byte IDs pass through untouched.
        self.assertEqual(buttons._to_allocate_form(bytes([0xB9, 0x02])), bytes([0xB9, 0x02]))

    def test_allocate_form_rejects_bad_width(self):
        with self.assertRaises(ValueError):
            buttons._to_allocate_form(bytes([1, 2, 3]))

    def test_allocate_form_rejects_compact_id_zero_with_a_clear_message(self):
        # button_id[0] - 1 would be -1; bytes([-1, 0x02]) fails with an
        # opaque "bytes must be in range(0, 256)" -- this needs its own
        # explicit check for a message that says what's actually wrong.
        with self.assertRaisesRegex(ValueError, "0x00"):
            buttons._to_allocate_form(bytes([0x00]))

    def test_resolve_button_id_accepts_name_or_hex(self):
        self.assertEqual(buttons.resolve_button_id("A"), bytes([0x7B]))
        self.assertEqual(buttons.resolve_button_id("b902"), bytes([0xB9, 0x02]))

    def test_resolve_keycode_accepts_name_or_hex(self):
        self.assertEqual(buttons.resolve_keycode("f12"), 0x3E)
        self.assertEqual(buttons.resolve_keycode("3e"), 0x3E)

    def test_resolve_keycode_rejects_out_of_range_hex(self):
        # A keycode is one wire byte; "1ff" (511) used to sail through here
        # and only fail deep inside remap()'s bytes([0x01, keycode]) with a
        # generic, hard-to-place error.
        with self.assertRaises(ValueError):
            buttons.resolve_keycode("1ff")


class CurvePayloadTest(unittest.TestCase):
    def test_standard_preset_matches_captured_bytes(self):
        # Captured: 03 01 01 44 0A 00 64 00 00 28 29 80 80 D7 D6
        self.assertEqual(
            curve_preset_payload(0x44, "standard"),
            bytes.fromhex("440a00640000282980 80d7d6".replace(" ", "")),
        )

    def test_concave_and_s_curve_match_captured_bytes(self):
        # Captured: ... 44 0A 01 64 00 00 5E 17 B0 4F E8 A1
        self.assertEqual(curve_preset_payload(0x44, "concave"),
                         bytes.fromhex("440a016400005e17b04fe8a1"))
        # Captured: ... 44 0A 02 64 00 00 28 4C 80 80 D7 B2
        self.assertEqual(curve_preset_payload(0x44, "s_curve"),
                         bytes.fromhex("440a02640000284c8080d7b2"))

    def test_custom_uses_the_short_form(self):
        # Custom carries no curve data -- it's only a mode-select flag.
        self.assertEqual(curve_preset_payload(0x44, "custom"), bytes([0x44, 0x01, 0x03, 0x00]))

    def test_unknown_preset_rejected(self):
        with self.assertRaises(ValueError):
            curve_preset_payload(0x44, "logarithmic")


class ReportRateTest(unittest.TestCase):
    def test_each_rate_encodes_to_its_confirmed_value(self):
        # 03 [profile] 00 30 01 [VALUE]; VALUE 0/1/2 for 250/500/1000 Hz.
        for hz, expected in ((250, 0x00), (500, 0x01), (1000, 0x02)):
            sess = FakeSession()
            report_rate.set_value(sess, hz, profile=1)
            self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0x30, 0x01, expected]),
                             f"wrong payload for {hz}Hz")

    def test_rate_is_profile_scoped(self):
        sess = FakeSession()
        report_rate.set_value(sess, 500, profile=3)
        self.assertEqual(sess.only_payload()[1], 0x03)

    def test_unsupported_rate_rejected(self):
        with self.assertRaises(ValueError):
            report_rate.set_value(FakeSession(), 2000)


class VibrationTest(unittest.TestCase):
    def test_level_payload(self):
        sess = FakeSession()
        vibration.set_value(sess, "left_grip", 75, profile=1)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0x20, 0x01, 75]))

    def test_flags_are_bits_on_one_byte(self):
        # bit0 = Force, bit1 = Sync -- confirmed via the 01/00/02/00 toggle run.
        self.assertEqual(vibration.flags_byte(force=False, sync=False), 0x00)
        self.assertEqual(vibration.flags_byte(force=True, sync=False), 0x01)
        self.assertEqual(vibration.flags_byte(force=False, sync=True), 0x02)
        self.assertEqual(vibration.flags_byte(force=True, sync=True), 0x03)

    def test_flags_accept_the_cli_string_form(self):
        sess = FakeSession()
        vibration.set_value(sess, "left_trigger_flags", "on,off", profile=1)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0x24, 0x01, 0x01]))

    def test_out_of_range_level_rejected(self):
        with self.assertRaises(ValueError):
            vibration.set_value(FakeSession(), "left_grip", 101)

    def test_off_scale_level_rejected(self):
        # Storage itself is exact 0-100 (write 47, read back 47, confirmed
        # on hardware) -- but felt-testing found the motors don't produce
        # distinct output at every value, only at these five. A value
        # that's in-range but not one of them (unlike 101 above, which
        # fails for a different reason) must still be rejected.
        with self.assertRaises(ValueError):
            vibration.set_value(FakeSession(), "left_grip", 43)

    def test_every_level_is_accepted(self):
        for level in vibration.LEVELS:
            with self.subTest(level=level):
                sess = FakeSession()
                vibration.set_value(sess, "left_grip", level, profile=1)
                self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0x20, 0x01, level]))

    def test_unknown_setting_rejected(self):
        with self.assertRaises(ValueError):
            vibration.set_value(FakeSession(), "middle_grip", 50)


class StickWriteTest(unittest.TestCase):
    def test_right_side_shifts_setting_id_by_0x20(self):
        left, right = FakeSession(), FakeSession()
        sticks.set_value(left, "left", "invert_x", True, profile=1)
        sticks.set_value(right, "right", "invert_x", True, profile=1)
        self.assertEqual(left.only_payload()[3], 0x51)
        self.assertEqual(right.only_payload()[3], 0x51 + 0x20)

    def test_resolution_bits_uses_the_other_prefix(self):
        # The documented exception: resolution_bits rides the `03 [p] 00`
        # prefix, not Sticks' usual `03 [p] 01`, and stores 12 - bits.
        sess = FakeSession()
        sticks.set_value(sess, "left", "resolution_bits", 10, profile=1)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x00, 0x32, 0x01, 2]))

    def test_trajectory_encoding(self):
        for value, expected in (("raw", 0x01), ("circle", 0x00)):
            sess = FakeSession()
            sticks.set_value(sess, "left", "trajectory", value, profile=1)
            self.assertEqual(sess.only_payload()[-1], expected)

    def test_output_mode_encoding(self):
        sess = FakeSession()
        sticks.set_value(sess, "left", "output_mode", "mouse", profile=1)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x01, 0x55, 0x01, 0x04]))

    def test_direction_bindings_bulk_write(self):
        sess = FakeSession()
        sticks.set_value(sess, "left", "direction_bindings", "w,s,a,d,shift", profile=1)
        self.assertEqual(
            sess.only_payload(),
            bytes([0x03, 0x01, 0x01, 0x57, 0x05, 0x4F, 0x5D, 0x5C, 0x5E, 0x68]),
        )

    def test_direction_bindings_requires_five_zones(self):
        with self.assertRaises(ValueError):
            sticks.set_value(FakeSession(), "left", "direction_bindings", "w,s,a")

    def test_bad_side_rejected(self):
        with self.assertRaises(ValueError):
            sticks.set_value(FakeSession(), "middle", "invert_x", True)

    def test_unknown_setting_rejected(self):
        with self.assertRaises(ValueError):
            sticks.set_value(FakeSession(), "left", "invert_z", True)


class DeadzoneLiveSuffixTest(unittest.TestCase):
    """Deadzone writes must carry the device's CURRENT overlapping bytes.

    This is the regression that corrupted the Curve preset (Sticks) and the
    opposite side's trigger keycode (Triggers) when the suffix was a stale
    captured constant. The test pins the behaviour: whatever the device
    currently has in that span is what gets sent back.
    """

    def test_stick_deadzone_suffix_comes_from_the_live_read(self):
        # Distinctive live bytes so a hardcoded suffix would be obvious.
        blob = bytes(range(256)) * 4
        sess = FakeSession(blob)
        sticks.set_value(sess, "left", "deadzone_initial", 5, profile=1)
        payload = sess.only_payload()
        storage_offset = 0x3F + sticks.STORAGE_BASE
        suffix = payload[6:]
        self.assertEqual(suffix, blob[storage_offset + 1:storage_offset + 1 + len(suffix)])
        self.assertEqual(payload[5], 5)  # the value byte itself

    def test_trigger_deadzone_reads_its_own_side(self):
        blob = bytes(range(256)) * 4
        left, right = FakeSession(blob), FakeSession(blob)
        triggers.set_value(left, "left", "deadzone_initial", 5, profile=1)
        triggers.set_value(right, "right", "deadzone_initial", 5, profile=1)
        # Right must read from its own +0x1C-shifted address, not Left's.
        self.assertNotEqual(left.only_payload()[6:], right.only_payload()[6:])
        self.assertEqual(right.reads[0][1], 0xCF + 0x1C + triggers.STORAGE_BASE + 1)


class TriggerWriteTest(unittest.TestCase):
    def test_right_side_shifts_setting_id_by_0x1c(self):
        # Deliberately different from Sticks' +0x20 -- confirmed per-category.
        left, right = FakeSession(), FakeSession()
        triggers.set_value(left, "left", "hair_trigger_mode", "off", profile=1)
        triggers.set_value(right, "right", "hair_trigger_mode", "off", profile=1)
        self.assertEqual(right.only_payload()[3] - left.only_payload()[3], 0x1C)

    def test_hair_trigger_modes(self):
        for mode, expected in (("off", 0x00), ("adaptive", 0x81), ("fixed", 0x82)):
            sess = FakeSession()
            triggers.set_value(sess, "left", "hair_trigger_mode", mode, profile=1)
            self.assertEqual(sess.only_payload()[-1], expected)

    def test_unknown_hair_trigger_mode_rejected(self):
        with self.assertRaises(ValueError):
            triggers.set_value(FakeSession(), "left", "hair_trigger_mode", "hairy")


class MotionWriteTest(unittest.TestCase):
    """See pyg7/motion.py -- every address here traces back to a live
    capture (test72-test77), not to the +0x22 stride alone; the two
    fields that break the stride (invert_yaw's Tilt offset, invert_roll's
    Aim-only existence) are exercised explicitly below."""

    def test_tilt_shifts_setting_id_by_0x22(self):
        aim, tilt = FakeSession(), FakeSession()
        motion.set_value(aim, "aim", "invert_y", True, profile=1)
        motion.set_value(tilt, "tilt", "invert_y", True, profile=1)
        self.assertEqual(tilt.only_payload()[3] - aim.only_payload()[3], 0x22)

    def test_invert_yaw_tilt_offset_is_0x20_not_0x22(self):
        # The one off-stride field in the category -- see motion.py's
        # module docstring. Pinned explicitly so a future "helpfully"
        # generalises the stride" refactor breaks a test, not hardware.
        aim, tilt = FakeSession(), FakeSession()
        motion.set_value(aim, "aim", "invert_yaw", True, profile=1)
        motion.set_value(tilt, "tilt", "invert_yaw", True, profile=1)
        self.assertEqual(tilt.only_payload()[3] - aim.only_payload()[3], 0x20)

    def test_invert_roll_is_aim_only(self):
        motion.set_value(FakeSession(), "aim", "invert_roll", True, profile=1)  # must not raise
        with self.assertRaises(ValueError):
            motion.set_value(FakeSession(), "tilt", "invert_roll", True, profile=1)

    def test_output_encoding_matches_sticks(self):
        # Same OUTPUT_MODES enum as sticks.py, reused not duplicated --
        # see motion.py's import.
        sess = FakeSession()
        motion.set_value(sess, "aim", "output", "directional", profile=1)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x01, 0xB7, 0x01, 0x03]))

    def test_x_axis_output_mode_encoding(self):
        for value, expected in (("yaw", 0x01), ("yaw_roll", 0x03)):
            sess = FakeSession()
            motion.set_value(sess, "aim", "x_axis_output_mode", value, profile=1)
            self.assertEqual(sess.only_payload()[-1], expected)

    def test_unknown_x_axis_output_mode_rejected(self):
        with self.assertRaises(ValueError):
            motion.set_value(FakeSession(), "aim", "x_axis_output_mode", "pitch", profile=1)

    def test_activate_method_is_bounded_0_to_3(self):
        motion.set_value(FakeSession(), "aim", "activate_method", 3, profile=1)  # must not raise
        with self.assertRaises(ValueError):
            motion.set_value(FakeSession(), "aim", "activate_method", 4, profile=1)

    def test_activate_button_accepts_a_keycode_name(self):
        sess = FakeSession()
        motion.set_value(sess, "aim", "activate_button", "native_l5", profile=1)
        self.assertEqual(sess.only_payload()[-1], 0x1F)

    def test_direction_bindings_are_four_independent_writes_not_bulk(self):
        # Unlike sticks.py's direction_bindings (one 5-byte bulk write),
        # Motion's four directions are four separate single-byte settings --
        # confirmed on the wire, one write per direction, no "ring" zone.
        for setting, addr in (("direction_up", 0xB9), ("direction_down", 0xBA),
                               ("direction_left", 0xBB), ("direction_right", 0xBC)):
            sess = FakeSession()
            motion.set_value(sess, "aim", setting, "native_dpad_up", profile=1)
            self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x01, addr, 0x01, 0x01]))

    def test_curve_preset_payloads_match_the_captured_bytes(self):
        # Motion's own shape data -- numerically different from sticks'/
        # triggers' (see motion.py's _CURVE_SHAPE_DATA), same structure.
        cases = {
            "standard": bytes.fromhex("0a0064000028288081d7d7"),
            "concave": bytes.fromhex("0a016400005e17ae4fe8a2"),
            "s_curve": bytes.fromhex("0a0264000028 4c 80 81 d7 b3".replace(" ", "")),
        }
        for preset, expected_tail in cases.items():
            with self.subTest(preset=preset):
                sess = FakeSession()
                motion.set_value(sess, "aim", "curve", preset, profile=1)
                self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x01, 0xA5]) + expected_tail)

    def test_curve_custom_is_short_form_no_trailing_byte(self):
        # Motion's own measured Custom write is 2 payload bytes (LEN=1,
        # index=3) -- not sticks.py's 3-byte custom form with a trailing
        # 0x00 (see motion.py's module docstring for why they differ).
        sess = FakeSession()
        motion.set_value(sess, "aim", "curve", "custom", profile=1)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x01, 0x01, 0xA5, 0x01, 0x03]))

    def test_unknown_curve_preset_rejected(self):
        with self.assertRaises(ValueError):
            motion.set_value(FakeSession(), "aim", "curve", "banana", profile=1)

    def test_deadzone_initial_suffix_comes_from_the_live_read(self):
        # Same regression class as DeadzoneLiveSuffixTest below -- pinned
        # separately here because motion.py computes its own marker/suffix
        # constants from its own captures, not sticks.py's.
        blob = bytes(range(256)) * 4
        sess = FakeSession(blob)
        motion.set_value(sess, "aim", "deadzone_initial", 17, profile=1)
        payload = sess.only_payload()
        storage_offset = 0xA0 + motion.STORAGE_BASE
        suffix = payload[6:]
        self.assertEqual(suffix, blob[storage_offset + 1:storage_offset + 1 + len(suffix)])
        self.assertEqual(payload[5], 17)

    def test_bad_side_rejected(self):
        with self.assertRaises(ValueError):
            motion.set_value(FakeSession(), "middle", "invert_y", True)

    def test_unknown_setting_rejected(self):
        with self.assertRaises(ValueError):
            motion.set_value(FakeSession(), "aim", "invert_z", True)


class DpadOptionsTest(unittest.TestCase):
    def test_diagonal_lock_payload(self):
        sess = FakeSession()
        dpad_options.set_diagonal_lock(sess, True, profile=2)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x02, 0x00, 0x2D, 0x01, 0x01]))

    def test_diagonal_lock_accepts_the_cli_off_string(self):
        # Regression: 0x01 if enabled else 0x00 on a raw (non-bool) `enabled`
        # treats the non-empty string "off" as truthy and silently writes ON.
        # Must route through values.boolean() like every other flag setting.
        sess = FakeSession()
        dpad_options.set_diagonal_lock(sess, "off", profile=1)
        self.assertEqual(sess.only_payload()[-1], 0x00)

    def test_swap_stick_dpad_accepts_the_cli_off_string(self):
        sess = FakeSession()
        dpad_options.set_swap_stick_dpad(sess, "off", profile=1)
        payload = sess.only_payload()
        self.assertEqual(payload[5], 0x00)   # val_2B
        self.assertEqual(payload[6], 0x00)   # val_2C

    def test_swap_stick_dpad_matches_the_captured_write(self):
        # Golden vector: decoded from the live USB capture of a real
        # "Swap Left Stick and D-pad" toggle, 2026-07-28.
        # When the live suffix span (offset 0x2D, 53 bytes) matches what was
        # actually on the device during that capture, the payload this
        # produces must match the captured packet byte for byte.
        suffix = bytes.fromhex(
            "0000000200000000000000000000000000000000000101000000000001020000000000010300000000000104000000000001050000")
        self.assertEqual(len(suffix), 53)
        blob = bytearray(512)
        blob[0x2D:0x2D + len(suffix)] = suffix
        sess = FakeSession(bytes(blob))
        dpad_options.set_swap_stick_dpad(sess, True, profile=1)
        expected = bytes.fromhex(
            "0301002b3701010000000200000000000000000000000000000000000101000000000001020000000000010300000000000104000000000001050000")
        self.assertEqual(sess.only_payload(), expected)

    def test_swap_stick_dpad_off_writes_zero(self):
        sess = FakeSession()
        dpad_options.set_swap_stick_dpad(sess, False, profile=1)
        payload = sess.only_payload()
        self.assertEqual(payload[3], 0x2B)   # SETTING_ID
        self.assertEqual(payload[4], 0x37)   # length byte, not a marker -- see module docstring
        self.assertEqual(payload[5], 0x00)   # val_2B
        self.assertEqual(payload[6], 0x00)   # val_2C

    def test_swap_stick_dpad_suffix_comes_from_the_live_read(self):
        # Same regression class DeadzoneLiveSuffixTest pins for Sticks/
        # Triggers: a hardcoded suffix would silently stomp whatever else
        # lives in this span (D-Pad Diagonal Lock's own byte at 0x2D sits
        # right inside it).
        blob = bytes(range(256)) * 4
        sess = FakeSession(blob)
        dpad_options.set_swap_stick_dpad(sess, True, profile=1)
        payload = sess.only_payload()
        suffix = payload[7:]
        self.assertEqual(len(suffix), 53)
        self.assertEqual(suffix, blob[0x2D:0x2D + 53])

    def test_set_value_dispatches_to_the_same_payloads(self):
        # set_value() is a name-based front door onto the same two
        # functions above, matching sticks.py/triggers.py/vibration.py/
        # report_rate.py's shape -- not a separate code path.
        direct = FakeSession()
        dpad_options.set_diagonal_lock(direct, True, profile=2)
        via_dispatch = FakeSession()
        dpad_options.set_value(via_dispatch, "diagonal_lock", True, profile=2)
        self.assertEqual(direct.only_payload(), via_dispatch.only_payload())

    def test_set_value_rejects_unknown_setting(self):
        with self.assertRaises(ValueError):
            dpad_options.set_value(FakeSession(), "not_a_real_setting", True)


class DockSettingsTest(unittest.TestCase):
    def test_brightness_payload_is_a_literal_percent(self):
        sess = FakeSession()
        dock_settings.set_brightness(sess, 75)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x20, 0x01, 0xF9, 0x01, 75]))

    def test_auto_on_off_payload(self):
        sess = FakeSession()
        dock_settings.set_auto_on_off(sess, False)
        self.assertEqual(sess.only_payload(), bytes([0x03, 0x20, 0x01, 0xF6, 0x01, 0x00]))

    def test_auto_on_off_accepts_the_cli_off_string(self):
        # Same regression class as DpadOptionsTest's -- see that test's comment.
        sess = FakeSession()
        dock_settings.set_auto_on_off(sess, "off")
        self.assertEqual(sess.only_payload()[-1], 0x00)

    def test_brightness_range_enforced(self):
        with self.assertRaises(ValueError):
            dock_settings.set_brightness(FakeSession(), 150)

    def test_set_value_dispatches_to_the_same_payloads(self):
        # Same reasoning as DpadOptionsTest's version of this test.
        direct = FakeSession()
        dock_settings.set_brightness(direct, 75)
        via_dispatch = FakeSession()
        dock_settings.set_value(via_dispatch, "brightness", 75)
        self.assertEqual(direct.only_payload(), via_dispatch.only_payload())

    def test_set_value_rejects_unknown_setting(self):
        with self.assertRaises(ValueError):
            dock_settings.set_value(FakeSession(), "not_a_real_setting", True)


if __name__ == "__main__":
    unittest.main()


@mock.patch.object(curves, "CURVE_POINT_WRITE_INTERVAL", 0)
class CurvePointsTest(unittest.TestCase):
    """The three interior control points of a custom curve.

    Addresses are the curve SETTING_ID + 4/6/8, all six hardware-confirmed
    2026-08-08 (left stick, right stick, both triggers), and the whole
    sequence was verified end to end on Profile 4: write, read back, diff --
    exactly the intended bytes changed and nothing else.
    """

    POINTS = [(0x30, 0x40), (0x80, 0x90), (0xC0, 0xD0)]

    def test_parse_accepts_the_cli_string_and_the_json_shapes(self):
        expected = [(1, 2), (3, 4), (5, 6)]
        self.assertEqual(curves.parse_points("1,2,3,4,5,6"), expected)
        self.assertEqual(curves.parse_points([[1, 2], [3, 4], [5, 6]]), expected)
        self.assertEqual(curves.parse_points([1, 2, 3, 4, 5, 6]), expected)

    def test_parse_rejects_wrong_count_and_out_of_range(self):
        with self.assertRaises(ValueError):
            curves.parse_points("1,2,3,4")
        with self.assertRaises(ValueError):
            curves.parse_points([[1, 2], [3, 4], [5, 6], [7, 8]])
        # 0-255, NOT the 0-100 the deadzone endpoints use -- different units
        # on the same axis, which is exactly the mistake worth catching.
        with self.assertRaises(ValueError):
            curves.parse_points("0,0,0,0,0,256")
        curves.parse_points("0,0,0,0,255,255")  # 255 is fine

    def _poke(self, sess, prefix, sid):
        """The per-point form: three 2-byte writes. Not the default any more
        (see the whole-block tests below), but it is what editing a single
        point on an already-configured curve looks like on the wire, and it
        is where the per-point addresses are pinned."""
        return curves.write_curve_points(sess, prefix, sid, self.POINTS,
                                         whole_block=False)

    def test_left_stick_points_land_at_48_4a_4c(self):
        sess = FakeSession()
        self._poke(sess, prefix_sticks(1), 0x44)
        self.assertEqual([p.hex() for p in sess.payloads],
                         ["03010148023040", "0301014a028090", "0301014c02c0d0"])

    def test_right_stick_points_take_the_0x20_side_offset(self):
        sess = FakeSession()
        self._poke(sess, prefix_sticks(1), 0x44 + 0x20)
        self.assertEqual([p[3] for p in sess.payloads], [0x68, 0x6A, 0x6C])

    def test_trigger_points_use_the_page_0_prefix_and_0x1c_offset(self):
        left = FakeSession()
        self._poke(left, prefix_triggers_vibration(1), 0xDC)
        self.assertEqual([p[3] for p in left.payloads], [0xE0, 0xE2, 0xE4])
        # triggers live on page 0 -- prefix 03 [profile] 00, not ...01
        self.assertTrue(all(p[2] == 0x00 for p in left.payloads))

    def test_right_trigger_third_point_carries_into_the_next_page(self):
        """Its address is 0x100 -- past the one-byte SETTING_ID field -- so
        the prefix's page byte increments and the offset wraps to 0x00.

        Confirmed on the wire 2026-08-08 (test62): dragging that point in
        Nexus emitted `03 01 01 00 02 e4 82`. Note a *trigger* write then
        carries the same prefix bytes a *stick* write uses, which is the
        clearest evidence that the third prefix byte is a page number rather
        than a category tag.
        """
        right = FakeSession()
        curves.write_curve_points(right, prefix_triggers_vibration(1), 0xDC + 0x1C,
                                  [(1, 2), (3, 4), (0xE4, 0x82)], whole_block=False)
        p1, p2, p3 = right.payloads
        # first two stay on page 0 at 0xFC / 0xFE
        self.assertEqual(p1[2], 0x00)
        self.assertEqual((p1[3], p2[3]), (0xFC, 0xFE))
        # the third flips the page byte and wraps the offset
        self.assertEqual(p3[2], 0x01, "page byte should increment")
        self.assertEqual(p3[3], 0x00, "offset should wrap to 0x00")
        self.assertEqual(p3.hex(), "0301010002e482", "the exact captured bytes")

    def test_profile_targeting_carries_through(self):
        sess = FakeSession()
        sticks.set_value(sess, "left", "curve_points", self.POINTS, profile=4)
        self.assertTrue(all(p[1] == 4 for p in sess.payloads))

    def test_each_point_is_a_two_byte_write(self):
        sess = FakeSession()
        self._poke(sess, prefix_sticks(1), 0x44)
        for payload in sess.payloads:
            self.assertEqual(payload[4], 0x02, "LEN byte should be 2 (x, y)")
            self.assertEqual(len(payload), 7)

    def test_set_value_writes_the_whole_block_including_scale(self):
        """A points-only write leaves the block half-initialised.

        The scale byte marks a block as written, and a profile whose curve
        was never configured has it at 0x00 -- so points-only writes landed
        correctly and then decoded as None, the tool writing a curve it
        could not read back (confirmed on hardware, Profile 4). set_value
        sends the whole 10-byte block, the same shape the presets use.
        """
        sess = FakeSession()
        sticks.set_value(sess, "left", "curve_points", self.POINTS, profile=4)
        payload = sess.only_payload()
        self.assertEqual(payload.hex(), "030401440a03640000304080 90c0d0".replace(" ", ""))
        self.assertEqual(payload[4], 0x0A, "LEN covers index+scale+origin+3 points")
        self.assertEqual(payload[5], 0x03, "preset index -> Custom")
        self.assertEqual(payload[6], 0x64, "scale marks the block as configured")

    def test_the_written_block_reads_back_as_configured(self):
        """The round trip the hardware test caught: what set_value writes
        must decode to the points that went in, not to None."""
        sess = FakeSession()
        sticks.set_value(sess, "left", "curve_points", self.POINTS, profile=1)
        payload = sess.only_payload()
        blob = bytearray(512)
        blob[0x144:0x144 + len(payload) - 5] = payload[5:]
        decoded = sticks.decode_settings(bytes(blob), "left")["curve"]
        self.assertEqual(decoded["preset"], "custom")
        self.assertEqual(decoded["points"], [list(p) for p in self.POINTS])

    def test_decode_reads_the_points_back_out_of_a_blob(self):
        # left stick curve block at 0x144: [idx][scale][origin][P1][P2][P3]
        blob = blob_with({
            0x144: 0x03, 0x145: 0x64,
            0x148: 0x30, 0x149: 0x40,
            0x14A: 0x80, 0x14B: 0x90,
            0x14C: 0xC0, 0x14D: 0xD0,
        })
        decoded = sticks.decode_settings(blob, "left")
        self.assertEqual(decoded["curve"]["preset"], "custom")
        self.assertEqual(decoded["curve"]["points"], [[0x30, 0x40], [0x80, 0x90], [0xC0, 0xD0]])

    def test_decode_survives_a_blob_too_short_to_hold_them(self):
        self.assertIsNone(curves.decode_curve_points(b"\x00" * 8, 0x144))


class ContinuousTriggerTest(unittest.TestCase):
    """Per-button Continuous Trigger -- byte 4 of the button's 7-byte record.

    See PROTOCOL.md "Continuous Trigger". The two addresses
    pinned here are the two `test61` actually captured; everything else is
    generated from the same table the binding writes already use, which is
    exactly why those two matter.
    """

    def setUp(self):
        self.sess = FakeSession()

    def test_captured_addresses_for_a_and_y(self):
        # test61: A's record is 0x7A and its toggle wrote 0x7E; Y's record is
        # 0x8F and its toggle wrote 0x93. If the slot table ever shifts, this
        # is the test that should fail.
        self.assertEqual(buttons.continuous_trigger_offset("a"), 0x7E)
        self.assertEqual(buttons.continuous_trigger_offset("y"), 0x93)

    def test_every_slot_lands_at_record_plus_four(self):
        for idx, slot in enumerate(buttons.BUTTON_TABLE_SLOTS):
            if slot is None:
                continue
            record = buttons.BUTTON_TABLE_OFFSET + idx * buttons.BUTTON_TABLE_SLOT_SIZE
            self.assertEqual(buttons.continuous_trigger_offset(slot), record + 4)

    def test_payload_shape(self):
        buttons.set_continuous_trigger(self.sess, "a", True, profile=1)
        self.assertEqual(self.sess.sent[-1][1].hex(), "030100" "7e" "01" "01")

    def test_off_writes_zero(self):
        buttons.set_continuous_trigger(self.sess, "a", False, profile=1)
        self.assertEqual(self.sess.sent[-1][1].hex(), "030100" "7e" "01" "00")

    def test_profile_is_targeted(self):
        buttons.set_continuous_trigger(self.sess, "y", True, profile=3)
        self.assertEqual(self.sess.sent[-1][1].hex(), "030300" "93" "01" "01")

    def test_triggers_are_rejected_not_guessed(self):
        # LT/RT have no button-table record at all, so there is no "+4 within
        # the record" to compute. Silently inventing an address would write
        # into the Triggers category's own data.
        for slot in ("lt", "rt"):
            with self.assertRaises(ValueError):
                buttons.continuous_trigger_offset(slot)

    def test_reserved_xbox_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            buttons.continuous_trigger_offset(None)

    def test_unknown_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            buttons.continuous_trigger_offset("nope")

    def test_decode_round_trips_against_the_write_address(self):
        blob = bytearray(0x100)
        blob[buttons.continuous_trigger_offset("b")] = 0x01
        decoded = buttons.decode_continuous_triggers(bytes(blob))
        self.assertTrue(decoded["b"])
        self.assertFalse(decoded["a"])

    def test_decode_includes_unbound_slots(self):
        # Nexus shows the checkbox on every button, so byte 4 is live in all
        # 20 records -- a slot being unbound must not drop it from the decode.
        decoded = buttons.decode_continuous_triggers(bytes(0x100))
        named = [s for s in buttons.BUTTON_TABLE_SLOTS if s]
        self.assertEqual(sorted(decoded), sorted(named))
