"""Colour-rule verification, A1 of the redesign (`IMPLEMENTATION-PLAN.md`:
"the colour-rule test (signal colour only in its three roles, across QSS,
painter and asset use)"). Pure Python -- `g7ctlc.qss` and `g7ctlc.palette`
need no PyQt6.

CRITIC.md finding #1, accepted: the signal hue is a closed list -- the
held state, live input marks, the button that actually writes. This test
checks that list two ways: structurally (only `SIGNAL_ROLE_NAMES` hold the
signal hex, on both palettes) and textually (the generated QSS only uses
those hex values inside the `role="write"` block).

Icon/painter use isn't covered here -- that's exercised against the
running widgets as those phases (A2 ownership bar, A1's own icon loader)
land, not as string-matching.
"""

import re
import unittest

from g7ctlc.palette import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    PALETTE_ROLE_NAMES,
    SIGNAL_ROLE_NAMES,
    Palette,
)
from g7ctlc.qss import generate_stylesheet

_SIGNAL_HEX_VALUES = {
    "fill": lambda p: p.signal_fill,
    "fill_hover": lambda p: p.signal_fill_hover,
    "fill_pressed": lambda p: p.signal_fill_pressed,
    "mark": lambda p: p.signal_mark,
}


class _NoOtherRoleHoldsTheSignalHueAssertions:
    """Mixin, not a `TestCase` -- see the identical note in
    `test_theme_palette.py`."""

    palette: Palette

    def test_no_non_signal_role_equals_any_signal_hex(self):
        signal_hexes = {fn(self.palette).lower() for fn in _SIGNAL_HEX_VALUES.values()}
        for role in PALETTE_ROLE_NAMES:
            if role in SIGNAL_ROLE_NAMES:
                continue
            value = getattr(self.palette, role).lower()
            self.assertNotIn(
                value,
                signal_hexes,
                f"non-signal role {role!r} equals a signal hex ({value}) -- "
                "the orange rule (CRITIC.md #1) is supposed to be a closed list",
            )


class DarkPaletteSignalHueTest(_NoOtherRoleHoldsTheSignalHueAssertions, unittest.TestCase):
    palette = DARK_PALETTE


class LightPaletteSignalHueTest(_NoOtherRoleHoldsTheSignalHueAssertions, unittest.TestCase):
    palette = LIGHT_PALETTE


def _blocks(qss: str) -> list[tuple[str, str]]:
    """Split generated QSS into (selector, body) pairs. Good enough for
    this generator's own output -- no nested braces, no comments inside
    a rule body -- not a general CSS parser."""
    # Strip /* ... */ comments first so a mention of a hex value in prose
    # (there isn't one today, but nothing should rely on that) can't be
    # mistaken for a rule.
    without_comments = re.sub(r"/\*.*?\*/", "", qss, flags=re.DOTALL)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", without_comments)


class _SignalHexOnlyInWriteButtonBlockAssertions:
    """Mixin, not a `TestCase` -- see the identical note in
    `test_theme_palette.py`."""

    palette: Palette

    def test_signal_fill_family_only_in_write_button_rules(self):
        qss = generate_stylesheet(self.palette)
        signal_hexes = {
            self.palette.signal_fill.lower(),
            self.palette.signal_fill_hover.lower(),
            self.palette.signal_fill_pressed.lower(),
        }
        for selector, body in _blocks(qss):
            if any(h in body.lower() for h in signal_hexes):
                self.assertIn(
                    'role="write"',
                    selector,
                    f"selector {selector.strip()!r} uses a signal fill hex "
                    "but isn't a role=\"write\" rule",
                )

    def test_write_button_block_exists_and_uses_signal_fill(self):
        qss = generate_stylesheet(self.palette)
        write_blocks = [
            body for selector, body in _blocks(qss) if 'role="write"' in selector
        ]
        self.assertTrue(write_blocks, "no role=\"write\" rule found at all")
        self.assertTrue(
            any(self.palette.signal_fill.lower() in b.lower() for b in write_blocks),
            "role=\"write\" rules exist but none use signal_fill",
        )


class DarkStylesheetSignalRuleTest(_SignalHexOnlyInWriteButtonBlockAssertions, unittest.TestCase):
    palette = DARK_PALETTE


class LightStylesheetSignalRuleTest(_SignalHexOnlyInWriteButtonBlockAssertions, unittest.TestCase):
    palette = LIGHT_PALETTE


if __name__ == "__main__":
    unittest.main()
