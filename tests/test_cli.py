"""CLI-level tests: error handling and message translation.

No real device is touched -- find_writable_device()/enter_vendor_mode()/
VendorSession are monkeypatched. These tests exist to pin the fix for a real
gap: main()'s only try/except used to catch usb.core.USBError alone, and
enter_vendor_mode() (called for both the standalone 'enter-vendor' action and
the CLI's own auto-handshake fallback) was called OUTSIDE that block
entirely -- so the exact USBError cases _explain_usb_error() exists to
translate (device busy, missing udev permission) surfaced as a raw libusb
traceback instead, on what's likely a new user's very first run. Separately,
a bad write-state path/JSON, or a malformed setting value, were never caught
at all.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import usb.core

from g7ctl import main as cli_main

from .fakes import FakeSession


class ExplainUsbErrorTest(unittest.TestCase):
    def _err(self, errno):
        exc = usb.core.USBError("boom")
        exc.errno = errno
        return exc

    def test_ebusy_mentions_the_gui(self):
        msg = cli_main._explain_usb_error(self._err(16))
        self.assertIn("busy", msg.lower())
        self.assertIn("Release Device", msg)

    def test_eacces_mentions_udev(self):
        msg = cli_main._explain_usb_error(self._err(13))
        self.assertIn("Permission denied", msg)
        self.assertIn("udev", msg)

    def test_enodev_mentions_reconnect(self):
        msg = cli_main._explain_usb_error(self._err(19))
        self.assertIn("disappeared", msg.lower())

    def test_unknown_errno_falls_back_to_the_raw_message(self):
        msg = cli_main._explain_usb_error(self._err(999))
        self.assertIn("boom", msg)


class _FakeSessionCM:
    """Stands in for `with VendorSession(vdev) as sess:` -- returns a
    FakeSession (from tests/fakes.py) without ever touching real USB."""

    def __init__(self, _dev, via_dongle=False):
        self.session = FakeSession()

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


class _NoOpSettleSession(FakeSession):
    def settle(self, *a, **k):
        pass

    def probe_controller_live(self, *a, **k):
        return True


class _FakeSessionCMNoOpSettle(_FakeSessionCM):
    def __init__(self, _dev, via_dongle=False):
        self.session = _NoOpSettleSession()


class _CapturingSessionCM(_FakeSessionCMNoOpSettle):
    """Same as _FakeSessionCMNoOpSettle, but stashes the FakeSession it
    creates on the class itself so a test can inspect what got sent after
    main() returns (main() constructs the session internally -- there's no
    other way to reach it from outside)."""
    captured = None

    def __init__(self, _dev, via_dongle=False):
        super().__init__(_dev, via_dongle=via_dongle)
        type(self).captured = self.session


class MainErrorHandlingTest(unittest.TestCase):
    """Drives main() end to end with the device layer faked out, asserting
    a clean stderr message + SystemExit(1) instead of an uncaught traceback."""

    def setUp(self):
        self._orig_find = cli_main.find_writable_device
        self._orig_enter = cli_main.enter_vendor_mode
        self._orig_session = cli_main.VendorSession
        self._orig_argv = sys.argv
        # A device is always "already reachable" -- these tests are about
        # what happens once we're talking to it, not device discovery.
        cli_main.find_writable_device = lambda: (object(), False)
        cli_main.VendorSession = _FakeSessionCMNoOpSettle

    def tearDown(self):
        cli_main.find_writable_device = self._orig_find
        cli_main.enter_vendor_mode = self._orig_enter
        cli_main.VendorSession = self._orig_session
        sys.argv = self._orig_argv

    def _run(self, argv):
        sys.argv = ["g7ctl", *argv]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli_main.main()
        return ctx.exception.code, stderr.getvalue()

    def test_missing_write_state_file_is_a_clean_error_not_a_traceback(self):
        code, stderr = self._run(["write-state", "/nonexistent/path/does-not-exist.json"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_malformed_write_state_json_is_a_clean_error(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("{not valid json")
            path = fh.name
        code, stderr = self._run(["write-state", path])
        self.assertEqual(code, 1)
        self.assertIn("Error:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_invalid_state_schema_is_a_clean_error(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump({"schema_version": 999}, fh)
            path = fh.name
        code, stderr = self._run(["write-state", path])
        self.assertEqual(code, 1)
        self.assertIn("Error:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_malformed_remap_keycode_is_a_clean_error(self):
        # "zzz" is neither a known keycode name nor valid hex.
        code, stderr = self._run(["remap", "a", "zzz", "--interval", "0"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_out_of_range_raw_hex_keycode_is_a_clean_error(self):
        code, stderr = self._run(["remap", "a", "1ff", "--interval", "0"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_enter_vendor_usb_error_is_translated_not_a_traceback(self):
        # Regression target: enter_vendor_mode() used to be called OUTSIDE
        # the try/except entirely for both call sites (standalone
        # 'enter-vendor' and the auto-handshake fallback below).
        def _raise(*a, **k):
            exc = usb.core.USBError("boom")
            exc.errno = 16
            raise exc
        cli_main.enter_vendor_mode = _raise
        code, stderr = self._run(["enter-vendor"])
        self.assertEqual(code, 1)
        self.assertIn("busy", stderr.lower())
        self.assertNotIn("Traceback", stderr)

    def test_auto_handshake_usb_error_is_translated_not_a_traceback(self):
        # Same regression, the other call site: find_writable_device()
        # reports "not ready yet", so main() falls back to calling
        # enter_vendor_mode() itself.
        cli_main.find_writable_device = lambda: (None, False)

        def _raise(*a, **k):
            exc = usb.core.USBError("boom")
            exc.errno = 13
            raise exc
        cli_main.enter_vendor_mode = _raise
        code, stderr = self._run(["remap", "a", "f12"])
        self.assertEqual(code, 1)
        self.assertIn("Permission denied", stderr)
        self.assertNotIn("Traceback", stderr)


class _DeadControllerSession(_NoOpSettleSession):
    """A dongle session that's fully claimable but never gets a real
    response -- the controller-off/unpaired case behind the dongle."""

    def probe_controller_live(self, *a, **k):
        return False


class _DeadControllerSessionCM(_FakeSessionCM):
    """Also captures the session, so a test can confirm whether dispatch
    actually ran (a real write got sent) -- the only reliable way to tell
    "probe_controller_live() correctly gated this" from "it happened to not
    matter" when the wired path is expected to skip the check entirely."""
    captured = None

    def __init__(self, _dev, via_dongle=False):
        self.session = _DeadControllerSession()
        type(self).captured = self.session


