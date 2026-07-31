"""GUI tests for the one thing the GUI can silently destroy: bindings.

The Buttons tab writes back to the shared state dict by sweeping EVERY combo
on any edit, not just the one that changed. That makes "the picker cannot
represent this value" equivalent to "this binding is deleted" -- which is
exactly how a set of newly-discovered keycodes went missing after being added
to the protocol layer but not to the picker.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent so
the protocol-library tests stay runnable without Qt installed.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7.buttons import KNOWN_KEYCODES


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class KeycodeCoverageTest(unittest.TestCase):
    def test_every_known_keycode_is_selectable(self):
        """The guard that would have caught the original bug.

        If a keycode exists in the protocol layer but not in the picker, a
        device using it renders as "(Unbound)" and is then dropped from the
        state dict by the next unrelated edit.
        """
        from g7ctlc.widgets import KEYCODE_GROUPS, _NOT_SELECTABLE
        listed = {name for _label, entries in KEYCODE_GROUPS for name, _short in entries}
        unreachable = sorted(set(KNOWN_KEYCODES) - listed - set(_NOT_SELECTABLE))
        self.assertEqual(unreachable, [], "keycodes unreachable from the GUI picker")

    def test_picker_lists_no_phantom_keycodes(self):
        from g7ctlc.widgets import KEYCODE_GROUPS
        listed = {name for _label, entries in KEYCODE_GROUPS for name, _short in entries}
        self.assertEqual(sorted(listed - set(KNOWN_KEYCODES)), [])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsViewRoundTripTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with(self, bindings):
        from pyg7 import state as state_mod
        from g7ctlc.views.buttons_view import ButtonsView
        state = state_mod.default_state_dict("test")
        state["buttons"]["default"].update(bindings)
        view = ButtonsView()
        view.load_state(state)
        return view, state

    def test_named_keycodes_survive_an_unrelated_edit(self):
        bindings = {"l4": "mouse_button4", "r4": "numpad_enter",
                    "share": "native_share_capture", "a": "f11"}
        view, state = self._view_with(bindings)
        combo = view._combos[("a", "default")]
        combo.setCurrentIndex(combo.findData("f12"))
        for button, expected in bindings.items():
            if button == "a":
                continue
            self.assertEqual(state["buttons"]["default"].get(button), expected,
                             f"{button} was lost after editing an unrelated button")

    def test_unnamed_raw_hex_keycodes_survive_an_unrelated_edit(self):
        # These used to be values real hardware returns on a factory-default
        # profile with no name yet -- all four got named 2026-07-30 (see
        # PROTOCOL.md "Keycodes"), so synthetic values guaranteed to
        # stay outside KNOWN_KEYCODES are used instead, to keep exercising
        # this code path.
        bindings = {"l4": "0xab", "r4": "0xac", "l5": "0xad", "r5": "0xae", "a": "f11"}
        view, state = self._view_with(bindings)
        combo = view._combos[("a", "default")]
        combo.setCurrentIndex(combo.findData("f12"))
        for button, expected in bindings.items():
            if button == "a":
                continue
            self.assertEqual(state["buttons"]["default"].get(button), expected,
                             f"{button} lost its unnamed keycode")

    def test_deliberate_unbind_still_works(self):
        # The flip side: selecting "(Unbound)" must genuinely clear it.
        view, state = self._view_with({"a": "f11"})
        combo = view._combos[("a", "default")]
        combo.setCurrentIndex(combo.findData(None))
        self.assertIsNone(state["buttons"]["default"].get("a"))

    def test_every_known_button_has_a_row(self):
        from pyg7.buttons import KNOWN_BUTTON_IDS
        view, _state = self._view_with({})
        shown = {button for button, _layer in view._combos}
        self.assertEqual(shown, set(KNOWN_BUTTON_IDS))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class SticksDirectionBindingsTest(unittest.TestCase):
    """Direction Bindings (Sticks tab, Directional Buttons output mode) uses
    the same make_keycode_combo()/select_by_data() machinery as the Buttons
    tab -- the same bug class applies: an unnamed raw-hex keycode must
    survive an edit to an unrelated field, since _StickSideWidget.save_into()
    rebuilds direction_bindings from all five combos on any change, not just
    the one that was actually edited.
    """

    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with(self, direction_bindings):
        from pyg7 import state as state_mod
        from g7ctlc.views.sticks_view import SticksView
        state = state_mod.default_state_dict("test")
        am = state["sticks"]["left"]["advanced_mapping"]
        am["output_mode"] = "directional"
        am["direction_bindings"] = direction_bindings
        view = SticksView()
        view.load_state(state)
        return view, state

    def test_unnamed_raw_hex_binding_survives_an_unrelated_edit(self):
        # 0xab is guaranteed to stay outside KNOWN_KEYCODES (unlike 0x11,
        # which named "native_l4" 2026-07-30 -- see PROTOCOL.md
        # "Keycodes"), so this keeps exercising the "unrecognised value" path.
        bindings = {"up": "0xab", "down": "w", "left": "a", "right": "d", "ring": "shift"}
        view, state = self._view_with(bindings)
        left = view.sides["left"]
        left.dz_initial.setValue(42)  # unrelated edit -- not a direction combo
        saved = state["sticks"]["left"]["advanced_mapping"]["direction_bindings"]
        self.assertEqual(saved, bindings)

    def test_a_direction_binding_can_be_cleared(self):
        bindings = {"up": "w", "down": "s", "left": "a", "right": "d", "ring": "shift"}
        view, state = self._view_with(bindings)
        left = view.sides["left"]
        combo = left.direction_combos["up"]
        combo.setCurrentIndex(combo.findData(None))
        saved = state["sticks"]["left"]["advanced_mapping"]["direction_bindings"]
        self.assertIsNone(saved["up"])
        self.assertEqual(saved["down"], "s")  # untouched zones still present


if __name__ == "__main__":
    unittest.main()
