"""InlineNotice tests, A2 of the redesign. Runs headless (offscreen
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
class InlineNoticeTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from g7ctlc.icon_loader import LucideIconLoader

        self.icons = LucideIconLoader()

    def test_rejects_an_unknown_variant(self):
        from g7ctlc.inline_notice import InlineNotice

        with self.assertRaises(ValueError):
            InlineNotice("warning", "text", DARK_PALETTE, self.icons)

    def test_each_variant_carries_its_own_role_property(self):
        from g7ctlc.inline_notice import InlineNotice

        for variant in ("info", "caution", "alarm"):
            notice = InlineNotice(variant, "Something to say", DARK_PALETTE, self.icons)
            self.assertEqual(notice.property("role"), f"notice-{variant}")

    def test_accessible_name_follows_the_text(self):
        from g7ctlc.inline_notice import InlineNotice

        notice = InlineNotice("info", "Read 3 of 3 fields", DARK_PALETTE, self.icons)
        self.assertEqual(notice.accessibleName(), "Read 3 of 3 fields")
        notice.set_text("Updated")
        self.assertEqual(notice.accessibleName(), "Updated")
        self.assertEqual(notice.text_label.text(), "Updated")

    def test_action_button_is_optional(self):
        from g7ctlc.inline_notice import InlineNotice

        plain = InlineNotice("info", "No action here", DARK_PALETTE, self.icons)
        self.assertIsNone(plain.action_button)

    def test_action_button_invokes_the_callback(self):
        from g7ctlc.inline_notice import InlineNotice

        calls = []
        notice = InlineNotice(
            "alarm", "Write failed", DARK_PALETTE, self.icons,
            action_text="Retry", on_action=lambda: calls.append(1),
        )
        self.assertIsNotNone(notice.action_button)
        notice.action_button.click()
        self.assertEqual(calls, [1])

    def test_set_palette_retints_the_icon(self):
        """Real bug, found in A6's code review (2026-10-22): this icon is
        a baked palette-tinted pixmap, same as TrayIcon's own, and there
        was no set_palette() at all -- MainWindow's _on_palette_changed()
        is wired to the ownership bar's alarm notice specifically, so a
        live theme switch left it tinted for whichever palette the app
        started in."""
        from g7ctlc.inline_notice import InlineNotice
        from g7ctlc.palette import LIGHT_PALETTE

        notice = InlineNotice("alarm", "Lost connection", DARK_PALETTE, self.icons)
        before = notice._icon_label.pixmap().cacheKey()
        notice.set_palette(LIGHT_PALETTE)
        after = notice._icon_label.pixmap().cacheKey()
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
