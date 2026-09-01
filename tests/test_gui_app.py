"""app.py's argument parsing and logging setup -- the pieces that don't
need a real QApplication/event loop to test directly.

app.py itself has no other test coverage: main() is a closure that builds
the whole app (QApplication, MainWindow, tray, watcher thread, real event
loop) end to end, not practically testable without a much bigger
restructuring than this file's scope (see fe614de's own commit message).
_parse_args()/_configure_logging() were pulled out specifically so the
-v/--verbose flag and the log file setup it gates (added 2026-09-01, see
DEBUGGING-INFRA-PLAN-2026-09-01.md) have real coverage without needing
that.

Runs headless (offscreen platform); skipped entirely if PyQt6 is absent,
same as the other g7ctlc test modules -- app.py imports PyQt6 at module
level, so it can't even be imported otherwise.
"""
import logging
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6.QtWidgets  # noqa: F401
    _PYQT6_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the environment
    _PYQT6_AVAILABLE = False


@unittest.skipIf(not _PYQT6_AVAILABLE, "PyQt6 not installed")
class ParseArgsTest(unittest.TestCase):
    def test_defaults_to_not_verbose(self):
        from g7ctlc.app import _parse_args
        self.assertFalse(_parse_args([]).verbose)

    def test_long_flag(self):
        from g7ctlc.app import _parse_args
        self.assertTrue(_parse_args(["--verbose"]).verbose)

    def test_short_flag(self):
        from g7ctlc.app import _parse_args
        self.assertTrue(_parse_args(["-v"]).verbose)

    def test_unrecognized_qt_flags_are_ignored_not_rejected(self):
        """QApplication(sys.argv) still gets the full, unfiltered argv
        further down main() -- this parser must not choke on (or
        silently eat) a Qt-own flag like -style/-platform, since those
        are Qt's to consume, not this parser's."""
        from g7ctlc.app import _parse_args
        args = _parse_args(["-style", "Fusion", "-v"])
        self.assertTrue(args.verbose)


@unittest.skipIf(not _PYQT6_AVAILABLE, "PyQt6 not installed")
class ConfigureLoggingTest(unittest.TestCase):
    """Every test here points _LOG_PATH at a real tempdir rather than the
    real ~/.config/g7ctl/ -- _configure_logging() always tries to create
    the log file (best-effort), so a mocked-but-still-real writable path
    is what exercises the normal path without touching the user's actual
    config directory or leaving debris behind."""

    def setUp(self):
        self._orig_level = logging.root.level
        self._orig_handlers = list(logging.root.handlers)
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._log_path = Path(self._tmp.name) / "g7ctl" / "g7ctlc.log"
        self._patcher = mock.patch("g7ctlc.app._LOG_PATH", self._log_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        logging.root.handlers[:] = self._orig_handlers
        logging.root.setLevel(self._orig_level)

    def test_default_level_is_info(self):
        from g7ctlc.app import _configure_logging
        _configure_logging(verbose=False)
        self.assertEqual(logging.root.getEffectiveLevel(), logging.INFO)

    def test_verbose_lowers_the_level_to_debug(self):
        from g7ctlc.app import _configure_logging
        _configure_logging(verbose=True)
        self.assertEqual(logging.root.getEffectiveLevel(), logging.DEBUG)

    def test_writes_a_real_rotating_log_file(self):
        from g7ctlc.app import _configure_logging
        _configure_logging(verbose=True)
        logging.getLogger("g7ctlc.test").debug("a real debug line")
        self.assertTrue(self._log_path.exists())
        self.assertIn("a real debug line", self._log_path.read_text())

    def test_an_unwritable_log_path_falls_back_to_stderr_only_without_raising(self):
        """A log file this process can't create (read-only home,
        permissions, disk full) must never stop the app from launching --
        stderr-only logging, same as the pre-2026-09-01 behavior, not an
        exception out of main()."""
        from g7ctlc.app import _configure_logging
        with mock.patch("logging.handlers.RotatingFileHandler", side_effect=OSError("boom")):
            _configure_logging(verbose=False)  # must not raise
        self.assertEqual(logging.root.getEffectiveLevel(), logging.INFO)
        self.assertEqual(len(logging.root.handlers), 1, "stderr handler only, no broken file handler")


if __name__ == "__main__":
    unittest.main()
