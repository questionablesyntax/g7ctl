"""BindingRow tests, A4 of the redesign. Runs headless (offscreen
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
class BindingRowLatchTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_latch_capable_button_gets_a_real_checkbox(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("A")
        self.assertIsNotNone(row.latch)
        self.assertIsNone(row.latch_reason_label)

    def test_a_trigger_gets_the_reason_text_instead(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("RT", latch_reason="Triggers have no latch setting")
        self.assertIsNone(row.latch)
        self.assertIsNotNone(row.latch_reason_label)
        self.assertEqual(row.latch_reason_label.text(), "Triggers have no latch setting")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class BindingRowModeTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_mode_shows_the_base_field_latch_and_shift_reference(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("A")
        row.set_mode("default")
        self.assertFalse(row.default_field.isHidden())
        self.assertTrue(row.shift_field.isHidden())
        self.assertFalse(row.latch.isHidden())
        self.assertFalse(row.shift_reference.isHidden())

    def test_shift_mode_shows_only_the_shift_field(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("A")
        row.set_mode("shift")
        self.assertTrue(row.default_field.isHidden())
        self.assertFalse(row.shift_field.isHidden())
        self.assertTrue(row.latch.isHidden())
        self.assertTrue(row.shift_reference.isHidden())

    def test_shift_mode_hides_the_reason_label_too(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("RT", latch_reason="Triggers have no latch setting")
        row.set_mode("shift")
        self.assertTrue(row.latch_reason_label.isHidden())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class BindingRowShiftReferenceTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_none_reads_no_shift_binding(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("A")
        row.set_shift_reference(None)
        self.assertEqual(row.shift_reference.text(), "No Shift binding")

    def test_a_known_value_shows_its_display_text(self):
        from g7ctlc.binding_row import BindingRow

        row = BindingRow("A")
        row.set_shift_reference("f11")
        self.assertEqual(row.shift_reference.text(), "Keyboard: F11")


if __name__ == "__main__":
    unittest.main()
