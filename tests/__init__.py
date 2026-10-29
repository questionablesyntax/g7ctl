"""Hooks every unittest-style test, whichever runner starts it.

CI runs `python -m unittest discover`; pytest runs the same TestCase classes
through TestCase.run too, so wrapping it once here covers both.
"""
import unittest

from .qt_cleanup import destroy_top_level_widgets

if not getattr(unittest.TestCase, "_destroys_qt_widgets_after_each_test", False):
    _original_run = unittest.TestCase.run

    def _run_then_clean_up(self, result=None):
        try:
            return _original_run(self, result)
        finally:
            destroy_top_level_widgets()

    unittest.TestCase.run = _run_then_clean_up
    unittest.TestCase._destroys_qt_widgets_after_each_test = True
