"""Blob-decoding tests: the read side of the protocol.

Each decoder turns a config blob read off the device into a state dict. The
storage offsets they use were mapped by write+read-diff against real
hardware; these tests place a known byte at a documented offset and assert
the decoder finds it there. If an offset constant is edited, one of these
fails rather than the GUI quietly displaying the wrong setting.
"""
import unittest

from pyg7 import buttons, dock_settings, dpad_options, motion, report_rate, sticks, triggers, vibration

from .fakes import UNBOUND_RECORD, blob_with, button_record


class ButtonTableDecodeTest(unittest.TestCase):
    def _blob_with_slots(self, keycodes_by_slot: dict) -> bytes:
        """Lay out a full button table at BUTTON_TABLE_OFFSET."""
        buf = bytearray(512)
        offset = buttons.BUTTON_TABLE_OFFSET
        for slot in buttons.BUTTON_TABLE_SLOTS:
            record = UNBOUND_RECORD
            if slot is not None and slot in keycodes_by_slot:
                record = button_record(keycodes_by_slot[slot])
            buf[offset:offset + buttons.BUTTON_TABLE_SLOT_SIZE] = record
            offset += buttons.BUTTON_TABLE_SLOT_SIZE
        return bytes(buf)

    def test_decodes_named_keycodes_per_slot(self):
        blob = self._blob_with_slots({"a": 0x09, "share": 0x3D, "l5": 0x92})
        decoded = buttons.decode_button_table(blob)
        self.assertEqual(decoded["a"], "native_a")
        self.assertEqual(decoded["share"], "f11")
        self.assertEqual(decoded["l5"], "numpad7")

    def test_slot_without_the_0x01_marker_is_unbound(self):
        blob = self._blob_with_slots({"a": 0x09})
        self.assertIsNone(buttons.decode_button_table(blob)["b"])

    def test_guide_slot_is_reserved_and_never_reported(self):
        # BUTTON_TABLE_SLOTS carries a None placeholder for the
        # non-remappable Xbox/Guide button; it must not leak into the result.
        decoded = buttons.decode_button_table(self._blob_with_slots({}))
        self.assertNotIn(None, decoded)

    def test_all_21_buttons_are_covered(self):
        # Regression guard for the bug where D-pad and LT/RT were missing
        # from read coverage and got silently deleted on "Read from Device".
        decoded = buttons.decode_button_table(self._blob_with_slots({}))
        expected = set(buttons.KNOWN_BUTTON_IDS)
        self.assertEqual(set(decoded), expected, "read coverage no longer matches KNOWN_BUTTON_IDS")
        self.assertEqual(len(expected), 21)

    def test_triggers_decode_from_their_own_flat_offsets(self):
        # LT/RT don't live in the uniform table -- they're single raw bytes
        # sitting inside the Triggers deadzone data.
        blob = bytearray(self._blob_with_slots({}))
        blob[buttons.TRIGGER_BUTTON_OFFSETS["lt"]] = 0x13
        blob[buttons.TRIGGER_BUTTON_OFFSETS["rt"]] = 0x14
        decoded = buttons.decode_button_table(bytes(blob))
        self.assertEqual(decoded["lt"], "native_lt")
        self.assertEqual(decoded["rt"], "native_rt")

    def test_unknown_keycode_falls_back_to_raw_hex(self):
        # Real hardware can return a keycode with no name in KNOWN_KEYCODES
        # (this used to be true of 0x11/0x12/0x1f/0x20 -- the paddles'
        # factory defaults -- until they were resolved and named 2026-07-30,
        # see PROTOCOL.md "Keycodes"). The decoder must surface an
        # unnamed value as raw hex, not drop it -- 0xab is guaranteed to
        # stay outside the table.
        self.assertEqual(buttons.decode_keycode(0xAB), "0xab")
        self.assertEqual(buttons.decode_keycode(0x09), "native_a")

    def test_paddle_native_keycodes_have_confirmed_names(self):
        # Resolved 2026-07-30 via GameSir Nexus's own translation of a
        # scratch-profile write -- see PROTOCOL.md "Keycodes".
        self.assertEqual(buttons.decode_keycode(0x0D), "native_home")
        self.assertEqual(buttons.decode_keycode(0x11), "native_l4")
        self.assertEqual(buttons.decode_keycode(0x12), "native_r4")
        self.assertEqual(buttons.decode_keycode(0x1F), "native_l5")
        self.assertEqual(buttons.decode_keycode(0x20), "native_r5")


