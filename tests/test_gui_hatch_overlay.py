"""HatchOverlay tests, A5 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.
"""
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


def _pump(app, seconds=0.6, step=0.02):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(step)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class HatchOverlayTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _overlay(self):
        from g7ctlc.hatch_overlay import HatchOverlay
        from g7ctlc.palette import DARK_PALETTE
        overlay = HatchOverlay(DARK_PALETTE)
        overlay.resize(120, 80)
        return overlay

    def test_starts_hidden(self):
        overlay = self._overlay()
        self.assertTrue(overlay.isHidden())

    def test_marking_unread_shows_it_immediately(self):
        # DIRECTION-A.md section 6: the reveal is specifically "unknown
        # becoming known" -- going unread is a high-frequency state
        # change like any other, so it's instant, not animated.
        overlay = self._overlay()
        overlay.set_unread(True)
        self.assertFalse(overlay.isHidden())
        self.assertEqual(overlay._effect.opacity(), 1.0)

    def test_clearing_unread_fades_it_out_and_hides_it(self):
        overlay = self._overlay()
        overlay.set_unread(True)
        overlay.set_unread(False)
        self.assertFalse(overlay.isHidden(), "must still be visible mid-fade")
        _pump(self.app)
        self.assertTrue(overlay.isHidden(), "must be hidden once the fade finishes")
        self.assertEqual(overlay._effect.opacity(), 1.0, "opacity must reset, not stay at 0")

    def test_clearing_unread_when_already_hidden_is_a_no_op(self):
        overlay = self._overlay()
        received = []
        overlay.destroyed.connect(lambda: received.append(1))  # would fire if this crashed/misbehaved
        overlay.set_unread(False)  # never shown -- must not start an animation on a hidden widget
        self.assertTrue(overlay.isHidden())

    def test_reduced_motion_uses_the_shorter_duration(self):
        from g7ctlc.tokens import MOTION_FAST
        overlay = self._overlay()
        overlay.set_unread(True)
        overlay.set_unread(False, reduced_motion=True)
        self.assertEqual(overlay._animation.duration(), MOTION_FAST.duration_ms)

    def test_full_motion_uses_the_slow_duration(self):
        from g7ctlc.tokens import MOTION_SLOW
        overlay = self._overlay()
        overlay.set_unread(True)
        overlay.set_unread(False)
        self.assertEqual(overlay._animation.duration(), MOTION_SLOW.duration_ms)

    def test_re_marking_unread_mid_fade_cancels_the_fade(self):
        overlay = self._overlay()
        overlay.set_unread(True)
        overlay.set_unread(False)
        overlay.set_unread(True)  # a profile switch while the previous reveal was still fading
        self.assertFalse(overlay.isHidden())
        self.assertEqual(overlay._effect.opacity(), 1.0)
        _pump(self.app, seconds=0.5)
        self.assertFalse(overlay.isHidden(), "the cancelled fade must not hide it later")

    def test_does_not_intercept_mouse_events(self):
        from PyQt6.QtCore import Qt
        overlay = self._overlay()
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_set_palette_triggers_a_repaint(self):
        from g7ctlc.palette import LIGHT_PALETTE
        overlay = self._overlay()
        overlay.set_palette(LIGHT_PALETTE)
        self.assertIs(overlay._palette, LIGHT_PALETTE)


if __name__ == "__main__":
    unittest.main()
