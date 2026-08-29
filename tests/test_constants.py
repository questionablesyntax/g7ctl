"""identify_variant() -- the real answer to roadmap item 36's original
question, via PID_XID rather than a CMD=0x01 sweep. See constants.py's
own comment on VARIANT_NAMES for the reasoning.
"""
import unittest

from pyg7 import constants


class IdentifyVariantTest(unittest.TestCase):
    def test_known_xid_pids_resolve_to_their_confirmed_names(self):
        self.assertEqual(constants.identify_variant(constants.PID_XID), "Shadow Ember")
        self.assertEqual(constants.identify_variant(constants.PID_XID_TRIMODE), "White Trimode")
        self.assertEqual(constants.identify_variant(constants.PID_XID_ZZZ), "Zenless Zone Zero")

    def test_unconfirmed_pid_returns_none_not_a_guess(self):
        # e.g. Dragon's Dogma 2 / WUCHANG editions -- believed compatible
        # per README.md, but no PID report on file yet. None is the
        # correct, honest answer, not an exception or a placeholder string.
        self.assertIsNone(constants.identify_variant(0x9999))

    def test_dongle_and_hid_pids_are_not_variant_lookups(self):
        # Deliberately keyed on PID_XID only -- a dongle PID is its own
        # wired counterpart + 1 wherever confirmed, not a separate lookup
        # here, and PID_HID/PID_NATIVE aren't independently confirmed to
        # vary per-variant the same way. Passing one of those in isn't
        # meaningful input, and should read as "unknown", not silently
        # match something by accident.
        self.assertIsNone(constants.identify_variant(constants.PID_DONGLE))
        self.assertIsNone(constants.identify_variant(constants.PID_DONGLE_TRIMODE))
        self.assertIsNone(constants.identify_variant(constants.PID_HID))
        self.assertIsNone(constants.identify_variant(constants.PID_NATIVE))


if __name__ == "__main__":
    unittest.main()