class DongleNoControllerTest(unittest.TestCase):
    """The dongle enumerates on USB (and is fully claimable) whether or not
    a physical controller is powered on/paired to it -- so
    find_writable_device() succeeding is not proof a controller answered.
    The CLI must catch this via probe_controller_live() and exit cleanly
    instead of running the requested command against a dead link."""

    def setUp(self):
        self._orig_find = cli_main.find_writable_device
        self._orig_session = cli_main.VendorSession
        self._orig_argv = sys.argv
        cli_main.find_writable_device = lambda: (object(), True)  # dongle, no handshake needed
        cli_main.VendorSession = _DeadControllerSessionCM

    def tearDown(self):
        cli_main.find_writable_device = self._orig_find
        cli_main.VendorSession = self._orig_session
        sys.argv = self._orig_argv

    def _run(self, argv):
        sys.argv = ["g7ctl", *argv]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli_main.main()
        return ctx.exception.code, stderr.getvalue()

    def test_exits_cleanly_instead_of_dispatching(self):
        code, stderr = self._run(["remap", "a", "f12", "--interval", "0"])
        self.assertEqual(code, 1)
        self.assertIn("no controller answered", stderr.lower())
        self.assertNotIn("Traceback", stderr)

    def test_wired_path_is_unaffected(self):
        # via_dongle=False must never call probe_controller_live() at all --
        # PID_VENDOR is the controller's own USB descriptor, so its mere
        # presence already proves it's there. _DeadControllerSession's
        # probe_controller_live() always returns False, so if the CLI ever
        # called it for a wired session, dispatch would never run and no
        # write would land -- assert the opposite: dispatch actually ran.
        cli_main.find_writable_device = lambda: (object(), False)
        sys.argv = ["g7ctl", "remap", "a", "f12", "--interval", "0"]
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            cli_main.main()  # must return normally, not sys.exit(1)
        _DeadControllerSessionCM.captured.only_payload()  # raises if nothing was sent


