"""Rail tests, A3 of the redesign. `tests/test_gui_main_window.py` already
exercises most of this indirectly (through MainWindow's own handlers) --
this file covers what nothing else does: clicking a nav entry other than
Buttons, the footer's own signal wiring, and the exclusive-group mechanics
`SegmentedControl`/`QButtonGroup` give this for free.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RailNavigationTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _rail(self):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.palette import DARK_PALETTE
        from g7ctlc.rail import Rail
        return Rail(DARK_PALETTE, LucideIconLoader())

    def test_buttons_is_the_default_current_page(self):
        rail = self._rail()
        self.assertEqual(rail.current_page(), "buttons")

    def test_clicking_a_different_nav_entry_requests_its_page_and_moves_current(self):
        rail = self._rail()
        received = []
        rail.pageRequested.connect(received.append)
        rail._nav_buttons["sticks"].click()
        self.assertEqual(received, ["sticks"])
        self.assertEqual(rail.current_page(), "sticks")

    def test_nav_entries_are_mutually_exclusive(self):
        rail = self._rail()
        rail._nav_buttons["triggers"].click()
        rail._nav_buttons["vibration"].click()
        self.assertFalse(rail._nav_buttons["triggers"].isChecked())
        self.assertTrue(rail._nav_buttons["vibration"].isChecked())

    def test_set_page_visible_is_reflected_by_is_page_visible(self):
        rail = self._rail()
        self.assertTrue(rail.is_page_visible("dock"))
        rail.set_page_visible("dock", False)
        self.assertFalse(rail.is_page_visible("dock"))

    def test_set_nav_enabled_gates_every_button_and_the_profile_switch(self):
        rail = self._rail()
        rail.set_nav_enabled(False)
        self.assertFalse(rail._nav_buttons["buttons"].isEnabled())
        self.assertFalse(rail._nav_buttons["dock"].isEnabled())
        self.assertFalse(rail.profile_switch.isEnabled())
        rail.set_nav_enabled(True)
        self.assertTrue(rail._nav_buttons["buttons"].isEnabled())
        self.assertTrue(rail.profile_switch.isEnabled())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RailProfileSwitchTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _rail(self):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.palette import DARK_PALETTE
        from g7ctlc.rail import Rail
        return Rail(DARK_PALETTE, LucideIconLoader())

    def test_choosing_a_slot_emits_profile_changed_and_updates_the_heading(self):
        rail = self._rail()
        received = []
        rail.profileChanged.connect(received.append)
        rail.profile_switch.set_value("3")
        self.assertEqual(received, [3])
        self.assertEqual(rail.profile_heading.text(), "Profile 3 settings")

    def test_set_profile_does_not_reemit_profile_changed(self):
        # The loading-guard reasoning MainWindow relies on: reflecting a
        # profile chosen elsewhere must not look like the user picking a
        # new one (which would kick off a redundant device read).
        rail = self._rail()
        received = []
        rail.profileChanged.connect(received.append)
        rail.set_profile(2)
        self.assertEqual(received, [])
        self.assertEqual(rail.profile_switch.value(), "2")
        self.assertEqual(rail.profile_heading.text(), "Profile 2 settings")

    def test_on_controller_marker_shows_and_hides(self):
        rail = self._rail()
        self.assertTrue(rail.on_controller_marker.isHidden())
        rail.set_active_profile(4)
        self.assertFalse(rail.on_controller_marker.isHidden())
        self.assertIn("4", rail._marker_label.text())
        rail.set_active_profile(None)
        self.assertTrue(rail.on_controller_marker.isHidden())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RailFooterSignalsTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _rail(self):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.palette import DARK_PALETTE
        from g7ctlc.rail import Rail
        return Rail(DARK_PALETTE, LucideIconLoader())

    def test_read_button_emits_read_requested(self):
        rail = self._rail()
        rail.read_button.setEnabled(True)  # starts disabled until MainWindow connects
        received = []
        rail.readRequested.connect(lambda: received.append(1))
        rail.read_button.click()
        self.assertEqual(received, [1])

    def test_snapshots_menu_import_and_export_actions_emit_their_signals(self):
        rail = self._rail()
        imports, exports = [], []
        rail.importRequested.connect(lambda: imports.append(1))
        rail.exportRequested.connect(lambda: exports.append(1))
        labels = [a.text() for a in rail.snapshots_button.menu().actions()]
        self.assertEqual(labels, ["Import…", "Export…"])
        rail.snapshots_button.menu().actions()[0].trigger()
        rail.snapshots_button.menu().actions()[1].trigger()
        self.assertEqual(imports, [1])
        self.assertEqual(exports, [1])

    def test_app_preferences_button_emits_its_signal(self):
        rail = self._rail()
        received = []
        rail.appPreferencesRequested.connect(lambda: received.append(1))
        rail.app_preferences_button.click()
        self.assertEqual(received, [1])

    def test_wire_help_menu_populates_the_rails_own_menu(self):
        rail = self._rail()
        from PyQt6.QtGui import QAction

        def build(menu):
            menu.addAction(QAction("About", menu))

        rail.wire_help_menu(build)
        labels = [a.text() for a in rail.help_button.menu().actions()]
        self.assertEqual(labels, ["About"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RailPaletteTest(unittest.TestCase):
    """Real bug, found in A6's code review (2026-10-22): every icon here
    is a baked palette-tinted pixmap/QIcon, and there was no set_palette()
    at all -- a live theme switch left every one of them tinted for
    whichever palette the rail was constructed with.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _rail(self, palette):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.rail import Rail
        return Rail(palette, LucideIconLoader())

    def test_set_palette_retints_every_icon(self):
        from g7ctlc.palette import DARK_PALETTE, LIGHT_PALETTE
        rail = self._rail(DARK_PALETTE)
        before = [
            rail._profile_heading_icon_label.pixmap().cacheKey(),
            rail._marker_icon_label.pixmap().cacheKey(),
            rail._shared_heading_icon_label.pixmap().cacheKey(),
            rail.read_button.icon().cacheKey(),
            rail.snapshots_button.icon().cacheKey(),
            rail.help_button.icon().cacheKey(),
            rail._import_action.icon().cacheKey(),
            rail._export_action.icon().cacheKey(),
        ]
        rail.set_palette(LIGHT_PALETTE)
        after = [
            rail._profile_heading_icon_label.pixmap().cacheKey(),
            rail._marker_icon_label.pixmap().cacheKey(),
            rail._shared_heading_icon_label.pixmap().cacheKey(),
            rail.read_button.icon().cacheKey(),
            rail.snapshots_button.icon().cacheKey(),
            rail.help_button.icon().cacheKey(),
            rail._import_action.icon().cacheKey(),
            rail._export_action.icon().cacheKey(),
        ]
        for b, a in zip(before, after):
            self.assertNotEqual(b, a, "an icon did not change for a different palette")


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RailEditCountTest(unittest.TestCase):
    """S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S):
    DESIGN-SPEC.md 10.2 item 2's "rail edit counts"."""
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _rail(self):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.palette import DARK_PALETTE
        from g7ctlc.rail import Rail
        return Rail(DARK_PALETTE, LucideIconLoader())

    def test_a_nonzero_count_is_appended_to_the_label(self):
        rail = self._rail()
        rail.set_edit_count("vibration", 2)
        self.assertEqual(rail._nav_buttons["vibration"].text(), "Vibration (2)")
        self.assertEqual(rail._nav_buttons["vibration"].accessibleName(), "Vibration (2)")

    def test_zero_restores_the_plain_label(self):
        rail = self._rail()
        rail.set_edit_count("vibration", 3)
        rail.set_edit_count("vibration", 0)
        self.assertEqual(rail._nav_buttons["vibration"].text(), "Vibration")
        self.assertEqual(rail._nav_buttons["vibration"].accessibleName(), "Vibration")

    def test_a_shared_scope_page_can_show_a_count_too(self):
        rail = self._rail()
        rail.set_edit_count("dock", 1)
        self.assertEqual(rail._nav_buttons["dock"].text(), "Dock (1)")


if __name__ == "__main__":
    unittest.main()
