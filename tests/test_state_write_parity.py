"""S1 parity gate (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S).

`tests/fixtures/s1_write_state_trace.json` is a frozen, unified, ordered
trace of every send/heartbeat/read/sleep `write_state()` produced against
a single wide-coverage state dict, captured from the code *before* S1's
Operation refactor landed. This test replays the same state dict against
the current code and asserts the trace is identical, event for event, in
order -- the thing FakeSession's separate `.sent`/`.heartbeats` counters
can't prove (two code paths could match on counts while differing in
interleaving or order). A single byte or a reordered heartbeat anywhere
in a 400+-event trace fails this test.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from pyg7 import state as state_mod

from .fakes import TracingFakeSession

FIXTURE = Path(__file__).parent / "fixtures" / "s1_write_state_trace.json"


def _load_fixture():
    with open(FIXTURE) as f:
        return json.load(f)


def _deserialize_trace(serializable):
    trace = []
    for ev in serializable:
        kind = ev[0]
        if kind == "send_raw":
            trace.append(("send_raw", ev[1], bytes.fromhex(ev[2])))
        elif kind == "heartbeat":
            trace.append(("heartbeat",))
        elif kind == "read_chunk":
            trace.append(("read_chunk", ev[1], ev[2], ev[3]))
        elif kind == "sleep":
            trace.append(("sleep", ev[1]))
        else:
            raise AssertionError(f"unknown trace event kind: {kind!r}")
    return trace


class WriteStateParityTest(unittest.TestCase):
    def test_write_state_trace_matches_the_frozen_golden_trace(self):
        fixture = _load_fixture()
        expected_trace = _deserialize_trace(fixture["trace"])

        trace: list = []
        sess = TracingFakeSession(trace=trace)
        with mock.patch.object(state_mod.time, "sleep", lambda s: trace.append(("sleep", s))):
            skipped = state_mod.write_state(sess, fixture["state"], interval=0.01)

        self.assertEqual(skipped, fixture["skipped"])
        self.assertEqual(
            len(trace), len(expected_trace),
            f"trace length changed: {len(trace)} events vs {len(expected_trace)} expected "
            "-- something now sends/heartbeats/sleeps a different number of times")
        for i, (actual, expected) in enumerate(zip(trace, expected_trace)):
            self.assertEqual(actual, expected, f"trace diverges at event {i}: {actual!r} != {expected!r}")
