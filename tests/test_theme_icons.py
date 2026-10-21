"""Icon loader tests, A1 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent -- `g7ctlc.icon_loader`'s
`LucideIconLoader` imports PyQt6/QtSvg at module level. `g7ctlc.icons`
itself (imported below for `ICON_NAMES`) is Qt-free, so that one import
stays outside the skip guard safely.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from g7ctlc.icons import ICON_NAMES
from g7ctlc.palette import DARK_PALETTE, LIGHT_PALETTE


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class LucideIconLoaderTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.icon_loader import LucideIconLoader

        self.loader = LucideIconLoader()

    def test_every_vendored_name_loads_at_both_sizes(self):
        for name in ICON_NAMES:
            for size in (16, 20):
                icon = self.loader.icon(name, size, "text_primary", DARK_PALETTE)
                self.assertFalse(icon.isNull(), f"{name} at {size}px produced a null QIcon")

    @staticmethod
    def _first_opaque_pixel(image):
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.alpha() > 0:
                    return color
        return None  # pragma: no cover - would mean a blank render

    def test_recoloring_actually_changes_the_rendered_pixel(self):
        # Same icon, two roles with very different hex values on the dark
        # palette (text_primary is near-white, signal_fill is orange) --
        # if recoloring didn't apply, both renders would be identical.
        # Scans for the first drawn (non-transparent) pixel rather than a
        # fixed coordinate: a fixed guess landed off the "check" glyph's
        # stroke in the first version of this test, comparing two
        # transparent pixels and passing for the wrong reason.
        light_tint = self.loader.icon("check", 20, "text_primary", DARK_PALETTE)
        signal_tint = self.loader.icon("check", 20, "signal_fill", DARK_PALETTE)
        light_color = self._first_opaque_pixel(light_tint.pixmap(20, 20).toImage())
        signal_color = self._first_opaque_pixel(signal_tint.pixmap(20, 20).toImage())
        self.assertIsNotNone(light_color)
        self.assertIsNotNone(signal_color)
        self.assertNotEqual(
            light_color, signal_color,
            "recoloring text_primary vs signal_fill produced identical pixels",
        )

    def test_same_key_is_served_from_cache(self):
        first = self.loader.icon("lock", 16, "text_primary", DARK_PALETTE)
        second = self.loader.icon("lock", 16, "text_primary", DARK_PALETTE)
        self.assertIs(first, second)

    def test_clear_cache_drops_prior_entries(self):
        first = self.loader.icon("lock", 16, "text_primary", DARK_PALETTE)
        self.loader.clear_cache()
        second = self.loader.icon("lock", 16, "text_primary", DARK_PALETTE)
        self.assertIsNot(first, second)

    def test_dark_and_light_palette_produce_different_cache_entries(self):
        dark = self.loader.icon("usb", 16, "text_primary", DARK_PALETTE)
        light = self.loader.icon("usb", 16, "text_primary", LIGHT_PALETTE)
        self.assertIsNot(dark, light)


if __name__ == "__main__":
    unittest.main()
