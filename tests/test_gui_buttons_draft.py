"""ButtonsView's S6 per-field draft slice (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the seventh slice, and the hardest
fit: this page has no per-field widget at all, so the touch/revert UI
lives inside KeycodePicker's own was/Revert row (see buttons_view.py's
own module docstring) instead of a wrapped form field, plus the two
D-pad options (plain checkboxes, the ordinary wrap-the-widget pattern).
Latch/Continuous Trigger is deliberately out of scope -- see the module
docstring for why.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod
from pyg7.field_spec import BUTTON_FIELDS, DPAD_FIELDS, Intent


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsFieldTouchedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, **overrides):
        from g7ctlc.views.buttons_view import ButtonsView

        state = state_mod.default_state_dict("test")
        state["controller_slot"] = 2
        state["buttons"].setdefault("default", {})["a"] = "native_a"
        state.update(overrides)
        view = ButtonsView()
        view.load_state(state)
        return view, state

    def test_picking_a_real_keycode_emits_fieldTouched_with_the_right_path_field_and_profile(self):
        view, state = self._view_with_state()
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")

        self.assertEqual(len(touches), 1)
        path, field, desired, profile = touches[0]
        self.assertEqual(path, ("buttons", "default", "a"))
        self.assertIs(field, BUTTON_FIELDS["default"]["a"])
        self.assertEqual(desired, "native_x")
        self.assertEqual(profile, 2)
        self.assertEqual(state["buttons"]["default"]["a"], "native_x")

    def test_picking_default_unbind_emits_Intent_CLEAR_not_raw_none(self):
        view, state = self._view_with_state()
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view._on_diagram_activated("a")
        view._on_code_chosen(None)  # the picker's own "(Default)" choice

        self.assertEqual(len(touches), 1)
        _path, _field, desired, _profile = touches[0]
        self.assertIs(desired, Intent.CLEAR)
        self.assertIsNone(state["buttons"]["default"]["a"])

    def test_shift_layer_touch_uses_the_shift_path_and_field(self):
        view, state = self._view_with_state()
        state["buttons"].setdefault("shift", {})["b"] = "native_b"
        view.load_state(state)
        view.set_layer("shift")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view._on_diagram_activated("b")
        view._on_code_chosen("native_y")

        self.assertEqual(len(touches), 1)
        path, field, desired, _profile = touches[0]
        self.assertEqual(path, ("buttons", "shift", "b"))
        self.assertIs(field, BUTTON_FIELDS["shift"]["b"])
        self.assertEqual(desired, "native_y")

    def test_opening_the_picker_for_an_untouched_button_passes_no_was_text(self):
        view, state = self._view_with_state()
        calls = []
        real_open_for = view._picker.open_for
        view._picker.open_for = lambda *a, **kw: (calls.append(kw.get("was_text")), real_open_for(*a, **kw))[-1]

        view._on_diagram_activated("a")

        self.assertEqual(calls, [None])

    def test_opening_the_picker_for_a_touched_button_passes_was_text(self):
        view, state = self._view_with_state()  # "a" loaded as "native_a"
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")

        calls = []
        real_open_for = view._picker.open_for
        view._picker.open_for = lambda *a, **kw: (calls.append(kw.get("was_text")), real_open_for(*a, **kw))[-1]
        view._on_diagram_activated("a")

        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(calls[0])
        self.assertIn("Native: A", calls[0])

    def test_revert_restores_the_loaded_value_and_clears_the_touch(self):
        view, state = self._view_with_state()
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        view._on_revert_requested()

        self.assertEqual(state["buttons"]["default"]["a"], "native_a")
        self.assertEqual(reverted, [("buttons", "default", "a")])
        self.assertNotIn(("default", "a"), view._touched)

    def test_revert_to_a_genuinely_unbound_baseline_restores_none(self):
        view, state = self._view_with_state()
        state["buttons"]["default"]["b"] = None
        view.load_state(state)
        view._on_diagram_activated("b")
        view._on_code_chosen("native_x")

        view._on_revert_requested()

        self.assertIsNone(state["buttons"]["default"]["b"])

    def test_revert_does_not_itself_re_fire_fieldTouched(self):
        view, state = self._view_with_state()
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))
        view._on_revert_requested()
        self.assertEqual(touches, [])

    def test_a_fresh_load_state_clears_every_touch(self):
        view, state = self._view_with_state()
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")
        self.assertIn(("default", "a"), view._touched)

        state2 = state_mod.default_state_dict("test2")
        view.load_state(state2)

        self.assertEqual(view._touched, set())

    def test_touched_button_callout_gets_an_unwritten_suffix(self):
        view, state = self._view_with_state()
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")
        self.assertIn("(unwritten)", view.diagram._bindings["a"])

    def test_touched_unbound_button_still_shows_a_callout(self):
        """A pending unbind (desired=None) must not look identical to an
        already-synced empty slot -- the old `value is not None` filter
        alone would hide it entirely."""
        view, state = self._view_with_state()
        view._on_diagram_activated("a")
        view._on_code_chosen(None)
        self.assertIn("a", view.diagram._bindings)
        self.assertIn("(unwritten)", view.diagram._bindings["a"])

    def test_untouched_button_callout_has_no_suffix(self):
        view, state = self._view_with_state()
        view._refresh_diagram_bindings()
        self.assertNotIn("(unwritten)", view.diagram._bindings.get("a", ""))

    def test_manually_picking_back_to_the_loaded_binding_acts_as_an_implicit_revert(self):
        """REAL BUG, reported 2026-10-26: after binding button B to Native A,
        manually choosing B again from the picker left the "revert change"
        row showing while Write correctly reported that all fields
        match -- picking the
        SAME value the field was loaded with (not clicking Revert) left
        the diagram's "(unwritten)" suffix and the draft ledger both
        still claiming an outstanding edit."""
        view, state = self._view_with_state()  # "a" loaded as "native_a"
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")
        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))

        view._on_diagram_activated("a")
        view._on_code_chosen("native_a")  # back to the loaded value, not Revert

        self.assertEqual(reverted, [("buttons", "default", "a")])
        self.assertNotIn(("default", "a"), view._touched)
        self.assertNotIn("(unwritten)", view.diagram._bindings.get("a", ""))

    def test_picking_default_back_to_an_already_unbound_baseline_acts_as_an_implicit_revert(self):
        view, state = self._view_with_state()
        state["buttons"]["default"]["b"] = None
        view.load_state(state)
        view._on_diagram_activated("b")
        view._on_code_chosen("native_x")
        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))

        view._on_diagram_activated("b")
        view._on_code_chosen(None)  # back to the genuinely-unbound baseline

        self.assertEqual(reverted, [("buttons", "default", "b")])
        self.assertNotIn(("default", "b"), view._touched)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ButtonsDpadOptionTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, **overrides):
        from g7ctlc.views.buttons_view import ButtonsView

        state = state_mod.default_state_dict("test")
        state["controller_slot"] = 3
        state.update(overrides)
        view = ButtonsView()
        view.load_state(state)
        return view, state

    def test_toggling_swap_stick_dpad_emits_fieldTouched(self):
        view, state = self._view_with_state(swap_stick_dpad=False)
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.swap_stick_dpad.setChecked(True)

        self.assertEqual(len(touches), 1)
        path, field, desired, profile = touches[0]
        self.assertEqual(path, ("swap_stick_dpad",))
        self.assertIs(field, DPAD_FIELDS["swap_stick_dpad"])
        self.assertTrue(desired)
        self.assertEqual(profile, 3)

    def test_mark_and_revert_appear_only_after_a_real_touch(self):
        view, state = self._view_with_state(dpad_diagonal_lock=False)
        self.assertTrue(view._dpad_was_labels["dpad_diagonal_lock"].isHidden())
        self.assertTrue(view._dpad_revert_buttons["dpad_diagonal_lock"].isHidden())

        view.dpad_diagonal_lock.setChecked(True)

        self.assertFalse(view._dpad_was_labels["dpad_diagonal_lock"].isHidden())
        self.assertIn("Off", view._dpad_was_labels["dpad_diagonal_lock"].text())
        self.assertFalse(view._dpad_revert_buttons["dpad_diagonal_lock"].isHidden())

    def test_revert_restores_the_loaded_value(self):
        view, state = self._view_with_state(dpad_diagonal_lock=False)
        view.dpad_diagonal_lock.setChecked(True)

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        view._revert_dpad_setting("dpad_diagonal_lock")

        self.assertFalse(view.dpad_diagonal_lock.isChecked())
        self.assertFalse(state["dpad_diagonal_lock"])
        self.assertTrue(view._dpad_was_labels["dpad_diagonal_lock"].isHidden())
        self.assertEqual(reverted, [("dpad_diagonal_lock",)])

    def test_moving_one_dpad_option_does_not_touch_the_other(self):
        view, state = self._view_with_state(swap_stick_dpad=False, dpad_diagonal_lock=False)
        view.swap_stick_dpad.setChecked(True)
        self.assertFalse(view.dpad_diagonal_lock.is_edited())

    def test_shift_layer_hides_the_whole_dpad_row_not_just_the_checkbox(self):
        view, state = self._view_with_state()
        view.set_layer("shift")
        self.assertTrue(view._dpad_row_widgets["swap_stick_dpad"].isHidden())
        self.assertTrue(view._dpad_row_widgets["dpad_diagonal_lock"].isHidden())

    def test_manually_toggling_back_to_the_loaded_value_acts_as_an_implicit_revert(self):
        """Same real bug as for button bindings, seen on D-Pad options (2026-10-26) -- toggling a D-pad
        option back to its loaded value (not clicking Revert) left the
        mark/revert row and the draft ledger both still claiming an
        outstanding edit."""
        view, state = self._view_with_state(dpad_diagonal_lock=False)
        view.dpad_diagonal_lock.setChecked(True)
        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))

        view.dpad_diagonal_lock.setChecked(False)  # back to the loaded value, not Revert

        self.assertEqual(reverted, [("dpad_diagonal_lock",)])
        self.assertTrue(view._dpad_was_labels["dpad_diagonal_lock"].isHidden())
        self.assertFalse(view.dpad_diagonal_lock.is_edited())

    def test_revert_all_discards_an_inactive_button_binding_and_a_dpad_option(self):
        """Scope-level "Discard changes" -- deliberately touches a button
        whose picker is NOT the currently-open one (self._active_button
        stays on "a" throughout), since this page's own per-field
        Revert only ever reverts _active_button -- revert_all() must
        not share that limitation."""
        view, state = self._view_with_state()
        state["buttons"].setdefault("default", {})["a"] = "native_a"
        state["buttons"]["default"]["b"] = "native_b"
        view.load_state(state)
        view._on_diagram_activated("a")
        view._on_code_chosen("native_x")  # "a" becomes the active button, touched
        state["buttons"]["default"]["b"] = "native_y"
        view._mark_button_touched("default", "b", "native_y")  # "b" touched without ever being active
        view.dpad_diagonal_lock.setChecked(not view.dpad_diagonal_lock.isChecked())
        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))

        view.revert_all()

        self.assertEqual(set(reverted), {
            ("buttons", "default", "a"), ("buttons", "default", "b"), ("dpad_diagonal_lock",),
        })
        self.assertEqual(state["buttons"]["default"]["a"], "native_a")
        self.assertEqual(state["buttons"]["default"]["b"], "native_b")
        self.assertEqual(view._touched, set())
        self.assertEqual(view._dpad_touched, set())
        self.assertTrue(view._dpad_was_labels["dpad_diagonal_lock"].isHidden())

    def test_revert_path_reverts_an_inactive_button_binding_by_full_path(self):
        """ReviewSheet's own per-row Revert (IMPLEMENTATION-PLAN.md's
        "Not started" list, item 3) -- same "doesn't need
        self._active_button" reasoning as revert_all()'s own test."""
        view, state = self._view_with_state()
        state["buttons"].setdefault("default", {})["a"] = "native_a"
        state["buttons"]["default"]["b"] = "native_b"
        view.load_state(state)
        state["buttons"]["default"]["b"] = "native_y"
        view._mark_button_touched("default", "b", "native_y")

        found = view.revert_path(("buttons", "default", "b"))

        self.assertTrue(found)
        self.assertEqual(state["buttons"]["default"]["b"], "native_b")
        self.assertEqual(view._touched, set())
        self.assertFalse(view.revert_path(("buttons", "default", "b")))  # already reverted

    def test_revert_path_reverts_a_dpad_option_by_full_path(self):
        view, state = self._view_with_state(dpad_diagonal_lock=False)
        view.dpad_diagonal_lock.setChecked(True)

        found = view.revert_path(("dpad_diagonal_lock",))

        self.assertTrue(found)
        self.assertFalse(view.dpad_diagonal_lock.isChecked())


if __name__ == "__main__":
    unittest.main()
