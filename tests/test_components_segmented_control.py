"""SegmentedControl tests, A2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class SegmentedControlTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make(self, meter=False):
        from PyQt6.QtCore import Qt

        from g7ctlc.segmented_control import SegmentedControl

        control = SegmentedControl(
            [("a", "A"), ("b", "B"), ("c", "C")], meter=meter
        )
        return control, Qt

    def test_defaults_to_off_scale(self):
        control, _ = self._make()
        self.assertIsNone(control.value())
        self.assertTrue(control.is_off_scale())

    def test_set_value_selects_the_matching_segment(self):
        control, _ = self._make()
        control.set_value("b")
        self.assertEqual(control.value(), "b")
        self.assertTrue(control._buttons["b"].isChecked())
        self.assertFalse(control.is_off_scale())

    def test_set_value_to_none_clears_selection(self):
        control, _ = self._make()
        control.set_value("b")
        control.set_value(None)
        self.assertIsNone(control.value())

    def test_set_value_rejects_unknown_segment(self):
        control, _ = self._make()
        with self.assertRaises(KeyError):
            control.set_value("nope")

    def test_clicking_a_segment_emits_selection_changed(self):
        control, _ = self._make()
        received = []
        control.selectionChanged.connect(received.append)
        control._buttons["c"].click()
        self.assertEqual(received, ["c"])

    def test_only_the_selected_segment_is_a_tab_stop(self):
        control, Qt = self._make()
        control.set_value("a")
        self.assertEqual(control._buttons["a"].focusPolicy(), Qt.FocusPolicy.StrongFocus)
        self.assertEqual(control._buttons["b"].focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(control._buttons["c"].focusPolicy(), Qt.FocusPolicy.NoFocus)
        control.set_value("c")
        self.assertEqual(control._buttons["a"].focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(control._buttons["c"].focusPolicy(), Qt.FocusPolicy.StrongFocus)

    def test_arrow_right_moves_selection_and_wraps(self):
        control, Qt = self._make()
        control.set_value("c")
        control._move_selection(list(control._buttons.values()), 2, +1)
        self.assertEqual(control.value(), "a")  # wrapped past the last segment

    def test_arrow_left_moves_selection_and_wraps(self):
        control, _ = self._make()
        control.set_value("a")
        control._move_selection(list(control._buttons.values()), 0, -1)
        self.assertEqual(control.value(), "c")  # wrapped before the first segment

    def test_meter_variant_marks_filled_up_to_the_selected_index(self):
        control, _ = self._make(meter=True)
        control.set_value("b")
        self.assertTrue(control._buttons["a"].property("filled"))
        self.assertTrue(control._buttons["b"].property("filled"))
        self.assertFalse(control._buttons["c"].property("filled"))

    def test_edited_and_unread_update_accessible_names(self):
        control, _ = self._make()
        control.set_edited(True)
        self.assertEqual(control._buttons["a"].accessibleName(), "A, edited")
        control.set_unread(True)
        self.assertEqual(control._buttons["a"].accessibleName(), "A, unread")
        self.assertFalse(control.isEnabled())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class CaptionedSegmentedControlTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_caption_shows_only_while_off_scale(self):
        from g7ctlc.segmented_control import CaptionedSegmentedControl

        control = CaptionedSegmentedControl(
            [("a", "A"), ("b", "B")], "Not set"
        )
        # isHidden(), not isVisible(): this widget is never shown on screen
        # in this test, and isVisible() answers false for every child of an
        # unshown top-level regardless of setVisible() -- isHidden() is the
        # one that reflects the explicit per-widget call this test exercises.
        self.assertFalse(control.caption.isHidden())
        control.set_value("a")
        self.assertTrue(control.caption.isHidden())
        control.set_value(None)
        self.assertFalse(control.caption.isHidden())


if __name__ == "__main__":
    unittest.main()
