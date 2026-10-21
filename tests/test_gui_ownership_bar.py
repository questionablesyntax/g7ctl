"""OwnershipBar tests, A3 of the redesign. `tests/test_gui_main_window.py`
covers the end-to-end wiring (set_connection_state -> this bar) --
this file covers the bar's own state->text/variant mapping directly.

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
class OwnershipBarStateTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bar(self):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.ownership_bar import OwnershipBar
        from g7ctlc.palette import DARK_PALETTE
        return OwnershipBar(DARK_PALETTE, LucideIconLoader())

    def test_connected_is_the_held_variant_with_the_release_button_enabled(self):
        bar = self._bar()
        bar.set_state("connected")
        self.assertEqual(bar.property("variant"), "held")
        self.assertIn("Holding", bar.capsule.text())
        self.assertTrue(bar.release_button.isEnabled())
        self.assertEqual(bar.release_button.text(), "Release Device")

    def test_paused_is_the_released_variant_with_reconnect_wording(self):
        bar = self._bar()
        bar.set_state("paused")
        self.assertEqual(bar.property("variant"), "released")
        self.assertTrue(bar.release_button.isEnabled())
        self.assertEqual(bar.release_button.text(), "Reconnect")

    def test_disconnected_and_no_controller_share_the_no_controller_variant(self):
        bar = self._bar()
        bar.set_state("disconnected")
        self.assertEqual(bar.property("variant"), "no_controller")
        self.assertFalse(bar.release_button.isEnabled())
        bar.set_state("no_controller")
        self.assertEqual(bar.property("variant"), "no_controller")
        # Different wording for the same visual variant -- "never tried"
        # and "tried, nothing answered" are different facts.
        self.assertNotEqual(bar.capsule.text(), "")

    def test_connecting_disables_release(self):
        bar = self._bar()
        bar.set_state("connecting")
        self.assertEqual(bar.property("variant"), "connecting")
        self.assertFalse(bar.release_button.isEnabled())

    def test_playability_warning_only_while_connected(self):
        bar = self._bar()
        bar.set_state("connected")
        self.assertIn("not usable as a gamepad", bar.playability_label.text())
        bar.set_state("paused")
        self.assertEqual(bar.playability_label.text(), "")

    def test_release_requested_fires_on_click(self):
        bar = self._bar()
        bar.set_state("connected")
        received = []
        bar.releaseRequested.connect(lambda: received.append(1))
        bar.release_button.click()
        self.assertEqual(received, [1])

    def test_set_release_enabled_can_suppress_release_mid_job(self):
        bar = self._bar()
        bar.set_state("connected")
        self.assertTrue(bar.release_button.isEnabled())
        bar.set_release_enabled(False)
        self.assertFalse(bar.release_button.isEnabled())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class OwnershipBarBatteryTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bar(self):
        from g7ctlc.icon_loader import LucideIconLoader
        from g7ctlc.ownership_bar import OwnershipBar
        from g7ctlc.palette import DARK_PALETTE
        return OwnershipBar(DARK_PALETTE, LucideIconLoader())

    def test_hidden_until_there_is_a_reading(self):
        bar = self._bar()
        self.assertFalse(bar.battery_label.isVisible())
        self.assertEqual(bar.battery_label.text(), "")

    def test_shows_percent_and_charging_and_clears(self):
        bar = self._bar()
        bar.set_battery(46, False)
        self.assertIn("46%", bar.battery_label.text())
        self.assertNotIn("charging", bar.battery_label.text())
        bar.set_battery(98, True)
        self.assertIn("charging", bar.battery_label.text())
        bar.clear_battery()
        self.assertEqual(bar.battery_label.text(), "")
        self.assertFalse(bar.battery_label.isVisible())

    def test_low_charge_is_flagged_caution(self):
        bar = self._bar()
        bar.set_battery(46, False)
        self.assertEqual(bar.battery_label.property("role"), "muted")
        bar.set_battery(12, False)
        self.assertEqual(bar.battery_label.property("role"), "caution")


if __name__ == "__main__":
    unittest.main()