class DpadDockSetCommandTest(unittest.TestCase):
    """Roadmap item 19: dpad-set/dock-set replaced the four old bespoke
    subcommands (dpad-diagonal-lock-set, swap-stick-dpad-set,
    dock-brightness-set, dock-auto-set) with two generic ones, matching
    stick-set/trigger-set/vibration-set's shape. These drive main() end to
    end (device layer faked out) and inspect what actually got sent."""

    def setUp(self):
        self._orig_find = cli_main.find_writable_device
        self._orig_session = cli_main.VendorSession
        self._orig_argv = sys.argv
        cli_main.find_writable_device = lambda: (object(), False)
        cli_main.VendorSession = _CapturingSessionCM

    def tearDown(self):
        cli_main.find_writable_device = self._orig_find
        cli_main.VendorSession = self._orig_session
        sys.argv = self._orig_argv

    def _run(self, argv):
        sys.argv = ["g7ctl", *argv, "--interval", "0"]
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            cli_main.main()
        return _CapturingSessionCM.captured.only_payload()

    def test_dpad_set_diagonal_lock(self):
        payload = self._run(["dpad-set", "diagonal_lock", "on", "--profile", "2"])
        self.assertEqual(payload, bytes([0x03, 0x02, 0x00, 0x2D, 0x01, 0x01]))

    def test_dpad_set_swap_stick_dpad(self):
        payload = self._run(["dpad-set", "swap_stick_dpad", "off", "--profile", "1"])
        self.assertEqual(payload[3], 0x2B)  # SETTING_ID
        self.assertEqual(payload[5], 0x00)  # val_2B

    def test_dock_set_brightness(self):
        payload = self._run(["dock-set", "brightness", "75"])
        self.assertEqual(payload, bytes([0x03, 0x20, 0x01, 0xF9, 0x01, 75]))

    def test_dock_set_auto_on_off(self):
        payload = self._run(["dock-set", "auto_on_off", "off"])
        self.assertEqual(payload, bytes([0x03, 0x20, 0x01, 0xF6, 0x01, 0x00]))

    def test_dpad_set_rejects_unknown_setting_via_argparse(self):
        sys.argv = ["g7ctl", "dpad-set", "not_a_real_setting", "on"]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli_main.build_parser().parse_args(sys.argv[1:])
        self.assertNotEqual(ctx.exception.code, 0)


class NonExitingArgumentParserTest(unittest.TestCase):
    """The parser class batch/REPL mode reparses each line with -- a bad
    line must raise a catchable exception, never call sys.exit(), or one
    typo would kill an entire multi-hundred-line script before it even
    opens a session."""

    def test_bad_action_raises_instead_of_exiting(self):
        parser = cli_main.build_parser(parser_class=cli_main._NonExitingArgumentParser)
        with self.assertRaises(cli_main._BatchLineError):
            parser.parse_args(["not-a-real-action"])

    def test_valid_line_parses_normally(self):
        parser = cli_main.build_parser(parser_class=cli_main._NonExitingArgumentParser)
        args = parser.parse_args(["remap", "a", "f12"])
        self.assertEqual(args.action, "remap")

    def test_top_level_parser_is_unaffected(self):
        # The real CLI entry point must keep its normal exit-on-error
        # behavior -- only batch/REPL mode should ever get the non-exiting
        # variant.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli_main.build_parser().parse_args(["not-a-real-action"])


