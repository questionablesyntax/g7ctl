"""ControllerDiagram tests, D2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from g7ctlc.palette import DARK_PALETTE, LIGHT_PALETTE


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ControllerDiagramTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.controller_diagram import ControllerDiagram

        self.diagram = ControllerDiagram(DARK_PALETTE)
        self.diagram.resize(300, 240)

    def test_loads_a_valid_svg(self):
        self.assertTrue(self.diagram._renderer.isValid())

    def test_starts_with_no_highlight(self):
        self.assertIsNone(self.diagram._highlighted)

    def test_every_known_button_has_a_hit_region(self):
        from pyg7.buttons import KNOWN_BUTTON_IDS

        missing = [b for b in KNOWN_BUTTON_IDS if not self.diagram._renderer.elementExists(b)]
        self.assertEqual(missing, [], f"buttons missing a hit region in the drawing: {missing}")

    def test_setting_a_known_button_highlights_it(self):
        self.diagram.set_highlighted("a")
        self.assertEqual(self.diagram._highlighted, "a")

    def test_an_unknown_id_is_treated_as_no_highlight(self):
        # Real-world case this guards: a page wiring bug (typo'd button id,
        # or an id that exists in KNOWN_BUTTON_IDS but was never added to
        # the drawing) must not crash the GUI -- see the method's own
        # docstring for why this is a silent fallback rather than a raise.
        self.diagram.set_highlighted("not_a_real_button")
        self.assertIsNone(self.diagram._highlighted)

    def test_clearing_the_highlight_with_none_works(self):
        self.diagram.set_highlighted("a")
        self.diagram.set_highlighted(None)
        self.assertIsNone(self.diagram._highlighted)

    def test_set_palette_does_not_raise(self):
        self.diagram.set_palette(LIGHT_PALETTE)
        self.assertIs(self.diagram._palette, LIGHT_PALETTE)

    def test_paints_without_raising_with_a_highlight_active(self):
        # Exercises the actual paintEvent path, highlight branch included --
        # a geometry bug in _paint_highlight (e.g. a stray division) would
        # otherwise only surface the first time a real user focused a row.
        self.diagram.set_highlighted("guide") if self.diagram._renderer.elementExists("guide") \
            else self.diagram.set_highlighted("a")
        pixmap = self.diagram.grab()
        self.assertFalse(pixmap.isNull())

    def test_guide_and_mode_have_no_hit_region(self):
        # Neither is bindable (see assets/drawing/SOURCES.md) -- a hit
        # region for either would make the diagram claim a remap target
        # that doesn't exist.
        self.assertFalse(self.diagram._renderer.elementExists("guide"))
        self.assertFalse(self.diagram._renderer.elementExists("mode"))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsViewDiagramSyncTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.views.buttons_view import ButtonsView

        self.view = ButtonsView(DARK_PALETTE)
        self.view.resize(900, 700)
        self.view.show()

    def test_focusing_a_default_field_highlights_its_button_on_the_diagram(self):
        self.view._rows["x"].default_field.setFocus()
        self.app.processEvents()
        self.assertEqual(self.view.diagram._highlighted, "x")

    def test_focusing_a_different_row_moves_the_highlight(self):
        self.view._rows["x"].default_field.setFocus()
        self.app.processEvents()
        self.view._rows["l4"].default_field.setFocus()
        self.app.processEvents()
        self.assertEqual(self.view.diagram._highlighted, "l4")

    def test_clicking_a_field_also_highlights_its_button(self):
        # Real-world path alongside keyboard Tab -- .click() both focuses
        # and emits clicked(), the same as a real mouse press.
        self.view._rows["y"].default_field.click()
        self.app.processEvents()
        self.assertEqual(self.view.diagram._highlighted, "y")

    def test_set_palette_reaches_the_diagram(self):
        self.view.set_palette(LIGHT_PALETTE)
        self.assertIs(self.view.diagram._palette, LIGHT_PALETTE)


if __name__ == "__main__":
    unittest.main()
