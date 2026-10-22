#!/usr/bin/env python3
"""button-bitfield-capture.py -- guided, one-button-at-a-time live capture
of the button bitfield on input report `0x10` (PROTOCOL.md "The input
stream on report 0x10"): "Which bit of 0x09/0x0A belongs to which button
is not mapped -- the sweep did not record button order reliably." This
is for the Track D / H0 hardware session the g7ctlc redesign's Overview
hero and Buttons diagram need (`DESIGN-SPEC.md` section 6, "Button press
highlights on the drawing | button bitfield, bytes 9-10 | after hardware
session H0") -- the drawing/geometry half of H0 is now covered by
reference artwork instead of a photo session; this script is the
remaining piece, the live data capture.

Safe: read-only, start to finish, same warmup/liveness sequence
`g7ctl/main.py`'s own `_connect_session()` uses before any read. Nothing
here writes a setting, changes a profile, or touches anything on the
controller -- it only opens a session and calls
`VendorSession.read_input_frame()` in a loop, exactly what the GUI's own
live-input plumbing will eventually do.

Methodology, chosen specifically to avoid the 2026-08-08 sweep's own
failure mode (button order not reliably recorded): one button at a time,
user-paced (press Enter, then hold the button while frames are sampled),
diffed against a fresh "nothing pressed" baseline captured immediately
before each button -- not a freeform sweep relying on the user to note
timing against a log after the fact. Diffs the *entire* 63-byte frame,
not just the documented bitfield bytes (9, 10) -- an unexpected byte
changing alongside the expected one is itself a real finding, not
something to silently discard because it wasn't in the documented set.

Usage:
    python3 button-bitfield-capture.py [--out capture.json]

Needs pyg7 importable (run from the repo root, or with it installed) --
unlike g7se-bulk-probe.py, this doesn't need to be a zero-dependency
handoff script; it's for use on this project's own dev machine, and
pyg7.session.VendorSession is the real, already-safe primitive for a
read-only capture like this one, not something worth reimplementing in
raw pyusb.

Please keep the printed transcript (or the --out JSON) for whoever
builds the controller drawing next -- that's the actual point of this
script.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import usb.core
except ImportError:
    print("This needs the 'pyusb' package, which isn't installed.")
    print("Try: python3 -m pip install --user pyusb")
    sys.exit(1)

try:
    from pyg7 import buttons as buttons_mod
    from pyg7.device import find_writable_device, switch_to_xid
    from pyg7.session import EARLY_PROBE_HEARTBEATS, VendorSession
except ImportError:
    print("This needs pyg7 importable -- run from the g7ctl repo root, "
          "or with the package installed.")
    sys.exit(1)

# Same default pacing floor g7ctl/main.py's CLI uses for a fresh handshake.
HANDSHAKE_MIN_INTERVAL = 0.05
# Matches main.py's own DEFAULT_INTERVAL -- "the app's observed heartbeat
# cadence". Used below to keep the session alive through this script's
# user-paced input() waits.
HEARTBEAT_INTERVAL = 0.316

# Physical layout order, matching g7ctlc/views/buttons_view.py's
# _BUTTON_GROUPS -- not reusing that module directly, since it imports
# PyQt6 and this script has no business depending on a GUI toolkit for a
# plain terminal capture session. Kept in sync by hand; both lists are
# small and change rarely.
_BUTTON_GROUPS: list[tuple[str, ...]] = [
    ("a", "b", "x", "y"),
    ("r3", "l3"),
    ("rb", "lb", "r5", "l5"),
    ("rt", "lt", "l4", "r4"),
    ("dpad_up", "dpad_down", "dpad_left", "dpad_right"),
    ("view", "menu", "share"),
]
_BUTTON_LABELS: dict[str, str] = {
    "share": "Share", "a": "A", "b": "B", "x": "X", "y": "Y",
    "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "l3": "L3 (left stick click)", "r3": "R3 (right stick click)",
    "view": "View", "menu": "Menu", "l4": "L4", "r4": "R4",
    "l5": "L5", "r5": "R5",
    "dpad_up": "D-Pad Up", "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left", "dpad_right": "D-Pad Right",
}
# Not in pyg7.buttons.KNOWN_BUTTON_IDS at all -- it isn't remappable, so
# the keycode-binding system has no record of it -- but it's a real,
# physically pressable button the drawing still needs a highlight for.
# Captured last, clearly marked, not mixed into the remappable set above.
_EXTRA_BUTTONS: list[tuple[str, str]] = [
    ("guide", "Xbox/Guide button (not remappable -- diagram only)"),
]

FRAME_LEN = 63          # report 0x10's own fixed payload length (PROTOCOL.md)
BASELINE_FRAMES = 12    # "nothing pressed" samples before each button
HOLD_FRAMES = 20        # samples taken while the button is held
SAMPLE_TIMEOUT = 2.0    # per-frame read timeout while sampling


def _sample_frames(sess: VendorSession, lock: threading.Lock, count: int,
                    timeout: float) -> list[bytes]:
    frames = []
    deadline = time.monotonic() + timeout * count
    while len(frames) < count and time.monotonic() < deadline:
        try:
            with lock:
                frames.append(sess.read_input_frame(timeout=timeout))
        except TimeoutError:
            continue
    return frames


def _drain(sess: VendorSession, lock: threading.Lock, timeout: float = 0.05,
           max_drain: float = 5.0) -> None:
    """Discard any backlog of already-queued input frames so the next real
    sample reflects current state, not stale pre-press state.

    REAL BUG, found capturing 'A' twice in a row with no signal at all
    (2026-10-22): report 0x10 streams continuously, but nothing reads it
    while this script is blocked in input() -- the user reading a prompt
    and getting a finger onto the button. Most visibly after the initial
    connect handshake (several seconds of heartbeats/settling before the
    very first prompt), a real backlog can queue up; reading only a
    handful of frames afterward just dequeues more backlog, never
    reaching "now", so the held sample silently reports the same stale
    state as the baseline. A one-shot fixed-count discard right after
    connecting (the first attempt at this fix) didn't help, because the
    backlog that actually matters builds *during* each prompt's own idle
    wait, not before the loop starts.

    Reads with a short timeout in a tight loop until one actually times
    out -- that's the signal the queue is empty and we're caught up to
    real time -- bounded by max_drain so a genuinely dead connection
    doesn't hang here forever."""
    deadline = time.monotonic() + max_drain
    while time.monotonic() < deadline:
        try:
            with lock:
                sess.read_input_frame(timeout=timeout)
        except TimeoutError:
            return