class ReportRateDecodeTest(unittest.TestCase):
    def test_decodes_each_rate(self):
        for raw, expected in ((0x00, 250), (0x01, 500), (0x02, 1000)):
            blob = blob_with({report_rate.SETTING_ID: raw})
            self.assertEqual(report_rate.decode_settings(blob)["report_rate_hz"], expected)

    def test_unknown_value_decodes_to_none(self):
        blob = blob_with({report_rate.SETTING_ID: 0x7F})
        self.assertIsNone(report_rate.decode_settings(blob)["report_rate_hz"])


class VibrationDecodeTest(unittest.TestCase):
    def test_levels_decode_from_setting_ids_directly(self):
        blob = blob_with({0x20: 10, 0x21: 20, 0x22: 30, 0x23: 40})
        decoded = vibration.decode_settings(blob)
        self.assertEqual(decoded["left_grip"], 10)
        self.assertEqual(decoded["right_grip"], 20)
        self.assertEqual(decoded["left_trigger"], 30)
        self.assertEqual(decoded["right_trigger"], 40)

    def test_flags_split_into_force_and_sync_bits(self):
        blob = blob_with({0x24: 0x03, 0x25: 0x02})
        decoded = vibration.decode_settings(blob)
        self.assertTrue(decoded["left_trigger_force"])
        self.assertTrue(decoded["left_trigger_sync"])
        self.assertFalse(decoded["right_trigger_force"])
        self.assertTrue(decoded["right_trigger_sync"])

    def test_decode_is_the_inverse_of_flags_byte(self):
        for force in (False, True):
            for sync in (False, True):
                blob = blob_with({0x24: vibration.flags_byte(force, sync)})
                decoded = vibration.decode_settings(blob)
                self.assertEqual(decoded["left_trigger_force"], force)
                self.assertEqual(decoded["left_trigger_sync"], sync)


class StickDecodeTest(unittest.TestCase):
    def test_settings_decode_from_setting_id_plus_storage_base(self):
        base = sticks.STORAGE_BASE
        blob = blob_with({
            base + 0x3D: 0x01,   # trajectory -> raw
            base + 0x3F: 7,      # deadzone initial
            base + 0x40: 90,     # deadzone max
            base + 0x51: 0x01,   # invert_x
            base + 0x53: 65,     # sensitivity
        })
        decoded = sticks.decode_settings(blob, "left")
        self.assertEqual(decoded["trajectory"], "raw")
        self.assertEqual(decoded["deadzone"], {"initial": 7, "max": 90})
        self.assertTrue(decoded["advanced_mapping"]["invert_x"])
        self.assertEqual(decoded["advanced_mapping"]["sensitivity"], 65)

    def test_right_side_reads_the_shifted_offsets(self):
        base = sticks.STORAGE_BASE
        blob = blob_with({base + 0x3F: 11, base + 0x3F + 0x20: 22})
        self.assertEqual(sticks.decode_settings(blob, "left")["deadzone"]["initial"], 11)
        self.assertEqual(sticks.decode_settings(blob, "right")["deadzone"]["initial"], 22)

    def test_resolution_bits_reads_from_the_other_address_space(self):
        # It rides the `03 [p] 00` prefix, so no STORAGE_BASE, and stores 12 - bits.
        blob = blob_with({0x32: 2})
        self.assertEqual(sticks.decode_settings(blob, "left")["resolution_bits"], 10)

    def test_direction_bindings_treat_0xff_as_unbound(self):
        base = sticks.STORAGE_BASE + 0x57
        blob = blob_with({base: 0x4F, base + 1: 0xFF, base + 2: 0x5C,
                          base + 3: 0x5E, base + 4: 0xFF})
        db = sticks.decode_settings(blob, "left")["advanced_mapping"]["direction_bindings"]
        self.assertEqual(db["up"], "w")
        self.assertIsNone(db["down"])
        self.assertIsNone(db["ring"])

    def test_curve_custom_index_decodes(self):
        # 0x03 is Custom -- it has no CURVE_PRESET_INDEX entry because it
        # carries no write data, but it still reads back.
        blob = blob_with({sticks.STORAGE_BASE + 0x44: 0x03})
        self.assertEqual(sticks.decode_settings(blob, "left")["curve"]["preset"], "custom")

    def test_short_blob_yields_none_rather_than_raising(self):
        decoded = sticks.decode_settings(b"\x00" * 8, "left")
        self.assertIsNone(decoded["deadzone"]["initial"])


