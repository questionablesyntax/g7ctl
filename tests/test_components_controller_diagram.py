"""ControllerDiagram tests, D2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
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

    def test_the_supersampled_art_is_reused_until_the_size_or_palette_changes(self):
        self.diagram.show()
        self.diagram.grab()
        cached = self.diagram._art_cache
        self.assertIsNotNone(cached)
        # A repaint that changes only callouts or the highlight reuses it.
        self.diagram.set_highlighted("a")
        self.diagram.set_bindings({"a": "Keyboard: R"})
        self.diagram.grab()
        self.assertIs(self.diagram._art_cache[1], cached[1])
        # A new size re-renders it.
        self.diagram.resize(500, 420)
        self.diagram.grab()
        self.assertIsNot(self.diagram._art_cache[1], cached[1])

    def test_changing_the_palette_drops_the_cached_art(self):
        self.diagram.show()
        self.diagram.grab()
        self.assertIsNotNone(self.diagram._art_cache)
        self.diagram.set_palette(LIGHT_PALETTE)
        self.assertIsNone(self.diagram._art_cache)
        self.diagram.grab()
        self.assertIsNotNone(self.diagram._art_cache)

    def test_the_line_art_actually_recolours_for_a_different_palette(self):
        # Real bug, found 2026-10-22: QSvgRenderer does not follow the
        # host QPainter's pen for fill="currentColor"/stroke="currentColor"
        # the way a browser would -- it resolves those once, internally,
        # against its own default (black), so the drawing rendered black
        # line art on the dark theme regardless of palette. A pixmap diff
        # is the real behavioral check; comparing hex strings would only
        # prove the *source* substitution ran, not that two differently-
        # themed renders actually look different.
        from g7ctlc.controller_diagram import ControllerDiagram

        dark_widget = ControllerDiagram(DARK_PALETTE)
        dark_widget.resize(300, 240)
        light_widget = ControllerDiagram(LIGHT_PALETTE)
        light_widget.resize(300, 240)
        dark_pixmap = dark_widget.grab()
        light_pixmap = light_widget.grab()
        self.assertNotEqual(
            dark_pixmap.toImage(), light_pixmap.toImage(),
            "dark- and light-palette renders must not be pixel-identical",
        )

    def test_build_renderer_produces_a_valid_renderer_for_both_palettes(self):
        from g7ctlc.controller_diagram import _build_renderer

        self.assertTrue(_build_renderer(DARK_PALETTE).isValid())
        self.assertTrue(_build_renderer(LIGHT_PALETTE).isValid())

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

    def test_every_hit_region_has_a_hotspot(self):
        from pyg7.buttons import KNOWN_BUTTON_IDS

        self.assertEqual(set(self.diagram._hotspots), set(KNOWN_BUTTON_IDS))

    def test_hotspots_are_positioned_inside_the_widget_once_shown(self):
        self.diagram.show()
        for hotspot in self.diagram._hotspots.values():
            geo = hotspot.geometry()
            self.assertGreater(geo.width(), 0)
            self.assertGreater(geo.height(), 0)

    def test_custom_order_controls_tab_order(self):
        from g7ctlc.controller_diagram import ControllerDiagram

        custom = ControllerDiagram(DARK_PALETTE, order=["b", "a"])
        self.assertEqual(list(custom._hotspots), ["b", "a"])

    def test_interactive_false_builds_no_hotspots_at_all(self):
        # Overview's own use (read-only drawing, D2 rework) -- no Tab
        # stops and no activated/focused signals, rather than a
        # clickable-looking part that silently does nothing.
        from g7ctlc.controller_diagram import ControllerDiagram

        quiet = ControllerDiagram(DARK_PALETTE, interactive=False)
        self.assertEqual(quiet._hotspots, {})
        self.assertIsNone(quiet.hotspot_for("a"))

    def test_interactive_false_still_paints_highlight_and_callouts(self):
        # The flag only skips hotspots -- set_highlighted()/set_bindings()
        # and the paint path they drive are unaffected.
        from g7ctlc.controller_diagram import ControllerDiagram

        quiet = ControllerDiagram(DARK_PALETTE, interactive=False)
        quiet.resize(300, 240)
        quiet.set_highlighted("a")
        quiet.set_bindings({"b": "Keyboard: R"})
        self.assertEqual(quiet._highlighted, "a")
        pixmap = quiet.grab()
        self.assertFalse(pixmap.isNull())

    def test_clicking_a_hotspot_emits_activated_with_its_button_id(self):
        self.diagram.show()
        received = []
        self.diagram.activated.connect(received.append)
        QTest.mouseClick(self.diagram.hotspot_for("a"), Qt.MouseButton.LeftButton)
        self.assertEqual(received, ["a"])

    def test_clicking_a_hotspot_also_focuses_and_highlights_it(self):
        self.diagram.show()
        self.app.processEvents()  # window must actually be active for setFocus() to stick
        QTest.mouseClick(self.diagram.hotspot_for("b"), Qt.MouseButton.LeftButton)
        self.assertTrue(self.diagram.hotspot_for("b").hasFocus())
        self.assertEqual(self.diagram._highlighted, "b")

    def test_enter_on_a_focused_hotspot_activates_it(self):
        self.diagram.show()
        self.diagram.hotspot_for("x").setFocus()
        received = []
        self.diagram.activated.connect(received.append)
        QTest.keyClick(self.diagram.hotspot_for("x"), Qt.Key.Key_Return)
        self.assertEqual(received, ["x"])

    def test_space_on_a_focused_hotspot_activates_it(self):
        self.diagram.show()
        self.diagram.hotspot_for("y").setFocus()
        received = []
        self.diagram.activated.connect(received.append)
        QTest.keyClick(self.diagram.hotspot_for("y"), Qt.Key.Key_Space)
        self.assertEqual(received, ["y"])

    def test_set_bindings_only_affects_remapped_buttons(self):
        self.diagram.set_bindings({"a": "Keyboard: R"})
        self.assertEqual(self.diagram._bindings, {"a": "Keyboard: R"})

    def test_every_button_gets_a_callout_without_expanding_remapped_bindings(self):
        from g7ctlc.controller_diagram import UNMAPPED_CALLOUT_TEXT
        from pyg7.buttons import KNOWN_BUTTON_IDS

        self.diagram.set_bindings({"a": "Keyboard: R"})
        self.diagram.show()
        self.diagram.grab()
        self.assertEqual(set(self.diagram._callout_rects), set(KNOWN_BUTTON_IDS))
        self.assertEqual(self.diagram._bindings, {"a": "Keyboard: R"})
        self.assertEqual(self.diagram._callout_text("b"), UNMAPPED_CALLOUT_TEXT)

    def test_compact_width_keeps_callout_cards_outside_the_artwork(self):
        # The main window can narrow until its content pane is only this
        # wide. Cards must elide there rather than force the artwork into
        # its full-width fallback, which would draw it behind both rails.
        self.diagram.resize(360, 500)
        self.diagram.show()
        self.diagram.grab()
        art = self.diagram._draw_rect()
        for button_id, card in self.diagram._callout_rects.items():
            self.assertFalse(card.intersects(art), button_id)

    def test_set_bindings_updates_the_hotspot_accessible_name(self):
        from g7ctlc.controller_diagram import UNMAPPED_CALLOUT_TEXT

        self.diagram.set_bindings({"a": "Keyboard: R"})
        self.assertIn("remapped to Keyboard: R", self.diagram.hotspot_for("a").accessibleName())
        self.assertIn(UNMAPPED_CALLOUT_TEXT.lower(), self.diagram.hotspot_for("b").accessibleName())

    def test_hovering_a_callout_shows_a_tooltip_without_raising(self):
        # A tooltip event carries its position as a QPoint, where mouse events
        # carry a QPointF; handing it straight to QRectF.contains() raised a
        # TypeError that only showed up when the cursor rested on a callout.
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QHelpEvent
        from PyQt6.QtWidgets import QToolTip

        self.diagram.resize(900, 700)
        self.diagram.show()
        self.diagram.grab()
        inside = self.diagram._callout_rects["a"].center().toPoint()
        self.assertEqual(self.diagram._callout_at(inside), "a")
        event = QHelpEvent(QEvent.Type.ToolTip, inside, self.diagram.mapToGlobal(inside))
        self.assertTrue(self.diagram.event(event))
        # The middle of the widget is the artwork, not a callout: it must look
        # up as "no callout" and fall through to the normal tooltip handling.
        outside = self.diagram.rect().center()
        self.assertIsNone(self.diagram._callout_at(outside))
        event = QHelpEvent(QEvent.Type.ToolTip, outside, self.diagram.mapToGlobal(outside))
        self.diagram.event(event)
        # A tooltip left open when the interpreter exits crashes it on teardown.
        QToolTip.hideText()

    def test_clicking_a_callout_activates_its_control_without_a_new_tab_stop(self):
        self.diagram.resize(900, 700)
        self.diagram.show()
        self.diagram.grab()
        original_hotspots = set(self.diagram._hotspots)
        received = []
        self.diagram.activated.connect(received.append)
        QTest.mouseClick(
            self.diagram,
            Qt.MouseButton.LeftButton,
            pos=self.diagram._callout_rects["a"].center().toPoint(),
        )
        self.assertEqual(received, ["a"])
        self.assertEqual(set(self.diagram._hotspots), original_hotspots)

    def test_paints_without_raising_with_bindings_set(self):
        # Mirrors test_paints_without_raising_with_a_highlight_active --
        # exercises the actual callout-painting path, not just the data.
        self.diagram.set_bindings({"a": "Keyboard: R", "rb": "Not remapped"})
        pixmap = self.diagram.grab()
        self.assertFalse(pixmap.isNull())


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
        # Real flake, caught adding the diagram hotspots: show() posts a
        # deferred "window active, focus the first focusable child" event
        # that a test's own later processEvents() call can pick up at the
        # wrong moment (after a .click() already set a different
        # highlight), clobbering it back to whichever hotspot is first in
        # tab order. Settle that deferred focus here, once, before any
        # test body runs -- a real user never interacts with a window in
        # the same instant it's shown, so this isn't masking a product
        # bug, just a synthetic-test timing artifact.
        self.app.processEvents()

    def tearDown(self):
        # KeycodePicker is a Qt.WindowType.Popup -- an open one left over
        # from a test that opened it without going through the real
        # selection path (e.g. emitting codeChosen directly) holds an
        # implicit input grab that pollutes every later test in the
        # process, not just this class. Real bug caught writing these
        # tests: test_clicking_a_field_also_highlights_its_button failed
        # with the wrong button id only when run after a picker-opening
        # test, never in isolation.
        self.view._picker.close()

    def test_clicking_a_hotspot_highlights_its_button(self):
        QTest.mouseClick(self.view.diagram.hotspot_for("y"), Qt.MouseButton.LeftButton)
        self.assertEqual(self.view.diagram._highlighted, "y")

    def test_set_palette_reaches_the_diagram(self):
        self.view.set_palette(LIGHT_PALETTE)
        self.assertIs(self.view.diagram._palette, LIGHT_PALETTE)

    # -- D2 rework: the diagram is the remapping surface, not an echo ----

    def test_activating_a_hotspot_opens_the_shared_picker_for_that_button(self):
        self.view.load_state({"buttons": {"default": {"y": "r"}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("y"), Qt.MouseButton.LeftButton)
        self.assertTrue(self.view._picker.isVisible())
        self.assertEqual(self.view._active_button, "y")
        self.assertEqual(self.view._picker._current_value, "r")

    def test_activating_a_hotspot_on_the_shift_screen_opens_the_shift_value(self):
        self.view.load_state({"buttons": {"default": {}, "shift": {"y": "e"}}})
        self.view.set_layer("shift")
        QTest.mouseClick(self.view.diagram.hotspot_for("y"), Qt.MouseButton.LeftButton)
        self.assertEqual(self.view._picker._current_value, "e")

    def test_choosing_a_value_from_a_diagram_opened_picker_updates_state(self):
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("y"), Qt.MouseButton.LeftButton)
        self.view._picker.codeChosen.emit("r")
        self.assertEqual(self.view._state["buttons"]["default"]["y"], "r")

    def test_load_state_feeds_remapped_buttons_to_the_diagram_as_callouts(self):
        from g7ctlc.widgets import keycode_display_text

        state = {"buttons": {"default": {"y": "r"}, "shift": {}}}
        self.view.load_state(state)
        self.assertEqual(self.view.diagram._bindings["y"], keycode_display_text("r"))
        self.assertNotIn("a", self.view.diagram._bindings)

    def test_switching_to_shift_shows_shift_bindings_instead_of_default(self):
        from g7ctlc.widgets import keycode_display_text

        state = {"buttons": {"default": {"y": "r"}, "shift": {"a": "e"}}}
        self.view.load_state(state)
        self.view.set_layer("shift")
        self.assertNotIn("y", self.view.diagram._bindings)
        self.assertEqual(self.view.diagram._bindings["a"], keycode_display_text("e"))

    def test_choosing_a_value_refreshes_the_diagram_callout(self):
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        self.assertNotIn("y", self.view.diagram._bindings)
        QTest.mouseClick(self.view.diagram.hotspot_for("y"), Qt.MouseButton.LeftButton)
        self.view._picker.codeChosen.emit("r")
        self.assertIn("y", self.view.diagram._bindings)

    # -- Latch, folded into the picker (2026-10-22, decision after a
    # hands-on test drive: drop the side panel, nest Latch in the picker
    # rather than keep a second surface for it) --------------------------

    def test_activating_a_latch_capable_button_shows_the_checkbox(self):
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("rb"), Qt.MouseButton.LeftButton)
        self.assertTrue(self.view._picker.latch_row.isVisible())
        self.assertTrue(self.view._picker.latch_checkbox.isVisible())

    def test_activating_a_trigger_shows_the_reason_text_instead(self):
        # LT/RT have no Continuous Trigger byte at all -- see
        # pyg7.buttons.continuous_trigger_offset().
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("lt"), Qt.MouseButton.LeftButton)
        self.assertFalse(self.view._picker.latch_checkbox.isVisible())
        self.assertEqual(
            self.view._picker.latch_reason_label.text(), "Triggers have no latch setting")

    def test_activating_on_the_shift_screen_hides_the_latch_row_entirely(self):
        # Latch is Base-layer-only, and "rb" supports it on the Base layer
        # -- the Shift screen must still show no Latch row for it at all,
        # not just hide the checkbox.
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        self.view.set_layer("shift")
        QTest.mouseClick(self.view.diagram.hotspot_for("rb"), Qt.MouseButton.LeftButton)
        self.assertFalse(self.view._picker.latch_row.isVisible())

    def test_the_checkbox_opens_pre_checked_to_match_state(self):
        self.view.load_state({"buttons": {"default": {}, "shift": {}},
                               "continuous_trigger": {"rb": True}})
        QTest.mouseClick(self.view.diagram.hotspot_for("rb"), Qt.MouseButton.LeftButton)
        self.assertTrue(self.view._picker.latch_checkbox.isChecked())

    def test_toggling_the_checkbox_updates_state(self):
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("rb"), Qt.MouseButton.LeftButton)
        self.view._picker.latch_checkbox.setChecked(True)
        self.assertTrue(self.view._state["continuous_trigger"]["rb"])

    def test_toggling_the_checkbox_does_not_close_the_picker(self):
        # Independent of choosing a code -- a user may want to do both in
        # the same visit (module docstring).
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("rb"), Qt.MouseButton.LeftButton)
        self.view._picker.latch_checkbox.setChecked(True)
        self.assertTrue(self.view._picker.isVisible())

    def test_the_latch_checkbox_and_reason_label_carry_their_explanations(self):
        from g7ctlc.views.buttons_view import _LATCH_TOOLTIP

        self.assertEqual(self.view._picker.latch_checkbox.toolTip(), _LATCH_TOOLTIP)
        self.assertTrue(self.view._picker.latch_reason_label.toolTip())

    def test_the_shared_checkbox_announces_which_button_its_for(self):
        # One checkbox now, not one per button (module docstring) -- a
        # screen reader needs it to keep saying which button, the same
        # way the old per-row checkbox said "RB, Latch".
        self.view.load_state({"buttons": {"default": {}, "shift": {}}})
        QTest.mouseClick(self.view.diagram.hotspot_for("rb"), Qt.MouseButton.LeftButton)
        self.assertEqual(self.view._picker.latch_checkbox.accessibleName(), "RB, Latch")
        QTest.mouseClick(self.view.diagram.hotspot_for("lb"), Qt.MouseButton.LeftButton)
        self.assertEqual(self.view._picker.latch_checkbox.accessibleName(), "LB, Latch")


if __name__ == "__main__":
    unittest.main()
