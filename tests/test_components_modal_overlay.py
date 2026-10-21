"""ModalOverlayBase tests, A2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.

Doesn't call `exec()` (it blocks on a real event loop) -- focus capture and
modality are exercised directly instead, matching how `test_gui_*` already
tests dialog-shaped widgets in this codebase without a blocking exec loop.
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
class ModalOverlayBaseTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_is_frameless_and_application_modal(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.modal_overlay import ModalOverlayBase

        overlay = ModalOverlayBase(DARK_PALETTE)
        self.assertTrue(overlay.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(overlay.windowModality(), Qt.WindowModality.ApplicationModal)

    def test_escape_rejects_by_default(self):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QDialog

        from g7ctlc.modal_overlay import ModalOverlayBase

        overlay = ModalOverlayBase(DARK_PALETTE, animate=False)
        results = []
        overlay.finished.connect(results.append)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        overlay.keyPressEvent(event)
        self.assertEqual(results, [QDialog.DialogCode.Rejected])

    def test_focus_is_restored_to_the_widget_that_had_it_before_open(self):
        from PyQt6.QtWidgets import QDialog, QLineEdit, QWidget

        from g7ctlc.modal_overlay import ModalOverlayBase

        host = QWidget()
        trigger = QLineEdit(host)
        host.show()
        trigger.setFocus()
        self.app.processEvents()

        overlay = ModalOverlayBase(DARK_PALETTE, host, animate=False)
        overlay._focus_before_open = trigger  # exec() blocks; set what exec() would have captured
        overlay.done(QDialog.DialogCode.Accepted)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), trigger)
        host.close()

    def test_content_layout_is_ready_for_a_subclass_to_populate(self):
        from PyQt6.QtWidgets import QLabel

        from g7ctlc.modal_overlay import ModalOverlayBase

        overlay = ModalOverlayBase(DARK_PALETTE, animate=False)
        overlay.content_layout.addWidget(QLabel("Review 3 changes"))
        self.assertEqual(overlay.content_layout.count(), 1)


if __name__ == "__main__":
    unittest.main()
