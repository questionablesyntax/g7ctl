"""identify_variant()/identify_unsupported() -- variants.py, split out of
constants.py 2026-09-01. identify_variant() is the real answer to roadmap
item 36's original question, via a variant's baseline PID rather than a
CMD=0x01 sweep -- see variants.py's own comment on KNOWN_VARIANTS for the
reasoning.
"""
import unittest
from unittest import mock

from pyg7 import variants


class IdentifyVariantTest(unittest.TestCase):
    def test_known_xid_pids_resolve_to_their_confirmed_names(self):
        self.assertEqual(variants.identify_variant(0x109b), "Shadow Ember")
        self.assertEqual(variants.identify_variant(0x1003), "White Trimode")
        self.assertEqual(variants.identify_variant(0x105d), "Zenless Zone Zero")

    def test_unconfirmed_pid_returns_none_not_a_guess(self):
        # e.g. Dragon's Dogma 2 / WUCHANG editions -- believed compatible
        # per README.md, but no PID report on file yet. None is the
        # correct, honest answer, not an exception or a placeholder string.
        self.assertIsNone(variants.identify_variant(0x9999))

    def test_dongle_pids_are_not_variant_lookups(self):
        # A dongle PID is its own wired counterpart + 1 wherever
        # confirmed, not a separate lookup here. Passing one of those in
        # isn't meaningful input, and should read as "unknown", not
        # silently match something by accident.
        self.assertIsNone(variants.identify_variant(0x109c))    # dongle
        self.assertIsNone(variants.identify_variant(0x1004))    # dongle, Trimode

    def test_hid_and_native_pids_currently_collide_so_stay_unresolved(self):
        # Real hardware fact, not a code gap: 0x100a is confirmed shared by
        # both Shadow Ember and White Trimode, and 0x1022 is confirmed
        # shared by both Shadow Ember and Zenless Zone Zero -- see
        # KNOWN_VARIANTS' own comment. identify_variant() must not guess
        # one name out of a genuine collision.
        self.assertIsNone(variants.identify_variant(0x100a))    # HID-presenting
        self.assertIsNone(variants.identify_variant(0x1022))    # native/GIP

    def test_an_unambiguous_hid_or_native_pid_resolves(self):
        # Added 2026-09-01: a controller caught sitting at its HID or
        # native identity (not yet handshaked to baseline) still resolves,
        # as long as exactly one known variant has that value -- proven
        # here against a patched registry, since no real entry is
        # unambiguous on either field today (see the collision test
        # above). variants.Variant is a NamedTuple (immutable), so this
        # patches the whole KNOWN_VARIANTS tuple, not individual fields.
        solo_hid = variants.Variant("Solo Edition", xid_pid=0x1234, dongle_pid=None,
                                     hid_pid=0xAAAA)
        solo_native = variants.Variant("Other Edition", xid_pid=0x5678, dongle_pid=None,
                                        native_pid=0xBBBB)
        with mock.patch.object(variants, "KNOWN_VARIANTS",
                                variants.KNOWN_VARIANTS + (solo_hid, solo_native)):
            self.assertEqual(variants.identify_variant(0xAAAA), "Solo Edition")
            self.assertEqual(variants.identify_variant(0xBBBB), "Other Edition")


class IsKnownDonglePidTest(unittest.TestCase):
    """Replaces the old XID_PID_CANDIDATES lookup (retired 2026-09-01) --
    same data, minus the redundant wired-PID-mapped-to-False half, which
    could never satisfy this check anyway."""

    def test_known_dongle_pids_are_recognized(self):
        self.assertTrue(variants.is_known_dongle_pid(0x109c))   # Shadow Ember
        self.assertTrue(variants.is_known_dongle_pid(0x1004))   # White Trimode

    def test_wired_pids_are_not_dongle_pids(self):
        self.assertFalse(variants.is_known_dongle_pid(0x109b))  # Shadow Ember
        self.assertFalse(variants.is_known_dongle_pid(0x1003))  # White Trimode

    def test_a_variant_with_no_confirmed_dongle_pid_matches_nothing(self):
        # Zenless Zone Zero's dongle PID is unconfirmed (see variants.py's
        # comment) -- must not be guessed from the "+1" pattern.
        self.assertIsNone(variants.KNOWN_VARIANTS[2].dongle_pid)

    def test_unknown_pid_is_not_a_dongle_pid(self):
        self.assertFalse(variants.is_known_dongle_pid(0x9999))


class IdentifyUnsupportedTest(unittest.TestCase):
    """Added 2026-09-01: a reject list for PIDs confirmed to belong to a
    different GameSir Nexus-family product, not a G7 Pro at all. Starts
    empty -- these tests patch it directly rather than depending on real
    entries existing yet.
    """

    def test_empty_by_default(self):
        # No other GameSir Nexus-family product's PID has been confirmed
        # yet (see README.md "Hardware support" for the ones this project
        # knows exist but has no PID for). This pins that starting state so
        # a future addition here is a deliberate choice, not an accident.
        self.assertEqual(variants.UNSUPPORTED_PIDS, {})

    def test_a_confirmed_unsupported_pid_resolves_to_its_name(self):
        with mock.patch.dict(
            variants.UNSUPPORTED_PIDS, {0xBEEF: "GameSir T7 Pro"}, clear=True
        ):
            self.assertEqual(variants.identify_unsupported(0xBEEF), "GameSir T7 Pro")

    def test_an_unlisted_pid_is_not_unsupported(self):
        # Absence here is NOT confirmation of G7 Pro compatibility -- it
        # also covers every genuinely unknown PID. See the function's own
        # docstring.
        self.assertIsNone(variants.identify_unsupported(0x9999))


if __name__ == "__main__":
    unittest.main()
