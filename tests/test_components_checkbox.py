"""Checkbox tests, A2 of the redesign. Runs headless (offscreen platform);
skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class CheckboxTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_accessible_name_follows_the_label_text(self):
        from g7ctlc.checkbox import Checkbox

        box = Checkbox("Invert X axis")
        self.assertEqual(box.accessibleName(), "Invert X axis")
        box.setText("Invert Y axis")
        self.assertEqual(box.accessibleName(), "Invert Y axis")

    def test_set_edited_suffixes_the_accessible_name(self):
        from g7ctlc.checkbox import Checkbox

        box = Checkbox("Invert X axis")
        box.set_edited(True)
        self.assertEqual(box.accessibleName(), "Invert X axis, edited")
        self.assertTrue(box.is_edited())
        box.set_edited(False)
        self.assertEqual(box.accessibleName(), "Invert X axis")

    def test_set_unread_disables_and_suffixes_the_accessible_name(self):
        from g7ctlc.checkbox import Checkbox

        box = Checkbox("Invert X axis")
        box.set_unread(True)
        self.assertEqual(box.accessibleName(), "Invert X axis, unread")
        self.assertFalse(box.isEnabled())
        self.assertTrue(box.is_unread())

    def test_unread_takes_precedence_over_edited_in_the_suffix(self):
        from g7ctlc.checkbox import Checkbox

        box = Checkbox("Invert X axis")
        box.set_edited(True)
        box.set_unread(True)
        self.assertEqual(box.accessibleName(), "Invert X axis, unread")


if __name__ == "__main__":
    unittest.main()
