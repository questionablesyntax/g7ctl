"""DeviceWatcher._establish() tests: the liveness gate.

Raised 2026-07-30 from real daily use: the 2.4GHz dongle enumerates on USB
(and claims, and heartbeats fine) whether or not a physical controller is
actually powered on and paired to it -- they're two separate things joined
by an RF link. Before this fix, DeviceWatcher reported "connected" the
instant the dongle was found, regardless, and every subsequent read/write
just failed silently against a live-looking but dead connection. Runs
unconditionally as of the 2026-08-29 detection redesign -- wired and dongle
alike, since real wired/dongle detection turned out not to be possible at
all (see pyg7/device.py's find_writable_device() docstring).

_connect() (real USB discovery) is monkeypatched to return a fake
session-like object -- these tests are about what _establish() does with
whatever _connect() hands it, not about USB discovery itself. Runs headless
(offscreen platform); skipped entirely if PyQt6 is absent, same as the other
g7ctlc test modules.
"""
import os
import time
import unittest
from unittest import mock

import usb.core

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


class _FakeSession:
    """Stands in for VendorSession -- just enough surface for _establish()."""

    def __init__(self, via_dongle: bool, live: bool = True):
        self.via_dongle = via_dongle
        self._live = live
        self.settled = False
        self.torn_down = False
        self.probed = False

    def settle(self) -> None:
        self.settled = True

    def probe_controller_live(self) -> bool:
        self.probed = True
        return self._live

    def __exit__(self, *exc) -> bool:
        self.torn_down = True
        return False


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class EstablishSessionTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self, connect_result):
        from g7ctlc.watcher import DeviceWatcher
        watcher = DeviceWatcher()
        watcher._connect = lambda: connect_result
        return watcher

    def test_wired_session_is_probed_too_and_becomes_connected(self):
        # Redesigned 2026-08-29: the liveness probe now runs
        # unconditionally, wired or dongle alike -- real wired/dongle
        # detection turned out not to be possible at all (a wired
        # baseline and its dongle counterpart share an identical
        # descriptor shape). This
        # test used to assert the opposite (wired must skip the probe
        # entirely) -- a healthy wired connection just passes it the same
        # way any other read succeeds, at the cost of one harmless extra
        # round trip.
        session = _FakeSession(via_dongle=False)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIs(result, session)
        self.assertTrue(session.settled)
        self.assertTrue(session.probed)
        self.assertFalse(session.torn_down)
        self.assertEqual(watcher._state, "connected")

    def test_dongle_session_with_live_controller_becomes_connected(self):
        session = _FakeSession(via_dongle=True, live=True)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIs(result, session)
        self.assertTrue(session.settled)
        self.assertFalse(session.torn_down)
        self.assertEqual(watcher._state, "connected")

    def test_dongle_session_with_no_controller_is_torn_down_not_connected(self):
        session = _FakeSession(via_dongle=True, live=False)
        watcher = self._watcher(session)
        result = watcher._establish()
        self.assertIsNone(result)
        self.assertTrue(session.settled)  # still warms up before probing
        self.assertTrue(session.torn_down)
        self.assertEqual(watcher._state, "no_controller")

    def test_no_controller_sets_a_probe_failure_backoff(self):
        # Raised 2026-08-30 from real daily use, the day after the liveness
        # probe became unconditional: a controller landing from PID_HID
        # sometimes kept losing its session shortly after connecting,
        # round-tripping back to PID_HID on release (confirmed release
        # behavior) and re-handshaking immediately -- a sustained
        # 100a<->109b oscillation, captured live (6 re-enum events across
        # ~36s). run()'s loop checks _probe_backoff_until before retrying
        # _establish() at all; this pins that a failed probe actually sets
        # it, in the future, not left at its initial 0.0.
        import time
        session = _FakeSession(via_dongle=False, live=False)
        watcher = self._watcher(session)
        before = time.time()
        watcher._establish()
        self.assertGreater(watcher._probe_backoff_until, before)

    def test_no_device_found_leaves_state_disconnected(self):
        watcher = self._watcher(None)
        result = watcher._establish()
        self.assertIsNone(result)
        self.assertEqual(watcher._state, "disconnected")  # unchanged from init

    def test_no_controller_state_recovers_once_a_controller_answers(self):
        # The whole point of treating this as "keep polling", not a hard
        # error: a real DeviceWatcher.run() loop retries _establish() on its
        # next iteration whenever session is None -- confirm a fresh
        # _establish() call succeeds cleanly right after a failed one, with
        # nothing left over from the torn-down attempt.
        watcher = self._watcher(_FakeSession(via_dongle=True, live=False))
        self.assertIsNone(watcher._establish())
        self.assertEqual(watcher._state, "no_controller")

        recovered = _FakeSession(via_dongle=True, live=True)
        watcher._connect = lambda: recovered
        result = watcher._establish()
        self.assertIs(result, recovered)
        self.assertEqual(watcher._state, "connected")


