"""GUI tests for the one thing the GUI can silently destroy: bindings.

Historically the Buttons tab wrote back to the shared state dict by
sweeping EVERY combo on any edit, not just the one that changed -- that
made "the picker cannot represent this value" equivalent to "this
binding is deleted," exactly how a set of newly-discovered keycodes went
missing after being added to the protocol layer but not to the picker.
D2's rework (2026-10-22, decision) replaced that whole per-button
widget layer with direct edits through the diagram + a shared picker --
there's nothing left to sweep, each edit writes only the one key it
changed -- but the underlying hazard this file guards (the picker must
offer every real keycode, and an edit must never disturb an unrelated
binding) is unchanged, so these tests stay, driven through the new path.

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
        from g7ctlc.widgets import _NOT_SELECTABLE, KEYCODE_GROUPS
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
        from g7ctlc.views.buttons_view import ButtonsView
        from pyg7 import state as state_mod
        state = state_mod.default_state_dict("test")
        state["buttons"]["default"].update(bindings)
        view = ButtonsView()
        view.load_state(state)
        return view, state

    def _edit(self, view, button_id, value, *, layer="default"):
        """Drives a real edit through the actual interaction path (diagram
        activation opens the picker, codeChosen writes state) -- D2's
        rework (2026-10-22, decision) replaced the old per-button
        BindingField/_combos shape entirely, so there is no widget left to
        call set_value() on directly."""
        view.set_layer(layer)
        view._on_diagram_activated(button_id)
        view._picker.codeChosen.emit(value)

    def test_named_keycodes_survive_an_unrelated_edit(self):
        bindings = {"l4": "mouse_button4", "r4": "numpad_enter",
                    "share": "native_share_capture", "a": "f11"}
        view, state = self._view_with(bindings)
        self._edit(view, "a", "f12")
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
        self._edit(view, "a", "f12")
        for button, expected in bindings.items():
            if button == "a":
                continue
            self.assertEqual(state["buttons"]["default"].get(button), expected,
                             f"{button} lost its unnamed keycode")

    def test_deliberate_default_reset_stores_explicit_none_not_a_missing_key(self):
        # The flip side: selecting "(Default)" must genuinely register as a
        # reset, not just look like one.
        #
        # REAL BUG, found 2026-09-17 (two independent
        # code reviews): this test used to assert only
        # `assertIsNone(state["buttons"]["default"].get("a"))`, which passes
        # identically whether "a" is present with value None OR missing from
        # the dict entirely -- so it kept passing right through the actual
        # bug (the old combo-sweep popped the key on Default instead of
        # storing None), masking it instead of catching it. Strengthened to
        # assert key presence, which the old buggy code fails and the fix
        # passes.
        view, state = self._view_with({"a": "f11"})
        self._edit(view, "a", None)
        self.assertIn("a", state["buttons"]["default"],
                       "Default must store an explicit reset, not remove the key")
        self.assertIsNone(state["buttons"]["default"]["a"])

    def test_default_reset_emits_a_real_unbind_write(self):
        # The actual end-to-end consequence of the bug above: without an
        # explicit None in the state dict, _build_steps() -- which only
        # visits keys that exist -- never saw the reset and scheduled no
        # unbind() at all, so the old hardware binding stayed live even
        # though Sync reported success.
        from pyg7 import state as state_mod
        view, state = self._view_with({"a": "f11"})
        self._edit(view, "a", None)
        # A real device baseline where "a" was previously bound to f11 --
        # decode_button_table()'s real shape, not a synthetic shortcut.
        baseline = state_mod.default_state_dict("baseline")
        baseline["buttons"]["default"]["a"] = "f11"
        steps, _skipped = state_mod._build_steps(state, baseline)
        labels = [label for label, _fn in steps]
        self.assertTrue(any("unbind" in label.lower() for label in labels),
                         f"expected an unbind step for button 'a', got: {labels}")

    def test_button_left_at_default_the_whole_time_emits_no_write(self):
        from pyg7 import state as state_mod
        view, state = self._view_with({"a": "f11"})
        self._edit(view, "a", "f12")  # edit a DIFFERENT value on "a"
        # "b" was never configured on this device either side -- both state
        # and baseline should agree it's None, matching decode_button_table()'s
        # real shape (an unconfigured slot decodes to None, not a missing key).
        baseline = state_mod.default_state_dict("baseline")
        baseline["buttons"]["default"]["a"] = "f11"
        baseline["buttons"]["default"]["b"] = None
        steps, _skipped = state_mod._build_steps(state, baseline)
        labels = [label for label, _fn in steps]
        self.assertFalse(any("Button b " in label for label in labels),
                          f"button 'b' was never touched and should generate no write, got: {labels}")

    def test_every_known_button_is_reachable_on_the_diagram(self):
        from pyg7.buttons import KNOWN_BUTTON_IDS
        view, _state = self._view_with({})
        self.assertEqual(set(view.diagram._hotspots), set(KNOWN_BUTTON_IDS))

    def _view_for_profile(self, slot, shift_bindings=None):
        from g7ctlc.views.buttons_view import ButtonsView
        from pyg7 import state as state_mod
        state = state_mod.default_state_dict("test")
        state["controller_slot"] = slot
        if shift_bindings:
            state["buttons"]["shift"].update(shift_bindings)
        view = ButtonsView()
        view.load_state(state)
        return view, state

    def test_default_layer_is_shown_by_default(self):
        """A freshly-constructed view must already be editing the Default
        layer -- D2's rework (2026-10-22) dropped the old column-visibility
        UI entirely, so `_layer` itself is the thing worth asserting now."""
        view, _state = self._view_for_profile(1)
        self.assertEqual(view._layer, "default")

    def test_set_layer_switches_which_layer_is_edited(self):
        """The Shift layer is device-global, so it lives behind its own
        entry in the selector rather than a per-profile column -- a global
        layer sitting in a per-profile screen is what made it look
        profile-scoped in the first place."""
        view, state = self._view_for_profile(1)
        view.set_layer("shift")
        self.assertEqual(view._layer, "shift")
        self._edit(view, "a", "f11", layer="shift")
        self.assertEqual(state["buttons"]["shift"]["a"], "f11")
        self.assertNotIn("a", state["buttons"]["default"])
        view.set_layer("default")
        self.assertEqual(view._layer, "default")

    def test_dpad_options_hide_on_the_shift_screen(self):
        """They are profile-scoped and cannot be written to the Shift blob."""
        view, _state = self._view_for_profile(1)
        view.set_layer("shift")
        self.assertFalse(view.swap_stick_dpad.isVisibleTo(view))
        self.assertFalse(view.dpad_diagonal_lock.isVisibleTo(view))
        view.set_layer("default")
        self.assertTrue(view.swap_stick_dpad.isVisibleTo(view))

    def test_editing_one_layer_does_not_touch_the_other(self):
        from pyg7 import state as state_mod
        view, state = self._view_for_profile(1)
        state["buttons"]["shift"]["y"] = "numpad1"
        state["buttons"]["default"]["a"] = "f11"
        view.load_state(state)
        self._edit(view, "y", "numpad3", layer="shift")
        self.assertEqual(state["buttons"]["shift"]["y"], "numpad3")
        self.assertEqual(state["buttons"]["default"]["a"], "f11",
                         "editing the Shift layer touched the hidden Default layer")
        state_mod.validate_state(state)

    def test_shift_bindings_survive_a_profile_that_is_not_1(self):
        """They used to be dropped on load for Profiles 2-4. The Shift layer
        is shared, so those bindings are real wherever they were read."""
        view, state = self._view_for_profile(3, {"a": "f11"})
        self.assertEqual(state["buttons"]["shift"].get("a"), "f11")
        view.set_layer("shift")
        self.assertIn("a", view.diagram._bindings)


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
        from g7ctlc.views.sticks_view import SticksView
        from pyg7 import state as state_mod
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
        field = left.direction_combos["up"]
        field.set_value(None)
        left._emit_changed()
        saved = state["sticks"]["left"]["advanced_mapping"]["direction_bindings"]
        self.assertIsNone(saved["up"])
        self.assertEqual(saved["down"], "s")  # untouched zones still present


if __name__ == "__main__":
    unittest.main()