def _stable_bytes(frames: list[bytes]) -> bytes:
    """The byte-wise mode across a batch of frames -- a single dropped or
    torn frame (always possible over USB) must not look like a changed
    bit. Short of a full majority vote this is overkill for 63 bytes and
    a handful of samples, so: most common value per offset, ties broken
    by the first frame's own value."""
    if not frames:
        return b""
    length = min(len(f) for f in frames)
    out = bytearray(length)
    for i in range(length):
        counts: dict[int, int] = {}
        for f in frames:
            counts[f[i]] = counts.get(f[i], 0) + 1
        out[i] = max(counts.items(), key=lambda kv: (kv[1], -abs(kv[0] - frames[0][i])))[0]
    return bytes(out)


def _held_bytes(rest: bytes, frames: list[bytes], min_occurrences: int = 2) -> bytes:
    """Like _stable_bytes, but tuned for a brief or repeated tap rather
    than one sustained hold held through the whole window.

    REAL BUG, found capturing Guide (2026-10-22): a pure majority vote
    (_stable_bytes) assumes the button stays pressed through most of the
    sampling window. Xbox-style Guide/Home buttons commonly need a
    deliberate, sustained hold before they even register as pressed at
    all, and a *long* sustained hold on Guide specifically risks tripping
    the controller's own built-in "hold Guide to power off" gesture --
    neither a short tap nor a long hold is reliably safe here. A quick
    tap (or several) spends most of the window released, so a strict
    majority vote would silently vote the real signal away as noise,
    same as never pressing it at all.

    Reports, per byte, the most common *non-rest* value seen, as long as
    it occurred in at least min_occurrences frames (filtering a single
    torn/corrupted frame from looking like a real signal) -- falling back
    to rest's own value if nothing cleared that bar."""
    if not frames:
        return rest
    length = min(len(rest), min(len(f) for f in frames))
    out = bytearray(rest[:length])
    for i in range(length):
        counts: dict[int, int] = {}
        for f in frames:
            if f[i] != rest[i]:
                counts[f[i]] = counts.get(f[i], 0) + 1
        if counts:
            best_val, best_count = max(counts.items(), key=lambda kv: kv[1])
            if best_count >= min_occurrences:
                out[i] = best_val
    return bytes(out)