class MotionDecodeTest(unittest.TestCase):
    def test_settings_decode_from_setting_id_plus_storage_base(self):
        base = motion.STORAGE_BASE
        blob = blob_with({
            base + 0x9E: 0x03,   # x_axis_output_mode -> yaw_roll
            base + 0xA0: 17,     # deadzone initial
            base + 0xA1: 93,     # deadzone max
            base + 0xB3: 0x01,   # invert_y
            base + 0xB5: 42,     # sensitivity_scale
        })
        decoded = motion.decode_settings(blob, "aim")
        self.assertEqual(decoded["x_axis_output_mode"], "yaw_roll")
        self.assertEqual(decoded["deadzone"], {"initial": 17, "max": 93})
        self.assertTrue(decoded["invert_y"])
        self.assertEqual(decoded["sensitivity_scale"], 42)

    def test_tilt_reads_the_0x22_shifted_offsets(self):
        base = motion.STORAGE_BASE
        blob = blob_with({base + 0xA0: 11, base + 0xA0 + 0x22: 22})
        self.assertEqual(motion.decode_settings(blob, "aim")["deadzone"]["initial"], 11)
        self.assertEqual(motion.decode_settings(blob, "tilt")["deadzone"]["initial"], 22)

    def test_invert_yaw_tilt_reads_the_0x20_shifted_offset_not_0x22(self):
        base = motion.STORAGE_BASE
        blob = blob_with({base + 0xB4: 0x01, base + 0xB4 + 0x20: 0x01})
        self.assertTrue(motion.decode_settings(blob, "tilt")["invert_yaw"])
        # The naive +0x22 address must NOT be where this reads from.
        blob2 = blob_with({base + 0xB4 + 0x22: 0x01})
        self.assertFalse(motion.decode_settings(blob2, "tilt")["invert_yaw"])

    def test_invert_roll_is_none_on_tilt(self):
        base = motion.STORAGE_BASE
        blob = blob_with({base + 0xB2: 0x01})
        self.assertTrue(motion.decode_settings(blob, "aim")["invert_roll"])
        self.assertIsNone(motion.decode_settings(blob, "tilt")["invert_roll"])

    def test_direction_bindings_treat_0xff_as_unbound_and_have_no_ring(self):
        base = motion.STORAGE_BASE + 0xB9
        blob = blob_with({base: 0x01, base + 1: 0xFF, base + 2: 0x03, base + 3: 0xFF})
        db = motion.decode_settings(blob, "aim")["direction_bindings"]
        self.assertEqual(db["up"], "native_dpad_up")
        self.assertIsNone(db["down"])
        self.assertNotIn("ring", db)

    def test_curve_custom_index_decodes(self):
        blob = blob_with({motion.STORAGE_BASE + 0xA5: 0x03})
        self.assertEqual(motion.decode_settings(blob, "aim")["curve"]["preset"], "custom")

    def test_output_decodes_using_the_same_enum_as_sticks(self):
        blob = blob_with({motion.STORAGE_BASE + 0xB7: 0x03})
        self.assertEqual(motion.decode_settings(blob, "aim")["output"], "directional")

    def test_short_blob_yields_none_rather_than_raising(self):
        decoded = motion.decode_settings(b"\x00" * 8, "aim")
        self.assertIsNone(decoded["deadzone"]["initial"])