class BatchDryRunTest(unittest.TestCase):
    """--dry-run must validate every line's syntax without ever touching the
    device layer at all."""

    def setUp(self):
        self._orig_find = cli_main.find_writable_device
        cli_main.find_writable_device = mock.Mock(
            side_effect=AssertionError("dry-run must never call find_writable_device()"))

    def tearDown(self):
        cli_main.find_writable_device = self._orig_find

    def _script(self, lines):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        fh.write("\n".join(lines))
        fh.close()
        return fh.name

    def _run(self, path, extra_args=()):
        sys.argv = ["g7ctl", "batch", path, "--dry-run", *extra_args]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                cli_main.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_all_valid_lines_exit_zero(self):
        path = self._script(["# a comment", "", "remap a f12", "stick-set left invert_x on"])
        code, stdout, _stderr = self._run(path)
        self.assertEqual(code, 0)
        self.assertIn("2/2", stdout)

    def test_bad_line_is_reported_and_exits_nonzero(self):
        path = self._script(["remap a f12", "not-a-real-action", "stick-set left invert_x on"])
        code, stdout, stderr = self._run(path)
        self.assertNotEqual(code, 0)
        self.assertIn("line 2:", stderr)
        self.assertIn("2/3", stdout)

    def test_batch_and_enter_vendor_rejected_inside_a_script(self):
        path = self._script(["enter-vendor", "batch other.txt"])
        code, _stdout, stderr = self._run(path)
        self.assertNotEqual(code, 0)
        self.assertIn("'enter-vendor' isn't valid", stderr)
        self.assertIn("'batch' isn't valid", stderr)


class BatchExecutionTest(unittest.TestCase):
    """Real batch execution (not dry-run) against a faked session -- one
    session, many lines, matching what was hardware-verified live."""

    def setUp(self):
        self._orig_find = cli_main.find_writable_device
        self._orig_session = cli_main.VendorSession
        self._orig_argv = sys.argv
        cli_main.find_writable_device = lambda: (object(), False)
        cli_main.VendorSession = _CapturingSessionCM

    def tearDown(self):
        cli_main.find_writable_device = self._orig_find
        cli_main.VendorSession = self._orig_session
        sys.argv = self._orig_argv

    def _script(self, lines):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        fh.write("\n".join(lines))
        fh.close()
        return fh.name

    def _run(self, path, extra_args=()):
        sys.argv = ["g7ctl", "batch", path, "--interval", "0", *extra_args]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                cli_main.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_multiple_lines_run_in_one_session(self):
        path = self._script([
            "# comment, skipped",
            "",
            "stick-set left invert_x on --profile 2",
            "vibration-set left_grip 50",
        ])
        code, stdout, _stderr = self._run(path)
        self.assertEqual(code, 0)
        self.assertEqual(len(_CapturingSessionCM.captured.payloads), 2)
        self.assertIn("2/2 succeeded", stdout)

    def test_pre_post_heartbeats_are_not_padded_per_line(self):
        # _wrapped_write()'s own pre/post heartbeats are forced to 0 inside
        # batch mode -- the loop's own heartbeat-before/heartbeat-after (2
        # per line) plus one final heartbeat is the only heartbeat activity
        # expected, not the standalone DEFAULT_PRE/POST_HEARTBEATS=3+5=8
        # per write.
        path = self._script(["vibration-set left_grip 50", "vibration-set right_grip 50"])
        self._run(path)
        # 1 heartbeat before each of 2 lines + 1 final heartbeat = 3.
        self.assertEqual(_CapturingSessionCM.captured.heartbeats, 3)

    def test_default_stops_on_first_error(self):
        path = self._script([
            "vibration-set left_grip 50",
            "not-a-real-action",
            "vibration-set right_grip 50",
        ])
        code, stdout, stderr = self._run(path)
        self.assertNotEqual(code, 0)
        self.assertIn("line 2:", stderr)
        self.assertEqual(len(_CapturingSessionCM.captured.payloads), 1)
        self.assertIn("1/2 succeeded", stdout)

    def test_continue_on_error_runs_remaining_lines(self):
        path = self._script([
            "vibration-set left_grip 50",
            "not-a-real-action",
            "vibration-set right_grip 50",
        ])
        code, stdout, stderr = self._run(path, extra_args=["--continue-on-error"])
        self.assertNotEqual(code, 0)  # still nonzero -- one line did fail
        self.assertIn("line 2:", stderr)
        self.assertEqual(len(_CapturingSessionCM.captured.payloads), 2)
        self.assertIn("2/3 succeeded", stdout)