def _diff(rest: bytes, held: bytes) -> list[tuple[int, int, int]]:
    """[(offset, rest_value, held_value), ...] for every byte that
    differs. Offsets beyond PROTOCOL.md's documented ranges (9, 10 the
    processed bitfield; 12, 13 triggers; 55-60 the raw group) are still
    reported, not filtered out -- an unexpected change is a real finding."""
    length = min(len(rest), len(held))
    return [(i, rest[i], held[i]) for i in range(length) if rest[i] != held[i]]


def _bit_summary(rest_val: int, held_val: int) -> str:
    changed = rest_val ^ held_val
    # Per bit, not one guess for the whole byte -- a single press could in
    # principle set one bit and clear another in the same byte (e.g. a
    # shared toggle/latch bit), and collapsing that into one blanket
    # direction would misreport it.
    parts = [f"{b} set" if held_val & (1 << b) else f"{b} cleared"
             for b in range(8) if changed & (1 << b)]
    return f"bit(s) {', '.join(parts)} (0x{rest_val:02x} -> 0x{held_val:02x})"


@contextlib.contextmanager
def _connect(min_interval: float = HANDSHAKE_MIN_INTERVAL):
    """Same connect/settle/liveness sequence as g7ctl/main.py's own
    _connect_session() -- reproduced here rather than imported, since
    that one is private to the CLI module (an underscore name, not a
    published helper) and this script is meant to stand on its own.
    Read-only from here on: nothing below ever sends anything but the
    heartbeats this same warmup always sends.

    Yields (session, lock). The lock guards every real session access --
    see the background heartbeat thread started below."""
    vdev, via_dongle = find_writable_device()
    if vdev is None:
        print("Controller presents the keyboard/mouse interface -- switching it now...")
        vdev, via_dongle = switch_to_xid(min_interval=min_interval)
        if vdev is None:
            print("Could not reach the controller. Plug it in (or connect the "
                  "wireless dongle) and try again.", file=sys.stderr)
            sys.exit(1)
    elif via_dongle:
        print("Using wireless dongle -- already answering, no handshake needed.")

    with VendorSession(vdev, via_dongle=via_dongle) as sess:
        sess.settle(count=EARLY_PROBE_HEARTBEATS)
        live = sess.probe_controller_live(retries=0)
        if not live:
            sess.settle()
            live = sess.probe_controller_live()
        if not live:
            print("Claimed the interface, but no controller answered. Make sure "
                  "it's powered on (and paired, if wireless) and try again.",
                  file=sys.stderr)
            sys.exit(1)

        # REAL BUG hit running this script for real (2026-10-22): this
        # script's input() prompts block with no heartbeat running, same
        # bug g7ctl/main.py's batch REPL hit and fixed on 2026-09-17
        # (session.py's own module docstring: a session with no heartbeat
        # for more than a couple seconds reverts to XInput). Worse here
        # than the REPL -- these prompts are "read it, get in position,
        # press Enter", user-paced with no telling how long that takes.
        # Same fix: a background thread heartbeats on the normal cadence
        # for the whole capture session, guarded by a lock shared with
        # every real read below so a heartbeat can never interleave
        # mid-read (VendorSession has no locking of its own).
        stop_heartbeat = threading.Event()
        session_lock = threading.Lock()

        def _background_heartbeat() -> None:
            while not stop_heartbeat.wait(HEARTBEAT_INTERVAL):
                with session_lock:
                    if stop_heartbeat.is_set():
                        return
                    try:
                        sess.heartbeat()
                    except usb.core.USBError:
                        # Not this thread's job to report it -- the main
                        # thread's own next real session call hits the
                        # same dead session and raises the same way.
                        return

        heartbeat_thread = threading.Thread(target=_background_heartbeat, daemon=True)
        heartbeat_thread.start()
        try:
            yield sess, session_lock
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL * 2)


