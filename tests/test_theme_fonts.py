"""Font loading tests, A1 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent, same as the other g7ctlc
test modules -- `g7ctlc.fonts` imports PyQt6 at module level.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class LoadFontsTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_vendored_family_loads_on_this_environment(self):
        from g7ctlc.fonts import load_fonts

        result = load_fonts()
        self.assertTrue(
            result.ok,
            f"expected every vendored family to load; failed: {result.failed_families}",
        )
        self.assertEqual(
            set(result.loaded_families),
            {"Atkinson Hyperlegible Next", "Atkinson Hyperlegible Mono", "Barlow Semi Condensed"},
        )

    def test_load_fonts_is_idempotent(self):
        from g7ctlc.fonts import load_fonts

        first = load_fonts()
        second = load_fonts()
        self.assertEqual(first, second)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class FontForRoleTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from g7ctlc.fonts import load_fonts

        cls.load_result = load_fonts()

    def test_every_type_role_builds_a_font_without_raising(self):
        from g7ctlc.fonts import font_for
        from g7ctlc.tokens import TYPE_ROLES

        for role in TYPE_ROLES:
            font = font_for(role, self.load_result)
            self.assertGreater(font.pointSizeF(), 0)

    def test_display_role_uses_points_not_pixel_size(self):
        # DESIGN-SPEC.md 10.2 item 6: points, not pixels, so the user's
        # own font-size preference is honoured. setPointSizeF is what
        # was actually called -- pixelSize() reports -1 when a font was
        # sized in points rather than pixels.
        from g7ctlc.fonts import font_for

        font = font_for("display", self.load_result)
        self.assertEqual(font.pixelSize(), -1)
        self.assertAlmostEqual(font.pointSizeF(), 36.0, places=3)

    def test_readout_role_requests_tabular_figures_without_raising(self):
        from g7ctlc.fonts import font_for

        # Already confirmed present on this environment in A0
        # (g7ctlc/assets/fonts/SOURCES.md); this just proves font_for's
        # guarded call path doesn't blow up either way.
        font_for("readout", self.load_result)

    def test_unloaded_family_falls_back_to_the_documented_chain(self):
        from g7ctlc.fonts import FALLBACK_CHAIN, FontLoadResult, font_for

        empty_result = FontLoadResult(loaded_families=(), failed_families=("Barlow Semi Condensed",))
        font = font_for("display", empty_result)
        self.assertEqual(font.family(), FALLBACK_CHAIN[0])


if __name__ == "__main__":
    unittest.main()
