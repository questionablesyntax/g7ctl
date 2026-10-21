"""Contrast verification, A1 of the redesign (`IMPLEMENTATION-PLAN.md`:
"the contrast test over every declared pair in both themes"). Pure
Python -- no PyQt6 import, `g7ctlc.palette` needs none, so this runs
regardless of the environment's Qt availability, unlike the rest of the
g7ctlc test suite.

Thresholds are WCAG's own (text needs 4.5:1, UI components and graphics
need 3:1), computed with the standard relative-luminance formula. A
handful of pairs are also spot-checked against the specific figures
`DIRECTION-A.md` section 2 documents, as a drift detector: if a palette
value changes later, this is what will notice that the two-decimal
numbers in that doc are no longer what's actually shipped.
"""

import unittest

from g7ctlc.palette import DARK_PALETTE, LIGHT_PALETTE, Palette

TEXT_MIN = 4.5
UI_MIN = 3.0


def _srgb_channel_to_linear(c: float) -> float:
    c /= 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (_srgb_channel_to_linear(c) for c in (r, g, b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


class ContrastRatioMathTest(unittest.TestCase):
    """The formula itself, against values anyone can hand-check: pure
    black/white is exactly 21:1, and a color against itself is 1:1."""

    def test_black_on_white_is_21_to_1(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0, places=2)

    def test_identical_colors_is_1_to_1(self):
        self.assertAlmostEqual(contrast_ratio("#808080", "#808080"), 1.0, places=5)


class _PaletteContrastAssertions:
    """Mixin, not a `TestCase` itself -- deliberately not inheriting
    `unittest.TestCase` here, so this class and its `test_*` methods
    aren't collected and run on their own (with no `palette` set). Only
    the concrete `Dark`/`LightPaletteContrastTest` classes below, which
    mix this in alongside `unittest.TestCase`, are real test cases."""

    palette: Palette

    def assertTextContrast(self, fg: str, bg: str, msg: str) -> None:
        ratio = contrast_ratio(getattr(self.palette, fg), getattr(self.palette, bg))
        self.assertGreaterEqual(ratio, TEXT_MIN, f"{msg}: {ratio:.2f} < {TEXT_MIN}")

    def assertUiContrast(self, fg: str, bg: str, msg: str) -> None:
        ratio = contrast_ratio(getattr(self.palette, fg), getattr(self.palette, bg))
        self.assertGreaterEqual(ratio, UI_MIN, f"{msg}: {ratio:.2f} < {UI_MIN}")

    def test_text_primary_on_every_surface(self):
        for surface in ("surface_ground", "surface_panel", "surface_raised"):
            self.assertTextContrast("text_primary", surface, f"text_primary on {surface}")

    def test_text_secondary_on_every_surface(self):
        for surface in (
            "surface_ground",
            "surface_panel",
            "surface_raised",
            "surface_overlay",
        ):
            self.assertTextContrast("text_secondary", surface, f"text_secondary on {surface}")

    def test_text_on_signal_on_signal_fills(self):
        for fill in ("signal_fill", "signal_fill_hover", "signal_fill_pressed"):
            self.assertTextContrast("text_on_signal", fill, f"text_on_signal on {fill}")

    def test_text_on_alarm_on_alarm_fills(self):
        for fill in ("alarm_fill", "alarm_fill_hover"):
            self.assertTextContrast("text_on_alarm", fill, f"text_on_alarm on {fill}")

    def test_text_alarm_on_every_surface(self):
        for surface in ("surface_ground", "surface_panel", "surface_raised"):
            self.assertTextContrast("text_alarm", surface, f"text_alarm on {surface}")

    def test_text_caution_on_every_surface(self):
        for surface in ("surface_ground", "surface_panel", "surface_raised"):
            self.assertTextContrast("text_caution", surface, f"text_caution on {surface}")

    def test_border_control_on_every_surface(self):
        # UI component, 3:1 -- the checkbox/input edge has to be visible,
        # not readable as text.
        for surface in (
            "surface_ground",
            "surface_panel",
            "surface_raised",
            "surface_overlay",
        ):
            self.assertUiContrast("border_control", surface, f"border_control on {surface}")

    def test_focus_ring_on_every_surface(self):
        for surface in (
            "surface_ground",
            "surface_panel",
            "surface_raised",
            "surface_overlay",
        ):
            self.assertUiContrast("focus_ring", surface, f"focus_ring on {surface}")

    def test_signal_mark_on_panel_and_raised(self):
        # Graphic, 3:1 -- the live-input dot/trace has to read against the
        # page, not just against text contrast rules.
        for surface in ("surface_panel", "surface_raised"):
            self.assertUiContrast("signal_mark", surface, f"signal_mark on {surface}")


class DarkPaletteContrastTest(_PaletteContrastAssertions, unittest.TestCase):
    palette = DARK_PALETTE


class LightPaletteContrastTest(_PaletteContrastAssertions, unittest.TestCase):
    palette = LIGHT_PALETTE


class DocumentedFigureSpotCheckTest(unittest.TestCase):
    """A handful of unambiguous pairs from `DIRECTION-A.md` section 2's
    own contrast table, checked to two decimals as a drift detector."""

    def test_dark_text_primary_on_ground(self):
        self.assertAlmostEqual(
            contrast_ratio(DARK_PALETTE.text_primary, DARK_PALETTE.surface_ground),
            14.14,
            places=1,
        )

    def test_dark_text_primary_on_panel(self):
        self.assertAlmostEqual(
            contrast_ratio(DARK_PALETTE.text_primary, DARK_PALETTE.surface_panel),
            12.72,
            places=1,
        )

    def test_light_text_primary_on_panel(self):
        self.assertAlmostEqual(
            contrast_ratio(LIGHT_PALETTE.text_primary, LIGHT_PALETTE.surface_panel),
            15.60,
            places=1,
        )

    def test_dark_text_on_signal_on_signal_fill(self):
        self.assertAlmostEqual(
            contrast_ratio(DARK_PALETTE.text_on_signal, DARK_PALETTE.signal_fill),
            7.20,
            places=1,
        )

    def test_dark_border_subtle_on_panel_is_decorative_only(self):
        # Documented as 1.41, explicitly "no requirement" -- a dividing
        # hairline, not something read as text or a control edge. Checked
        # here only so a future change is a deliberate edit, not silent
        # drift away from the documented figure.
        self.assertAlmostEqual(
            contrast_ratio(DARK_PALETTE.border_subtle, DARK_PALETTE.surface_panel),
            1.41,
            places=1,
        )


if __name__ == "__main__":
    unittest.main()