class _RaisingSession(_FakeSession):
    """Like _FakeSession, but settle()/probe_controller_live() can raise
    instead of completing -- for the USBError-during-warmup regression
    below. `raise_on` picks which call fails ("settle" or "probe")."""

    def __init__(self, raise_on: str, **kwargs):
        super().__init__(**kwargs)
        self._raise_on = raise_on

    def settle(self) -> None:
        super().settle()
        if self._raise_on == "settle":
            raise usb.core.USBError("settle failed")

    def probe_controller_live(self) -> bool:
        super().probe_controller_live()
        if self._raise_on == "probe":
            raise usb.core.USBError("probe failed")
        return self._live


class EstablishSessionWarmupErrorTest(unittest.TestCase):
    """Real bug, found 2026-09-01 (second bug-hunt pass): a USBError raised
    by settle()/probe_controller_live() itself -- not just
    probe_controller_live() returning False, already covered by
    EstablishSessionTest above -- used to propagate straight out of
    _establish() with the interface still claimed and the kernel driver
    still detached. run()'s own except block only ever discards its local
    `session` reference; it never had a chance to tear down the actual
    VendorSession object _establish() created. The next claim attempt
    could then fail as "device busy" (interface still held by the leaked
    session), turning a transient bus blip into a stuck disconnected state
    until the whole USB device was replugged or the process restarted.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self, session):
        from g7ctlc.watcher import DeviceWatcher
        watcher = DeviceWatcher()
        watcher._connect = lambda: session
        return watcher

    def test_a_usb_error_during_settle_still_tears_down_the_session(self):
        session = _RaisingSession(raise_on="settle", via_dongle=False)
        watcher = self._watcher(session)
        with self.assertRaises(usb.core.USBError):
            watcher._establish()
        self.assertTrue(session.torn_down, "the session must be released even though settle() raised")

    def test_a_usb_error_during_the_liveness_probe_still_tears_down_the_session(self):
        session = _RaisingSession(raise_on="probe", via_dongle=False)
        watcher = self._watcher(session)
        with self.assertRaises(usb.core.USBError):
            watcher._establish()
        self.assertTrue(session.torn_down, "the session must be released even though probe raised")


if __name__ == "__main__":
    unittest.main()


class _BatterySession:
    """Serves scripted read_battery() results; records nothing else."""

    def __init__(self, results):
        self.via_dongle = False
        self._results = list(results)
        self.calls = 0
        self.timeouts = []

    def read_battery(self, timeout=None):
        self.calls += 1
        self.timeouts.append(timeout)
        item = self._results.pop(0) if self._results else TimeoutError("quiet")
        if isinstance(item, Exception):
            raise item
        return item


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class BatteryPollTest(unittest.TestCase):
    """DeviceWatcher._poll_battery().

    The invariant that matters is not the reading -- it is that a battery
    sample can never take the session down. It rides in the same loop that
    heartbeats, and a heartbeat gap is what makes the firmware drop vendor
    mode.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self):
        from g7ctlc.watcher import DeviceWatcher
        return DeviceWatcher()

    def test_emits_a_reading(self):
        from pyg7.session import BatteryStatus
        w = self._watcher()
        seen = []
        w.battery_changed.connect(lambda p, c: seen.append((p, c)))
        w._poll_battery(_BatterySession([BatteryStatus(46, False)]))
        self.assertEqual(seen, [(46, False)])

    def test_rate_limited_between_polls(self):
        from pyg7.session import BatteryStatus
        w = self._watcher()
        sess = _BatterySession([BatteryStatus(46, False), BatteryStatus(47, False)])
        w._poll_battery(sess)
        w._poll_battery(sess)   # immediately after -- must not sample again
        self.assertEqual(sess.calls, 1)

    def test_unchanged_reading_is_not_re_emitted(self):
        from pyg7.session import BatteryStatus
        w = self._watcher()
        seen = []
        w.battery_changed.connect(lambda p, c: seen.append((p, c)))
        sess = _BatterySession([BatteryStatus(46, False), BatteryStatus(46, False)])
        w._poll_battery(sess)
        w._battery_due = 0.0
        w._poll_battery(sess)
        self.assertEqual(len(seen), 1)

    def test_a_timeout_is_swallowed_not_raised(self):
        # A quiet stream must not look like connection loss -- the run loop
        # treats a raised exception as a reason to tear the session down.
        w = self._watcher()
        w._poll_battery(_BatterySession([TimeoutError("quiet")]))  # must not raise

    def test_a_bad_frame_is_swallowed_not_raised(self):
        w = self._watcher()
        w._poll_battery(_BatterySession([ValueError("battery byte out of range")]))

    def test_a_usb_error_still_propagates(self):
        # Genuine connection loss is the run loop's job, not something to
        # hide behind a missing battery reading.
        import usb.core
        w = self._watcher()
        with self.assertRaises(usb.core.USBError):
            w._poll_battery(_BatterySession([usb.core.USBError("no such device")]))

    def test_read_timeout_is_much_tighter_than_a_config_read(self):
        from g7ctlc.watcher import BATTERY_READ_TIMEOUT
        from pyg7.session import READ_CHUNK_TIMEOUT
        self.assertLess(BATTERY_READ_TIMEOUT, READ_CHUNK_TIMEOUT)

    def test_forgetting_clears_and_lets_the_same_value_re_emit(self):
        # Without this, the change-only emit would suppress an identical
        # reading on reconnect and the label would stay blank.
        from pyg7.session import BatteryStatus
        w = self._watcher()
        seen, gone = [], []
        w.battery_changed.connect(lambda p, c: seen.append((p, c)))
        w.battery_unknown.connect(lambda: gone.append(True))
        sess = _BatterySession([BatteryStatus(46, False), BatteryStatus(46, False)])
        w._poll_battery(sess)
        w._forget_battery()
        w._poll_battery(sess)
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(gone), 1)


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class RunLoopBackoffTest(unittest.TestCase):
    """run()'s own backoff-skip logic -- untested until now (only
    _establish() in isolation is covered above). Raised 2026-08-30 from
    real daily use: a session that starts on HID-needing content
    round-trips straight back to PID_HID on release, so losing the
    connection and retrying immediately just re-triggers the whole
    handshake cycle again -- exactly the rapid-re-enumeration pattern
    HANDSHAKE_MIN_INTERVAL already exists to pace against for handshake
    sends specifically, just via a path that pacing never covered. Only
    ever verified live against real hardware before this test existed.

    Drives run() directly with time.sleep mocked to a fast,
    iteration-counting stub that stops the loop deterministically, rather
    than needing a real thread or a real timeout.
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_backoff_skips_establish_until_it_expires(self):
        from g7ctlc.watcher import PROBE_FAILURE_BACKOFF, DeviceWatcher

        watcher = DeviceWatcher()
        establish_calls = []

        def fake_establish():
            establish_calls.append(1)
            # Mirrors what a real failure inside _establish() does: sets
            # the backoff deadline before returning None.
            watcher._probe_backoff_until = time.time() + PROBE_FAILURE_BACKOFF
            return None

        watcher._establish = fake_establish

        sleep_calls = []

        def fake_sleep(interval):
            sleep_calls.append(interval)
            if len(sleep_calls) >= 4:
                watcher._stop = True

        with mock.patch("g7ctlc.watcher.time.sleep", side_effect=fake_sleep):
            watcher.run()

        # _establish() only ever got one real chance -- the backoff
        # deadline it set on that first (fake) failure should have kept
        # every later loop iteration in this test from calling it again.
        self.assertEqual(len(establish_calls), 1)
        self.assertGreaterEqual(len(sleep_calls), 4)

    def test_no_backoff_means_establish_is_retried_every_iteration(self):
        # Contrast case: confirms the previous test is actually pinning the
        # backoff, not some other reason _establish() is only called once
        # (e.g. the loop exiting early). With no deadline ever set, a
        # failing _establish() should be retried every iteration.
        from g7ctlc.watcher import DeviceWatcher

        watcher = DeviceWatcher()
        establish_calls = []
        watcher._establish = lambda: establish_calls.append(1) or None

        sleep_calls = []

        def fake_sleep(interval):
            sleep_calls.append(interval)
            if len(sleep_calls) >= 4:
                watcher._stop = True

        with mock.patch("g7ctlc.watcher.time.sleep", side_effect=fake_sleep):
            watcher.run()

        self.assertEqual(len(establish_calls), len(sleep_calls))


class _MinimalSession:
    """Just enough surface for one normal run() iteration to complete
    (heartbeat() gets called; the rest of that iteration's helpers are
    mocked to no-ops by the test) plus a clean teardown."""

    def heartbeat(self) -> None:
        pass

    def __exit__(self, *exc) -> bool:
        return False


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class PauseDrainsQueuedJobTest(unittest.TestCase):
    """Real bug, found 2026-09-01: run() checked self._paused before ever
    draining queued jobs each iteration, so a sync/read requested right
    before pause() landed -- e.g. clicking Release Device right after Sync
    Now, well within the up-to-HEARTBEAT_INTERVAL gap between the job being
    queued and the next iteration -- got silently dropped: that iteration
    tore the session down and went straight to "paused" without ever
    checking the queue. sync_finished/read_finished never fired, leaving
    MainWindow._syncing stuck True until an app restart (sync_btn/read_btn
    permanently disabled, even after reconnecting).
    """
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_queued_job_is_drained_before_the_session_is_torn_down(self):
        from g7ctlc.watcher import DeviceWatcher

        watcher = DeviceWatcher()
        fake_session = _MinimalSession()
        watcher._establish = lambda: fake_session
        watcher._read_firmware_once = lambda session: None
        watcher._poll_active_profile = lambda session: None
        watcher._poll_battery = lambda session: None

        drained_with = []
        watcher._drain_jobs = lambda session: drained_with.append(session)

        sleep_calls = []

        def fake_sleep(interval):
            sleep_calls.append(interval)
            if len(sleep_calls) == 1:
                # The exact race: pause() lands in the gap between one
                # normal iteration finishing (this sleep) and the next
                # one starting -- session is already established and live.
                watcher._paused = True
            else:
                watcher._stop = True

        with mock.patch("g7ctlc.watcher.time.sleep", side_effect=fake_sleep):
            watcher.run()

        # _drain_jobs() must have run against the still-live session from
        # the paused branch too, not just the one normal-iteration call
        # before pause landed.
        self.assertEqual(drained_with, [fake_session, fake_session])

    def test_a_usb_error_during_the_paused_drain_does_not_crash_the_loop(self):
        # The drain can still fail (device actually disconnected) -- must
        # be caught and reported like the normal-path drain is, not left
        # to propagate out of run() entirely.
        import usb.core

        from g7ctlc.watcher import DeviceWatcher

        watcher = DeviceWatcher()
        fake_session = _MinimalSession()
        watcher._establish = lambda: fake_session
        watcher._read_firmware_once = lambda session: None
        watcher._poll_active_profile = lambda session: None
        watcher._poll_battery = lambda session: None

        def failing_drain(session):
            raise usb.core.USBError("gone")

        errors = []
        watcher.error.connect(errors.append)

        sleep_calls = []

        def fake_sleep(interval):
            sleep_calls.append(interval)
            if len(sleep_calls) == 1:
                watcher._paused = True
                watcher._drain_jobs = failing_drain
            else:
                watcher._stop = True

        with mock.patch("g7ctlc.watcher.time.sleep", side_effect=fake_sleep):
            watcher.run()  # must not raise

        self.assertTrue(any("Lost connection" in e for e in errors))


class _RaisingExitSession:
    """__exit__() itself raises, past whatever internal handling
    VendorSession.__exit__() already does for release_interface()/
    attach_kernel_driver() -- exercises _teardown()'s own outer net."""

    def __exit__(self, *exc) -> bool:
        raise usb.core.USBError("gone mid-teardown")
        return False  # pragma: no cover - unreachable, mirrors real __exit__'s shape


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class TeardownDoesNotVanishSilentlyTest(unittest.TestCase):
    """Real gap, found by a dedicated active-debugging-infrastructure pass,
    2026-09-01: _teardown()'s `except Exception: pass` contradicted this
    codebase's own stated philosophy, quoted directly from
    VendorSession.__exit__()'s own comment right next to what this wraps --
    "shouldn't vanish with zero trace anywhere." See
    DEBUGGING-INFRA-PLAN-2026-09-01.md."""

    def test_a_teardown_exception_is_logged_not_swallowed_silently(self):
        from g7ctlc.watcher import DeviceWatcher

        with self.assertLogs("g7ctlc.watcher", level="DEBUG") as ctx:
            DeviceWatcher._teardown(_RaisingExitSession())  # must not raise
        self.assertTrue(any("session teardown failed" in line for line in ctx.output))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class EmitErrorIsLoggedTest(unittest.TestCase):
    """Real gap, found live-testing tonight's own debug-logging work
    against real hardware, 2026-09-01: _emit_error() only ever emitted a
    Qt signal -- reaching the GUI's status label for exactly one state
    change before the next update overwrote it -- and never touched
    logging at all. The actual reason a reconnect cycle happened (which
    of heartbeat()/firmware-read/profile-poll/battery-poll raised, and
    the real USBError) was invisible in the log file even at DEBUG with
    -v; only the downstream _teardown() symptom ever showed up there."""

    def test_emit_error_logs_at_warning_as_well_as_emitting_the_signal(self):
        from g7ctlc.watcher import DeviceWatcher

        watcher = DeviceWatcher()
        received = []
        watcher.error.connect(received.append)

        with self.assertLogs("g7ctlc.watcher", level="WARNING") as ctx:
            watcher._emit_error("Lost connection: [Errno 19] gone")

        self.assertEqual(received, ["Lost connection: [Errno 19] gone"])
        self.assertTrue(any("Lost connection: [Errno 19] gone" in line for line in ctx.output))

    def test_a_deduped_repeat_does_not_log_again(self):
        """Matches the existing dedup contract for the signal -- a
        persistent condition (e.g. no udev permission) logging once per
        poll cycle would spam the log file exactly as badly as it would
        have spammed the GUI without the original dedup guard."""
        import logging

        from g7ctlc.watcher import DeviceWatcher

        watcher = DeviceWatcher()
        watcher._emit_error("USB error: gone")

        with self.assertRaises(AssertionError):  # assertLogs itself raises if nothing logs
            with self.assertLogs("g7ctlc.watcher", level=logging.WARNING):
                watcher._emit_error("USB error: gone")  # same message again
