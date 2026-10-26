"""SettingsView's S6 per-field draft slice (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the Dock page's second slice onto the
real per-field draft model, both fields fully migrated (no CoupledFieldSpec
gap, unlike Vibration's Force/Sync flags).
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from pyg7 import state as state_mod
from pyg7.field_spec import DOCK_FIELDS


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class DockFieldTouchedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_state(self, **overrides):
        from g7ctlc.views.settings_view import SettingsView

        state = state_mod.default_state_dict("test")
        state.update(overrides)
        view = SettingsView()
        view.load_state(state)
        return view, state

    def test_moving_brightness_emits_fieldTouched(self):
        view, state = self._view_with_state(dock_led_brightness=25)
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.brightness.set_value("100")

        self.assertGreaterEqual(len(touches), 1)
        for path, field, desired, _profile in touches:
            self.assertEqual(path, ("dock_led_brightness",))
            self.assertIs(field, DOCK_FIELDS["dock_led_brightness"])
            self.assertEqual(desired, 100)

    def test_brightness_mark_and_revert_appear_only_after_a_real_touch(self):
        view, state = self._view_with_state(dock_led_brightness=25)
        self.assertTrue(view._brightness_was_label.isHidden())
        view.brightness.set_value("100")
        self.assertFalse(view._brightness_was_label.isHidden())
        self.assertIn("25", view._brightness_was_label.text())
        self.assertFalse(view._brightness_revert_btn.isHidden())
        self.assertTrue(view.brightness.is_edited())

    def test_revert_brightness_restores_the_loaded_value(self):
        view, state = self._view_with_state(dock_led_brightness=25)
        view.brightness.set_value("100")

        reverted = []
        view.fieldReverted.connect(lambda path: reverted.append(path))
        view._revert_brightness()

        self.assertEqual(view.brightness.value(), "25")
        self.assertEqual(state["dock_led_brightness"], 25)
        self.assertTrue(view._brightness_was_label.isHidden())
        self.assertFalse(view.brightness.is_edited())
        self.assertEqual(reverted, [("dock_led_brightness",)])

    def test_toggling_auto_on_off_emits_fieldTouched(self):
        view, state = self._view_with_state(dock_auto_on_off=False)
        touches = []
        view.fieldTouched.connect(lambda *a: touches.append(a))

        view.auto_on_off.setChecked(True)

        self.assertEqual(len(touches), 1)
        path, field, desired, profile = touches[0]
        self.assertEqual(path, ("dock_auto_on_off",))
        self.assertIs(field, DOCK_FIELDS["dock_auto_on_off"])
        self.assertTrue(desired)

    def test_revert_auto_on_off_restores_the_loaded_value(self):
        view, state = self._view_with_state(dock_auto_on_off=False)
        view.auto_on_off.setChecked(True)

        view._revert_auto_on_off()

        self.assertFalse(view.auto_on_off.isChecked())
        self.assertFalse(state["dock_auto_on_off"])
        self.assertTrue(view._auto_was_label.isHidden())
        self.assertFalse(view.auto_on_off.is_edited())

    def test_a_fresh_load_state_clears_every_mark(self):
        view, state = self._view_with_state(dock_led_brightness=25, dock_auto_on_off=False)
        view.brightness.set_value("100")
        view.auto_on_off.setChecked(True)

        state2 = state_mod.default_state_dict("test2")
        view.load_state(state2)

        self.assertTrue(view._brightness_was_label.isHidden())
        self.assertTrue(view._auto_was_label.isHidden())
        self.assertFalse(view.brightness.is_edited())
        self.assertFalse(view.auto_on_off.is_edited())

    def test_unknown_observed_brightness_shows_as_unknown(self):
        # None's own nearest stop is 100 (_nearest_brightness_index's
        # documented default), so moving TO "100" would be a same-value
        # Qt no-op that never fires selectionChanged -- move away instead.
        view, state = self._view_with_state(dock_led_brightness=None)
        view.brightness.set_value("0")
        self.assertIn("Unknown", view._brightness_was_label.text())

    def test_moving_brightness_does_not_also_mark_auto_on_off(self):
        """Mirrors vibration_view.py's "unrelated edit" regression -- two
        independent fields sharing one _on_edit() must not cross-touch."""
        view, state = self._view_with_state(dock_led_brightness=25, dock_auto_on_off=False)
        view.brightness.set_value("100")
        self.assertFalse(view.auto_on_off.is_edited())
        self.assertTrue(view._auto_was_label.isHidden())


if __name__ == "__main__":
    unittest.main()