class TriggerDecodeTest(unittest.TestCase):
    def test_settings_decode_from_setting_id_directly(self):
        blob = blob_with({0xD8: 0x81, 0xCF: 5, 0xD0: 95})
        decoded = triggers.decode_settings(blob, "left")
        self.assertEqual(decoded["hair_trigger_mode"], "adaptive")
        self.assertEqual(decoded["deadzone"], {"initial": 5, "max": 95})

    def test_right_side_uses_the_0x1c_shift(self):
        blob = blob_with({0xCF: 3, 0xCF + 0x1C: 8})
        self.assertEqual(triggers.decode_settings(blob, "left")["deadzone"]["initial"], 3)
        self.assertEqual(triggers.decode_settings(blob, "right")["deadzone"]["initial"], 8)


class DpadOptionsDecodeTest(unittest.TestCase):
    def test_both_toggles_decode(self):
        blob = blob_with({0x2D: 1, 0x2B: 1})
        decoded = dpad_options.decode_settings(blob)
        self.assertTrue(decoded["dpad_diagonal_lock"])
        self.assertTrue(decoded["swap_stick_dpad"])

    def test_zero_decodes_false_not_none(self):
        decoded = dpad_options.decode_settings(blob_with({}))
        self.assertIs(decoded["dpad_diagonal_lock"], False)


class DockDecodeTest(unittest.TestCase):
    def test_offsets_include_the_storage_base(self):
        # Confirmed by read-diff: brightness lands at 0x1F9, not 0xF9.
        blob = blob_with({0x1F9: 75, 0x1F6: 1}, size=dock_settings.BLOB_LENGTH)
        decoded = dock_settings.decode_settings(blob)
        self.assertEqual(decoded["dock_led_brightness"], 75)
        self.assertTrue(decoded["dock_auto_on_off"])

    def test_blob_length_covers_both_settings(self):
        highest = max(dock_settings.BRIGHTNESS_SETTING_ID, dock_settings.AUTO_ON_OFF_SETTING_ID)
        self.assertGreater(dock_settings.BLOB_LENGTH, highest + 0x100)


if __name__ == "__main__":
    unittest.main()


class UnconfiguredTriggerDecodeTest(unittest.TestCase):
    """LT/RT's keycode byte is 0x00 until the trigger is explicitly bound.

    That means "performs its factory function", not "no keycode": Profile 2
    carries 0x00 for both triggers and both work normally (verified in Steam
    Input and KDE controller settings, 2026-08-07). It decodes to None, the
    same as every other unconfigured slot, so the GUI shows "(Default)"
    rather than "Raw: 0x00" on an untouched profile.
    """

    def _blob_with_triggers(self, lt_byte, rt_byte):
        blob = bytearray(0x200)
        blob[buttons.TRIGGER_BUTTON_OFFSETS["lt"]] = lt_byte
        blob[buttons.TRIGGER_BUTTON_OFFSETS["rt"]] = rt_byte
        return bytes(blob)

    def test_zero_decodes_as_unconfigured(self):
        decoded = buttons.decode_button_table(self._blob_with_triggers(0x00, 0x00))
        self.assertIsNone(decoded["lt"])
        self.assertIsNone(decoded["rt"])

    def test_a_real_keycode_still_decodes_normally(self):
        decoded = buttons.decode_button_table(self._blob_with_triggers(0x13, 0x14))
        self.assertEqual(decoded["lt"], "native_lt")
        self.assertEqual(decoded["rt"], "native_rt")

    def test_zero_is_not_treated_as_unset_everywhere(self):
        """Scoped to the trigger offsets on purpose -- 0x00 is not a
        universal 'unset' marker, and decode_keycode() must keep returning
        the raw hex string for it so other callers aren't changed."""
        self.assertEqual(buttons.decode_keycode(0x00), "0x00")
