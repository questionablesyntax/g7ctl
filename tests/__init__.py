"""Hooks every unittest-style test, whichever runner starts it.

CI runs `python -m unittest discover`; pytest runs the same TestCase classes
through TestCase.run too, so wrapping it once here covers both.
"""
import unittest

from pyg7 import curves

from .qt_cleanup import destroy_top_level_widgets

# No test should wait on real hardware pacing -- unlike SPLIT_WRITE_INTERVAL/
# the various session.py intervals, this one isn't threaded through a
# per-call parameter tests can override locally (see curves.py's own comment
# on why: a default argument is bound once at import time). Set once, for
# the whole run, instead of requiring every test path that happens to touch
# a curve-point write -- or, since 2026-11-02, motion.py's output-setting
# repair writes (ROADMAP item 66, notes repo) -- to remember its own
# `@mock.patch.object(curves, "CURVE_POINT_WRITE_INTERVAL", 0)`. Several
# call sites already carry that decorator from before this existed; it's
# redundant now, not wrong, so left alone rather than churned out.
curves.CURVE_POINT_WRITE_INTERVAL = 0

if not getattr(unittest.TestCase, "_destroys_qt_widgets_after_each_test", False):
    _original_run = unittest.TestCase.run

    def _run_then_clean_up(self, result=None):
        try:
            return _original_run(self, result)
        finally:
            destroy_top_level_widgets()

    unittest.TestCase.run = _run_then_clean_up
    unittest.TestCase._destroys_qt_widgets_after_each_test = True
