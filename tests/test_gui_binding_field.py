"""BindingField tests, A4 of the redesign. Runs headless (offscreen
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
class BindingFieldTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_starts_not_remapped(self):
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        self.assertIsNone(field.value())
        self.assertEqual(field.text(), "Not remapped")
        self.assertTrue(field.is_known())

    def test_known_value_shows_its_grouped_display_text(self):
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        field.set_value("f11")
        self.assertEqual(field.text(), "Keyboard: F11")
        self.assertTrue(field.is_known())

    def test_unknown_raw_value_shows_as_unrecognised_and_flags_the_property(self):
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        field.set_value("0xab")
        self.assertEqual(field.text(), "Raw: 0xab")
        self.assertFalse(field.is_known())
        self.assertTrue(field.property("unrecognised"))

    def test_known_flag_is_inferred_when_not_given(self):
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        field.set_value("f11")  # no known= kwarg -- inferred from KNOWN_KEYCODES
        self.assertTrue(field.is_known())
        field.set_value("0xzz")
        self.assertFalse(field.is_known())

    def test_accessible_name_combines_the_label_and_the_current_value(self):
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        field.setAccessibleName("A")
        self.assertEqual(field.accessibleName(), "A: Not remapped")
        field.set_value("f11")
        self.assertEqual(field.accessibleName(), "A: Keyboard: F11")

    def test_edited_suffixes_the_accessible_name(self):
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        field.setAccessibleName("A")
        field.set_edited(True)
        self.assertEqual(field.accessibleName(), "A: Not remapped, edited")
        self.assertTrue(field.is_edited())

    def test_is_a_real_button_reachable_by_click_and_activation(self):
        # The picker opens via clicked -- Enter/Space activation and click
        # both fire it, for free, because this is a real QPushButton, not
        # a custom-painted field re-implementing focus/activation.
        from g7ctlc.binding_field import BindingField

        field = BindingField()
        received = []
        field.clicked.connect(lambda: received.append(1))
        field.click()
        self.assertEqual(received, [1])


if __name__ == "__main__":
    unittest.main()
