"""Help menu tests: the Help button (About / On-Device Features / Report
an Issue), added in the pre-fork UX pass and moved from the top selector
bar into the rail's footer in A3 of the redesign.

QMessageBox.about()/.information() and QDesktopServices.openUrl() are
monkeypatched rather than actually invoked -- all three block on a real
event loop waiting for user interaction (or, for openUrl, reach outside the
process entirely), neither of which belongs in a headless, offscreen test.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent, same
as the other g7ctlc test modules.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class HelpMenuTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from g7ctlc.main_window import MainWindow
        return MainWindow()

    def test_help_button_lives_in_the_rail_footer(self):
        # A3 of the redesign moved Help from the top selector bar (gone --
        # replaced by the ownership bar and rail) into the rail's own
        # footer, alongside Snapshots and App preferences.
        window = self._window()
        self.assertIs(window.help_btn, window.rail.help_button)
        self.assertIn(window.rail.help_button, window.rail.findChildren(type(window.rail.help_button)))
        self.assertNotIn(
            window.rail.help_button,
            window.ownership_bar.findChildren(type(window.rail.help_button)),
        )

    def test_help_menu_has_the_three_expected_actions(self):
        window = self._window()
        labels = [a.text() for a in window.help_btn.menu().actions() if a.text()]
        self.assertEqual(labels, ["About", "On-Device Features", "Report an Issue…"])

    def test_about_shows_the_version(self):
        from g7ctlc import __version__
        window = self._window()
        with mock.patch("g7ctlc.main_window.QMessageBox.about") as about:
            window._on_about()
        about.assert_called_once()
        _parent, _title, text = about.call_args.args
        self.assertIn(__version__, text)

    def test_about_mentions_both_licenses(self):
        window = self._window()
        with mock.patch("g7ctlc.main_window.QMessageBox.about") as about:
            window._on_about()
        text = about.call_args.args[-1]
        self.assertIn("Apache-2.0", text)
        self.assertIn("GPL-3.0", text)

    def test_on_device_features_shows_the_profile_switch_combo(self):
        window = self._window()
        with mock.patch("g7ctlc.main_window.QMessageBox.information") as info:
            window._on_ondevice_features()
        info.assert_called_once()
        text = info.call_args.args[-1]
        self.assertIn("M+Y", text)

    def test_report_issue_opens_the_github_issues_url(self):
        from g7ctlc.help_content import ISSUES_URL
        window = self._window()
        with mock.patch("g7ctlc.main_window.QDesktopServices.openUrl") as open_url:
            window._on_report_issue()
        open_url.assert_called_once()
        (url_arg,) = open_url.call_args.args
        self.assertEqual(url_arg.toString(), ISSUES_URL)


if __name__ == "__main__":
    unittest.main()
