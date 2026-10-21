"""ScopeLine tests, A2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None

from g7ctlc.palette import DARK_PALETTE


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class ScopeLineTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.icon_loader import LucideIconLoader

        self.icons = LucideIconLoader()

    def test_accessible_name_and_label_follow_the_sentence(self):
        from g7ctlc.scope_line import ScopeLine

        line = ScopeLine("gamepad-2", "Edits Profile 2 only.", DARK_PALETTE, self.icons)
        self.assertEqual(line.accessibleName(), "Edits Profile 2 only.")
        self.assertEqual(line.text_label.text(), "Edits Profile 2 only.")

    def test_set_sentence_updates_both(self):
        from g7ctlc.scope_line import ScopeLine

        line = ScopeLine("layers", "Shared by all profiles.", DARK_PALETTE, self.icons)
        line.set_sentence("Shared by all profiles and the dock.")
        self.assertEqual(line.accessibleName(), "Shared by all profiles and the dock.")
        self.assertEqual(line.text_label.text(), "Shared by all profiles and the dock.")

    def test_icon_pixmap_is_not_null(self):
        from g7ctlc.scope_line import ScopeLine

        line = ScopeLine("gamepad-2", "Edits Profile 2 only.", DARK_PALETTE, self.icons)
        icon_label = line.layout().itemAt(0).widget()
        self.assertFalse(icon_label.pixmap().isNull())


if __name__ == "__main__":
    unittest.main()
