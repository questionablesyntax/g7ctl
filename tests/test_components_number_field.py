"""NumberField tests, A2 of the redesign. Runs headless (offscreen
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
class NumberFieldVariantsTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_percent_variant_ranges_zero_to_a_hundred_with_a_suffix(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        self.assertEqual((field.minimum(), field.maximum()), (0, 100))
        self.assertEqual(field.suffix(), "%")

    def test_byte_value_variant_ranges_zero_to_255(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.byte_value()
        self.assertEqual((field.minimum(), field.maximum()), (0, 255))

    def test_bits_variant_displays_hex(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.bits()
        field.setValue(255)
        self.assertEqual(field.text(), "0xff")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class NumberFieldSteppingTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _press(self, field, key):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        field.keyPressEvent(event)

    def test_page_up_steps_by_ten(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field.setValue(10)
        self._press(field, Qt.Key.Key_PageUp)
        self.assertEqual(field.value(), 20)

    def test_page_down_steps_by_ten(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field.setValue(50)
        self._press(field, Qt.Key.Key_PageDown)
        self.assertEqual(field.value(), 40)

    def test_page_down_clamps_at_the_minimum(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field.setValue(5)
        self._press(field, Qt.Key.Key_PageDown)
        self.assertEqual(field.value(), 0)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class NumberFieldErrorStateTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_typing_past_the_maximum_flags_an_error(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field._on_text_edited("250%")
        self.assertTrue(field.is_error())
        self.assertEqual(field.toolTip(), "Enter 0 to 100")

    def test_valid_text_clears_the_error(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field._on_text_edited("250%")
        field._on_text_edited("50%")
        self.assertFalse(field.is_error())

    def test_focus_out_clears_the_error_state(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFocusEvent

        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field._on_text_edited("250%")
        self.assertTrue(field.is_error())
        field.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason))
        self.assertFalse(field.is_error())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class NumberFieldUnreadAndEditedTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unread_blanks_the_display_but_keeps_the_real_value(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field.setValue(42)
        field.set_unread(True)
        self.assertEqual(field.text(), "")
        self.assertEqual(field.value(), 42)
        self.assertFalse(field.isEnabled())
        field.set_unread(False)
        self.assertEqual(field.text(), "42%")

    def test_accessible_name_gains_unread_and_edited_suffixes(self):
        from g7ctlc.number_field import NumberField

        field = NumberField.percent()
        field.setAccessibleName("Deadzone")
        field.set_edited(True)
        self.assertEqual(field.accessibleName(), "Deadzone, edited")
        field.set_unread(True)
        self.assertEqual(field.accessibleName(), "Deadzone, unread")


if __name__ == "__main__":
    unittest.main()