class BatchReplTest(unittest.TestCase):
    """Interactive mode -- same per-line dispatch machinery, fed via a
    mocked input() instead of a script file."""

    def setUp(self):
        self._orig_find = cli_main.find_writable_device
        self._orig_session = cli_main.VendorSession
        self._orig_argv = sys.argv
        cli_main.find_writable_device = lambda: (object(), False)
        cli_main.VendorSession = _CapturingSessionCM

    def tearDown(self):
        cli_main.find_writable_device = self._orig_find
        cli_main.VendorSession = self._orig_session
        sys.argv = self._orig_argv

    def test_repl_dispatches_canned_commands_then_exits_on_eof(self):
        sys.argv = ["g7ctl", "batch", "--interval", "0"]
        inputs = iter(["vibration-set left_grip 50", "exit"])

        def fake_input(prompt=""):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError() from None

        with mock.patch("builtins.input", side_effect=fake_input), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            cli_main.main()

        self.assertEqual(len(_CapturingSessionCM.captured.payloads), 1)

    def test_repl_reports_a_bad_command_and_keeps_going(self):
        sys.argv = ["g7ctl", "batch", "--interval", "0"]
        inputs = iter(["not-a-real-action", "vibration-set left_grip 50", "exit"])

        def fake_input(prompt=""):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError() from None

        with mock.patch("builtins.input", side_effect=fake_input), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            cli_main.main()

        self.assertIn("not-a-real-action", stderr.getvalue())
        self.assertEqual(len(_CapturingSessionCM.captured.payloads), 1)


if __name__ == "__main__":
    unittest.main()


class VersionFlagTest(unittest.TestCase):
    """`--version`, and the batch-safety hole adding it exposed.

    argparse's version action prints and then calls parser.exit() directly,
    never touching parser.error(). _NonExitingArgumentParser overrode only
    error(), so before this the flag (and `-h`, which behaves the same way)
    could end a running batch session from one line -- the exact failure that
    class exists to prevent.
    """

    def test_version_prints_and_exits_zero(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            cli_main.build_parser().parse_args(["--version"])
        self.assertEqual(0, cm.exception.code)
        self.assertIn(f"g7ctl {cli_main.__version__}", buf.getvalue())

    def test_version_names_the_module_it_ran_from(self):
        # The number alone can't separate a release from a -git build (both
        # carry pyproject.toml's version) or a checkout from site-packages.
        self.assertIn(str(Path(cli_main.__file__).resolve().parent),
                      cli_main._version_string())

    def test_version_on_a_batch_line_does_not_end_the_session(self):
        parser = cli_main.build_parser(parser_class=cli_main._NonExitingArgumentParser)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(cli_main._BatchLineError):
                parser.parse_args(["--version"])

    def test_help_on_a_batch_line_does_not_end_the_session_either(self):
        parser = cli_main.build_parser(parser_class=cli_main._NonExitingArgumentParser)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(cli_main._BatchLineError):
                parser.parse_args(["-h"])
