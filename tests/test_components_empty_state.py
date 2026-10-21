"""EmptyState tests, A2 of the redesign. Runs headless (offscreen
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
class EmptyStateTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.fonts import load_fonts

        self.font_load = load_fonts()

    def test_rejects_more_than_two_actions(self):
        from g7ctlc.empty_state import EmptyState

        with self.assertRaises(ValueError):
            EmptyState(
                "No controller",
                "Connect a GameSir G7 Pro to get started.",
                self.font_load,
                actions=[("A", lambda: None), ("B", lambda: None), ("C", lambda: None)],
            )

    def test_accessible_name_and_description_follow_heading_and_sentence(self):
        from g7ctlc.empty_state import EmptyState

        state = EmptyState("No controller", "Connect a controller.", self.font_load)
        self.assertEqual(state.accessibleName(), "No controller")
        self.assertEqual(state.accessibleDescription(), "Connect a controller.")

    def test_actions_build_one_button_each_and_wire_their_callback(self):
        from g7ctlc.empty_state import EmptyState

        calls = []
        state = EmptyState(
            "No controller",
            "Connect a controller.",
            self.font_load,
            actions=[("Reconnect", lambda: calls.append("reconnect"))],
        )
        self.assertEqual(len(state.buttons), 1)
        state.buttons[0].click()
        self.assertEqual(calls, ["reconnect"])

    def test_no_actions_means_no_buttons(self):
        from g7ctlc.empty_state import EmptyState

        state = EmptyState("No controller", "Connect a controller.", self.font_load)
        self.assertEqual(state.buttons, [])


if __name__ == "__main__":
    unittest.main()