def _capture_one(sess: VendorSession, lock: threading.Lock, name: str, label: str) -> dict:
    print(f"\n=== {label} ({name}) ===")
    input("  Make sure it is NOT pressed right now, then press Enter... ")
    _drain(sess, lock)
    rest_frames = _sample_frames(sess, lock, BASELINE_FRAMES, SAMPLE_TIMEOUT)
    if len(rest_frames) < BASELINE_FRAMES // 2:
        print(f"  Only got {len(rest_frames)}/{BASELINE_FRAMES} baseline frames -- "
              "connection may be unstable. Recording what we have and continuing.")
    rest = _stable_bytes(rest_frames)

    input(f"  Now PRESS AND HOLD {label}, then press Enter... ")
    _drain(sess, lock)
    held_frames = _sample_frames(sess, lock, HOLD_FRAMES, SAMPLE_TIMEOUT)
    if len(held_frames) < HOLD_FRAMES // 2:
        print(f"  Only got {len(held_frames)}/{HOLD_FRAMES} held frames -- "
              "connection may be unstable. Recording what we have and continuing.")
    print("  You can release it now.")
    held = _held_bytes(rest, held_frames)

    diffs = _diff(rest, held)
    if not diffs:
        print("  No byte changed at all -- nothing captured for this button. "
              "Worth trying again (loose contact, mistimed hold, or this "
              "button genuinely isn't on this report).")
    else:
        for offset, rv, hv in diffs:
            known = " (documented button-bitfield byte)" if offset in (9, 10) else \
                    " (documented trigger byte)" if offset in (12, 13) else \
                    " (documented raw buttons/triggers byte)" if 55 <= offset <= 60 else \
                    " (** not a documented byte for this -- worth a second look **)"
            print(f"  byte {offset:2d}{known}: {_bit_summary(rv, hv)}")
    return {
        "button": name,
        "label": label,
        "rest_frame_hex": rest.hex(),
        "held_frame_hex": held.hex(),
        "diffs": [{"offset": o, "rest": rv, "held": hv} for o, rv, hv in diffs],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None,
                         help="Save the full capture as JSON to this path "
                              "(default: button-bitfield-capture-<timestamp>.json "
                              "in the current directory).")
    parser.add_argument("--only", type=str, default=None,
                         help="Comma-separated button names to (re)capture instead of "
                              "the full 22 -- e.g. --only a to redo just one that came "
                              "back with no signal the first time. Still runs in the "
                              "usual physical-layout order; names not in that order "
                              "(or not recognized at all) are an error, not a silent skip.")
    args = parser.parse_args()
    out_path = args.out or Path(
        f"button-bitfield-capture-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")

    order: list[tuple[str, str]] = []
    for group in _BUTTON_GROUPS:
        for name in group:
            order.append((name, _BUTTON_LABELS[name]))
    order.extend(_EXTRA_BUTTONS)

    missing = [name for name, _ in order if name not in buttons_mod.KNOWN_BUTTON_IDS
               and name not in dict(_EXTRA_BUTTONS)]
    if missing:
        print(f"Internal error: {missing} not in pyg7.buttons.KNOWN_BUTTON_IDS "
              "and not marked as an extra -- this script's own button list has "
              "drifted from the library's. Fix _BUTTON_GROUPS/_EXTRA_BUTTONS "
              "above before continuing.", file=sys.stderr)
        sys.exit(1)

    if args.only:
        wanted = [n.strip() for n in args.only.split(",") if n.strip()]
        known = {name for name, _ in order}
        unknown = [n for n in wanted if n not in known]
        if unknown:
            print(f"Unknown button name(s): {unknown}. Valid names: "
                  f"{sorted(known)}", file=sys.stderr)
            sys.exit(1)
        order = [(name, label) for name, label in order if name in wanted]

    print(f"Will capture {len(order)} button(s), one at a time, in physical "
          "layout order (same grouping the Buttons page uses).")
    print("Each one: confirm it's released, a brief baseline is sampled, then "
          "you press and hold it while frames are sampled.\n")

    results = []
    try:
        with _connect() as (sess, lock):
            for name, label in order:
                results.append(_capture_one(sess, lock, name, label))
    except KeyboardInterrupt:
        print("\nInterrupted -- saving what was captured so far.")
    except usb.core.USBError as e:
        print(f"\nUSB error: {e}. Saving what was captured so far.", file=sys.stderr)

    out_path.write_text(json.dumps(
        {"captured_at": datetime.now(timezone.utc).isoformat(), "frame_length": FRAME_LEN,
         "results": results}, indent=2))
    print(f"\nSaved {len(results)}/{len(order)} button captures to {out_path}")
    print("Please keep this file (or the printed transcript above) for "
          "whoever builds the controller drawing next.")


if __name__ == "__main__":
    main()
