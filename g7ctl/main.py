#!/usr/bin/env python3
"""
Reverse-engineered CLI for the GameSir G7 Pro's vendor config protocol.
See PROTOCOL.md for the wire-format reference.

Confirmed via USB capture + testing:
  - Default runtime identity:  VID 0x3537 PID 0x100a ("Xbox 360 Controller for Windows")
  - Vendor/config identity:    VID 0x3537 PID 0x109b ("GameSir-G7 Pro")
  - Switching 100a -> 109b requires no windows app: send the ASCII string
    "gamesirapp" as 5 chunks of 2 chars to interrupt OUT endpoint 0x02, each
    chunk padded to 8 bytes as [00 08 00 c1 c2 00 00 00], interleaved with an
    empty flush packet [00 08 00 00 00 00 00 00]. The device disconnects and
    re-enumerates as 109b roughly 1-1.5s after the last chunk.
  - NOTE: the real app also does a report-ID-0x06 exchange before this,
    whose purpose is still unknown. It is NOT required for this tool's
    handshake or writes to work.
  - Once in 109b, all config writes are sent as 64-byte interrupt OUT reports
    on endpoint 0x02, format:
        0f 00 [SEQ] 3c [payload] 00 00 ... (zero pad to 64)
    SEQ increments each command sent (shared with the heartbeat 0f 00 SEQ 02 f2 00).
    Buttons category payload: 03 [PROFILE+LAYER] 00 [BUTTON_ID] 01 [KEYCODE].
    PROFILE+LAYER: one byte encodes BOTH the target profile (1-4) and layer:
    byte = profile + (4 if shift layer else 0), but only five values exist --
    01-04 (Default layer) and 05 (Profile 1's Shift layer). Profiles 2-4 have
    no Shift layer, and the firmware answers the categories the formula
    predicts for them (06/07/08) with Profile 1's blob rather than an error,
    so asking for one silently hits Profile 1. See PROTOCOL.md "Profile
    scoping". Sticks/Triggers/Vibrations use their own
    category prefixes -- see pyg7/sticks.py, triggers.py, vibration.py.
  - IMPORTANT: an isolated write with no heartbeat before/after appears to
    get silently discarded (device reverts to XInput almost instantly and
    the app-visible config doesn't change). Wrapping the write with a few
    heartbeats before and after made writes stick reliably in testing.
  - Confirmed onboard/firmware persistence for button remaps: writes here DO
    survive power cycles and work standalone (no PC/app needed) once written
    to the correct profile/layer, confirmed by testing physical button
    presses against /dev/input/eventN (the controller exposes a genuine
    second HID interface -- "... Keyboard" / "... Mouse" -- on interface 1.1
    in 100a mode; that's what actually emits the remapped key/mouse events).
"""
import argparse
import contextlib
import importlib.metadata
import logging
import shlex
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Callable, Optional

import usb.core

from pyg7 import buttons, dock_settings, dpad_options, report_rate, sticks, triggers, vibration
from pyg7 import state as state_mod
from pyg7.device import enter_vendor_mode, find_writable_device
from pyg7.session import SHIFT_LAYER_PROFILES, VendorSession, shift_layer_supported

from . import __version__

DEFAULT_PRE_HEARTBEATS = 3
DEFAULT_POST_HEARTBEATS = 5
DEFAULT_INTERVAL = 0.316   # matches the app's observed heartbeat cadence

# batch/REPL mode: one continuous session instead of one
# handshake per command. The loop itself keeps the session alive, so
# individual lines don't need the pre/post heartbeat sandwich _wrapped_write()
# uses for a standalone invocation -- see _dispatch_batch_args().
BATCH_HEARTBEAT_INTERVAL = 0.25   # matches g7ctlc/watcher.py's cadence
BATCH_NOT_ALLOWED = ("batch", "enter-vendor")


class _BatchLineError(Exception):
    """A single batch/REPL line failed to parse or is not valid here."""


class _NonExitingArgumentParser(argparse.ArgumentParser):
    """Like ArgumentParser, but a bad line raises _BatchLineError instead of
    printing usage and calling sys.exit() -- one typo in a 100-line script
    must not kill the whole process before it even opens a session.
    add_subparsers() propagates this class to every subparser automatically
    (it defaults parser_class to type(self)), so build_parser() only needs
    to construct the top-level parser with this class to cover every
    subcommand."""

    def error(self, message: str) -> None:
        raise _BatchLineError(message)

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        """Same contract as error(), for the argparse actions that terminate
        without going through it -- `--version` and `-h` both print and then
        call exit() directly. Overriding error() alone left those two able to
        kill a running batch session from a single line, which is precisely
        what this class exists to prevent. Nothing inside a batch line has a
        legitimate reason to end the process."""
        if message:
            raise _BatchLineError(message.strip())
        raise _BatchLineError("this option isn't valid inside a batch session")


def _add_heartbeat_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pre-heartbeats", type=int, default=DEFAULT_PRE_HEARTBEATS,
                         help=f"Heartbeats to send before the write, to look like an established session (default {DEFAULT_PRE_HEARTBEATS})")
    parser.add_argument("--post-heartbeats", type=int, default=DEFAULT_POST_HEARTBEATS,
                         help=f"Heartbeats to send after the write, to let it 'stick' before we go silent (default {DEFAULT_POST_HEARTBEATS})")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                         help=f"Seconds between heartbeats, matches observed app cadence (default {DEFAULT_INTERVAL})")


def _wrapped_write(sess: VendorSession, args: argparse.Namespace, write_fn: Callable[[VendorSession], bytes]) -> None:
    for _ in range(args.pre_heartbeats):
        sess.heartbeat()
        time.sleep(args.interval)
    pkt = write_fn(sess)
    print(f"  sent: {pkt.hex()}")
    for _ in range(args.post_heartbeats):
        time.sleep(args.interval)
        sess.heartbeat()


def _version_string() -> str:
    """What `--version` prints.

    Leads with this package's own `__version__` -- the version of the code
    that is actually executing -- rather than installed distribution
    metadata. Running `python3 g7ctl_tool.py` from a checkout on a machine
    that also has the package installed imports the checkout, and the
    metadata would name the installed package instead: the wrong answer to
    the only question `--version` is ever asked.

    The module path is appended because neither number distinguishes the two
    package sets this project ships. `g7ctl-git` builds the same
    pyproject.toml version as `g7ctl` -- only its *pacman* version carries
    the revision -- so "0.1.3" alone cannot tell a release apart from a VCS
    build, while the path separates a checkout from site-packages at a
    glance.

    Distribution metadata still appears when it disagrees, which means
    either a checkout running ahead of the installed package or genuine
    drift between g7ctl/__init__.py and pyproject.toml (a release bumps five
    version strings by hand; tests/test_version.py pins them together).
    """
    line = f"g7ctl {__version__} ({Path(__file__).resolve().parent})"
    try:
        installed = importlib.metadata.version("g7ctl")
    except importlib.metadata.PackageNotFoundError:
        return line
    if installed != __version__:
        line += f" [installed distribution reports {installed}]"
    return line


def build_parser(parser_class: type = argparse.ArgumentParser) -> argparse.ArgumentParser:
    """`parser_class` is a hook for batch/REPL mode's _NonExitingArgumentParser
    -- every other caller (the real CLI entry point) gets the normal
    exit-on-error argparse.ArgumentParser, unchanged."""
    ap = parser_class(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # Safe on the batch/REPL parser too: _NonExitingArgumentParser.exit()
    # turns the terminating actions into a per-line error instead of ending
    # the session.
    ap.add_argument("--version", action="version", version=_version_string())
    sub = ap.add_subparsers(dest="action", required=True)

    sub.add_parser("enter-vendor", help="Switch the controller from XInput mode into vendor/config mode.")

    p_remap = sub.add_parser("remap", help="Send a button remap command (device must already be in vendor mode).")
    p_remap.add_argument("button", help=f"Button ID: name ({', '.join(buttons.KNOWN_BUTTON_IDS)}) or raw hex bytes")
    p_remap.add_argument("keycode", help=f"Target keycode: name ({', '.join(buttons.KNOWN_KEYCODES)}) or raw hex byte")
    _add_heartbeat_args(p_remap)
    p_remap.add_argument("--shift", action="store_true",
                          help="Target the Shift Layer instead of the Default layer (Profile 1 only)")
    p_remap.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4], help="Target profile 1-4 (default 1)")

    p_unbind = sub.add_parser("unbind", help="Clear a button's binding entirely (device must already be in vendor mode).")
    p_unbind.add_argument("button", help=f"Button ID: name ({', '.join(buttons.KNOWN_BUTTON_IDS)}) or raw hex bytes")
    _add_heartbeat_args(p_unbind)
    p_unbind.add_argument("--shift", action="store_true",
                           help="Target the Shift Layer instead of the Default layer (Profile 1 only)")
    p_unbind.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4], help="Target profile 1-4 (default 1)")

    p_stick = sub.add_parser("stick-set", help="Set a Sticks-tab setting (device must already be in vendor mode).")
    p_stick.add_argument("side", choices=["left", "right"])
    p_stick.add_argument("setting", choices=sorted(sticks.SETTINGS))
    p_stick.add_argument("value", help="Value: number, on/off, or preset/mode name depending on the setting")
    p_stick.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4],
                          help="Target profile 1-4 (default 1) -- confirmed genuinely profile-scoped, "
                               "same as Buttons.")
    _add_heartbeat_args(p_stick)

    p_trig = sub.add_parser("trigger-set", help="Set a Triggers-tab setting (device must already be in vendor mode).")
    p_trig.add_argument("side", choices=["left", "right"])
    p_trig.add_argument("setting", choices=sorted(triggers.SETTINGS))
    p_trig.add_argument("value", help="Value: number or preset name depending on the setting")
    p_trig.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4],
                         help="Target profile 1-4 (default 1) -- confirmed genuinely profile-scoped, "
                              "same as Buttons.")
    _add_heartbeat_args(p_trig)

    p_vib = sub.add_parser("vibration-set", help="Set a Vibrations-tab setting (device must already be in vendor mode).")
    p_vib.add_argument("setting", choices=sorted(vibration.SETTINGS))
    p_vib.add_argument("value", help="0-100 for levels, on/off for force/sync flags")
    p_vib.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4], help="Target profile 1-4 (default 1)")
    _add_heartbeat_args(p_vib)

    p_rate = sub.add_parser("report-rate-set", help="Set the report/polling rate (device must already be in vendor mode).")
    p_rate.add_argument("hz", type=int, choices=[250, 500, 1000])
    p_rate.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4], help="Target profile 1-4 (default 1)")
    _add_heartbeat_args(p_rate)

    p_dpad = sub.add_parser("dpad-set", help="Set a D-Pad option (device must already be in vendor mode).")
    p_dpad.add_argument("setting", choices=sorted(dpad_options.SETTINGS))
    p_dpad.add_argument("value", choices=["on", "off"])
    p_dpad.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4], help="Target profile 1-4 (default 1)")
    _add_heartbeat_args(p_dpad)

    p_dock = sub.add_parser("dock-set", help="Set a Dock setting (global, not per-profile; device must already be in vendor mode).")
    p_dock.add_argument("setting", choices=sorted(dock_settings.SETTINGS))
    p_dock.add_argument("value", help="0-100 for brightness, on/off for auto_on_off")
    _add_heartbeat_args(p_dock)

    p_raw = sub.add_parser(
        "raw",
        help="Send an unvalidated raw command byte + hex payload -- the protocol-poking escape "
             "hatch, no safety checks at all (device must be in vendor mode).")
    p_raw.add_argument("cmd", help="Command byte in hex, e.g. 3c")
    p_raw.add_argument("payload", help="Payload as hex bytes, e.g. 0305007b013e -- sent exactly as "
                        "given, with none of the range/format checks every other setting command has")

    sub.add_parser("list", help="List known button/keycode names.")

    p_new = sub.add_parser("new-state", help="Write a fresh default state JSON file to edit by hand.")
    p_new.add_argument("path", help="Output path, e.g. mystate.json")
    p_new.add_argument("--name", default="New State")

    p_write = sub.add_parser("write-state", help="Push an entire state JSON file to the device in one session (device must already be in vendor mode).")
    p_write.add_argument("path", help="State JSON file to write")
    p_write.add_argument("--interval", type=float, default=state_mod.WRITE_HEARTBEAT_INTERVAL,
                          help=f"Seconds between heartbeats (default {state_mod.WRITE_HEARTBEAT_INTERVAL})")

    p_read = sub.add_parser("read-state", help="Read a profile's current button bindings back from the device (device must already be in vendor mode).")
    p_read.add_argument("--profile", type=int, default=1, choices=[1, 2, 3, 4], help="Profile slot to read (default 1)")
    p_read.add_argument("--save", metavar="PATH", help="Also save the result as a state JSON file")

    p_batch = sub.add_parser(
        "batch",
        help="Run multiple commands in one continuous session (script file, stdin, or an interactive prompt).")
    p_batch.add_argument(
        "path", nargs="?",
        help="Script file, one command per line (same syntax as this CLI, minus 'g7ctl'); "
             "'#' starts a comment. Omit (or pass '-') to read from stdin, or for an interactive "
             "prompt if stdin is a terminal. 'batch' and 'enter-vendor' aren't valid inside it -- "
             "the session's already open, and per-line --pre-heartbeats/--post-heartbeats are "
             "ignored, since the batch loop's own continuous heartbeat already keeps it alive.")
    p_batch.add_argument("--dry-run", action="store_true",
                          help="Validate every line's syntax without opening a device session at all")
    p_batch.add_argument("--continue-on-error", action="store_true",
                          help="Skip a bad line and keep going instead of stopping the batch "
                               "(default: stop on the first bad line). A real USB disconnect always "
                               "stops the batch either way.")
    p_batch.add_argument("--interval", type=float, default=BATCH_HEARTBEAT_INTERVAL,
                          help=f"Seconds between the batch loop's own heartbeats (default {BATCH_HEARTBEAT_INTERVAL})")

    return ap


def _explain_usb_error(exc: usb.core.USBError) -> str:
    """Turn a raw pyusb errno into something a user can act on.

    Without this the common cases surface as a dozen frames of libusb
    traceback: errno 16 whenever the GUI/tray app is running (it holds a
    long-lived claim on interface 0), and errno 13 whenever the udev rule
    hasn't been installed yet.
    """
    errno = getattr(exc, "errno", None)
    if errno == 16:  # EBUSY
        return ("Device is busy -- another process already has it claimed.\n"
                "The GUI/tray app holds the interface whenever it's connected: "
                "click 'Release Device' there (or quit it) and retry.")
    if errno == 13:  # EACCES
        return ("Permission denied opening the device.\n"
                "Either run with sudo, or install the udev rule once for "
                "passwordless access -- see README.md 'Running without root'.")
    if errno == 19:  # ENODEV
        return ("Device disappeared mid-operation.\n"
                "It most likely reverted to XInput mode: heartbeats have to keep "
                "flowing or the firmware drops back on its own. Re-run "
                "'enter-vendor' and retry.")
    return f"USB error: {exc}"


# --- On-device command handlers -------------------------------------------
#
# Split by what each group actually does to the device rather than run as one
# long if/elif ladder: the single-setting writes all share the heartbeat
# wrapper, while state read/write drive whole-config operations with their own
# pacing. `raw` sits on its own deliberately -- it's the protocol-poking
# escape hatch and gets no wrapping or validation at all.


def _dispatch(sess: VendorSession, args: argparse.Namespace) -> None:
    for handler in (_handle_setting_write, _handle_state_command, _handle_raw):
        if handler(sess, args):
            return
    raise SystemExit(f"unhandled action {args.action!r}")


def _handle_setting_write(sess: VendorSession, args: argparse.Namespace) -> bool:
    """One setting, one wrapped write. Returns True if it handled `args`."""
    writes = {
        "remap": lambda s: buttons.remap(
            s, buttons.resolve_button_id(args.button), buttons.resolve_keycode(args.keycode),
            profile=args.profile, shift=args.shift),
        "unbind": lambda s: buttons.unbind(
            s, buttons.resolve_button_id(args.button), profile=args.profile, shift=args.shift),
        "stick-set": lambda s: sticks.set_value(
            s, args.side, args.setting, args.value, profile=args.profile),
        "trigger-set": lambda s: triggers.set_value(
            s, args.side, args.setting, args.value, profile=args.profile),
        "vibration-set": lambda s: vibration.set_value(
            s, args.setting, args.value, profile=args.profile),
        "report-rate-set": lambda s: report_rate.set_value(s, args.hz, profile=args.profile),
        "dpad-set": lambda s: dpad_options.set_value(
            s, args.setting, args.value, profile=args.profile),
        # Dock settings take no profile= -- they're genuinely global, see
        # dock_settings.py.
        "dock-set": lambda s: dock_settings.set_value(s, args.setting, args.value),
    }
    write_fn = writes.get(args.action)
    if write_fn is None:
        return False
    _wrapped_write(sess, args, write_fn)
    return True


def _handle_state_command(sess: VendorSession, args: argparse.Namespace) -> bool:
    """Whole-config read/write. Returns True if it handled `args`."""
    if args.action == "write-state":
        state = state_mod.load_state(args.path)
        state_mod.write_state(
            sess, state,
            on_progress=lambda i, total, label: print(f"  [{i}/{total}] {label}"),
            interval=args.interval,
        )
        print("State applied.")
        print(f"  Targeted Profile {state.get('controller_slot') or 1} "
              "(every category is profile-scoped).")
        return True

    if args.action == "read-state":
        state = state_mod.read_state(sess, slot=args.profile)
        _print_state(state, args.profile)
        if args.save:
            state_mod.save_state(args.save, state)
            print(f"Saved to {args.save}")
        return True

    return False


def _handle_raw(sess: VendorSession, args: argparse.Namespace) -> bool:
    if args.action != "raw":
        return False
    pkt = sess.send_raw(int(args.cmd, 16), bytes.fromhex(args.payload))
    print(f"  sent: {pkt.hex()}")
    return True


def _print_state(state: dict, slot: int) -> None:
    """Print everything read_state() actually decodes.

    This used to print only the two button layers, which quietly implied the
    read was buttons-only -- it hasn't been since Sticks/Triggers/Vibration
    coverage landed, and a `read-state` that hides two thirds of what it just
    fetched makes write->read->compare testing harder than it needs to be.
    """
    for layer in ("default", "shift"):
        print(f"Profile {slot} -- {layer.capitalize()} layer:")
        for btn, kc in state["buttons"][layer].items():
            print(f"  {btn:8s} {kc}")

    print(f"Profile {slot} -- per-profile settings:")
    print(f"  report rate       {state['report_rate_hz']} Hz")
    print(f"  dpad diagonal lock {state['dpad_diagonal_lock']}")
    print(f"  swap stick/dpad    {state['swap_stick_dpad']}")
    for side in ("left", "right"):
        s = state["sticks"][side]
        am = s["advanced_mapping"]
        print(f"  {side} stick: trajectory={s['trajectory']} curve={s['curve']['preset']} "
              f"deadzone={s['deadzone']['initial']}-{s['deadzone']['max']} "
              f"anti={s['anti_deadzone']['initial']}-{s['anti_deadzone']['max']} "
              f"bits={s['resolution_bits']} mode={am['output_mode']} "
              f"invert=({am['invert_x']},{am['invert_y']})")
    for side in ("left", "right"):
        t = state["triggers"][side]
        print(f"  {side} trigger: hair={t['hair_trigger_mode']} curve={t['curve']['preset']} "
              f"deadzone={t['deadzone']['initial']}-{t['deadzone']['max']} "
              f"anti={t['anti_deadzone']['initial']}-{t['anti_deadzone']['max']}")
    v = state["vibration"]
    print(f"  vibration: grips={v['left_grip']}/{v['right_grip']} "
          f"triggers={v['left_trigger']}/{v['right_trigger']}")

    # Dock settings are device-wide, so they're deliberately printed outside
    # the "Profile N" grouping above -- they'd read as per-profile otherwise.
    print("Device-wide (not per-profile):")
    print(f"  dock LED brightness {state['dock_led_brightness']}%")
    print(f"  dock auto on/off    {state['dock_auto_on_off']}")


def _print_list() -> None:
    print("Known button IDs:")
    for k, v in buttons.KNOWN_BUTTON_IDS.items():
        print(f"  {k:10s} {v.hex()}")
    print("Known keycodes:")
    for k, v in buttons.KNOWN_KEYCODES.items():
        print(f"  {k:10s} {v:02x}")


@contextlib.contextmanager
def _connect_session():
    """Find/handshake the controller and yield a settled, liveness-checked
    VendorSession -- the connect logic every device-touching action needs,
    factored out of a single inline block in main() so batch mode (roadmap
    item 20) can open exactly one session for many commands instead of
    duplicating this per invocation."""
    vdev, via_dongle = find_writable_device()
    if vdev is None:
        # Fall back to doing the handshake ourselves rather than telling
        # the user to run 'enter-vendor' as a separate command first. That
        # two-step flow barely works in practice: once 'enter-vendor'
        # exits, nothing is heartbeating, and the firmware reverts to
        # XInput within seconds -- usually before the follow-up command can
        # claim it. The GUI's watcher has always auto-entered for exactly
        # this reason (watcher._connect); this brings the CLI in line.
        print("Device not in vendor mode -- entering it now...")
        # The handshake reports which identity it landed on: wired
        # (PID_VENDOR) or dongle (PID_DONGLE). Both are reachable this way --
        # an idle dongle sits in XInput mode like the wired controller does.
        vdev, via_dongle = enter_vendor_mode()
        if vdev is None:
            print("Could not reach the controller. Plug it in (or connect the "
                  "wireless dongle) and try again.", file=sys.stderr)
            sys.exit(1)
    elif via_dongle:
        print("Using wireless dongle -- already in vendor mode, no handshake needed.")

    with VendorSession(vdev, via_dongle=via_dongle) as sess:
        # A just-claimed session accepts heartbeats but isn't ready to
        # service CMD_READ yet -- see VendorSession.settle().
        sess.settle()
        # The dongle enumerates on USB (and claims, and heartbeats fine)
        # whether or not a physical controller is actually powered on and
        # paired to it -- they're two separate things joined by an RF
        # link. Only a real read proves a controller answered; wired mode
        # doesn't need this check, since PID_VENDOR is the controller's
        # own USB descriptor. See VendorSession.probe_controller_live().
        if via_dongle and not sess.probe_controller_live():
            print("Dongle detected, but no controller answered. Make sure "
                  "it's powered on and paired (or hold Menu+Share on the "
                  "controller if it may have switched identity).", file=sys.stderr)
            sys.exit(1)
        yield sess


# --- Batch/REPL mode --------------------------------------------------------
#
# One continuous session instead of one handshake per command. A line is
# just this CLI's own subcommand syntax minus the program name, reparsed
# per line against a _NonExitingArgumentParser built from the same
# build_parser() every other action uses -- no separate grammar to maintain.


def _dispatch_batch_args(sess: VendorSession, args: argparse.Namespace) -> None:
    """Dispatch one already-parsed batch/REPL line.

    Forces pre/post-heartbeats to 0 regardless of what was parsed -- those
    exist in _wrapped_write() only to pad a standalone session that's about
    to close; inside batch/REPL mode the surrounding loop already keeps the
    session continuously alive, so the padding is pure overhead here."""
    if hasattr(args, "pre_heartbeats"):
        args.pre_heartbeats = 0
    if hasattr(args, "post_heartbeats"):
        args.post_heartbeats = 0
    _dispatch(sess, args)


def _run_batch_line(sess: VendorSession, args: argparse.Namespace) -> None:
    """Handles the 3 batch/REPL actions _dispatch() doesn't know about
    (list/new-state need no session at all; batch/enter-vendor make no
    sense once a session is already open) before falling through to the
    normal device-touching dispatch."""
    if args.action in BATCH_NOT_ALLOWED:
        raise _BatchLineError(f"'{args.action}' isn't valid inside a batch session")
    if args.action == "list":
        _print_list()
        return
    if args.action == "new-state":
        state_mod.save_state(args.path, state_mod.default_state_dict(args.name))
        print(f"Wrote a new default state to {args.path}")
        return
    _dispatch_batch_args(sess, args)


def _read_lines(path: Optional[str]) -> list[str]:
    if path in (None, "-"):
        return sys.stdin.readlines()
    with open(path) as fh:
        return fh.readlines()


def _run_batch_lines(sess: VendorSession, lines: Iterable[str], *, line_parser: argparse.ArgumentParser,
                      continue_on_error: bool, interval: float) -> bool:
    """Runs a fixed sequence of lines (script file or stdin). Returns True
    if every line succeeded."""
    total = ok = 0
    for lineno, raw in enumerate(lines, 1):
        tokens = shlex.split(raw, comments=True)
        if not tokens:
            continue
        total += 1
        sess.heartbeat()
        time.sleep(interval)
        try:
            args = line_parser.parse_args(tokens)
            _run_batch_line(sess, args)
            ok += 1
        except (_BatchLineError, ValueError, OSError) as exc:
            print(f"line {lineno}: error: {exc}", file=sys.stderr)
            if not continue_on_error:
                break
        # usb.core.USBError is deliberately NOT caught here -- it propagates
        # to main()'s top-level handler and aborts the whole batch, same as
        # every other action. A real disconnect can't be "skipped past".
    sess.heartbeat()
    failed = total - ok
    print(f"batch: {ok}/{total} succeeded" + (f", {failed} failed" if failed else ""))
    return failed == 0


def _run_batch_repl(sess: VendorSession, line_parser: argparse.ArgumentParser, interval: float) -> None:
    try:
        import readline  # noqa: F401 -- import side effect only: arrow-key history in input()
    except ImportError:
        pass  # not fatal, just no history -- e.g. not available on all platforms

    print("Interactive batch mode -- one continuous session, no per-command handshake.")
    print("Type a command (e.g. 'remap a f12'), 'help' to list subcommands, "
          "'exit' or Ctrl-D to quit.\n")
    while True:
        try:
            raw = input("g7ctl> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        tokens = shlex.split(raw, comments=True)
        if not tokens:
            continue
        if tokens[0] in ("exit", "quit"):
            return
        if tokens[0] in ("help", "-h", "--help"):
            line_parser.print_help()
            continue
        sess.heartbeat()
        try:
            args = line_parser.parse_args(tokens)
            _run_batch_line(sess, args)
        except (_BatchLineError, ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
        # A real USBError here still propagates up through main()'s
        # top-level handler and ends the REPL -- the session is gone either
        # way, so there's nothing left to keep prompting against.
        sess.heartbeat()
        time.sleep(interval)


def _handle_batch(args: argparse.Namespace) -> None:
    line_parser = build_parser(parser_class=_NonExitingArgumentParser)

    if args.dry_run:
        # Syntax-only: catches a bad subcommand/argument before a session is
        # even opened. Doesn't catch semantic errors (e.g. an unknown
        # keycode name) -- those only surface when a line's write() is
        # actually built, which dry-run deliberately never does.
        lines = _read_lines(args.path)
        total = ok = 0
        for lineno, raw in enumerate(lines, 1):
            tokens = shlex.split(raw, comments=True)
            if not tokens:
                continue
            total += 1
            try:
                a = line_parser.parse_args(tokens)
                if a.action in BATCH_NOT_ALLOWED:
                    raise _BatchLineError(f"'{a.action}' isn't valid inside a batch session")
                ok += 1
            except _BatchLineError as exc:
                print(f"line {lineno}: error: {exc}", file=sys.stderr)
        failed = total - ok
        print(f"dry-run: {ok}/{total} line(s) OK" + (f", {failed} failed" if failed else ""))
        if failed:
            sys.exit(1)
        return

    interactive = args.path is None and sys.stdin.isatty()
    with _connect_session() as sess:
        if interactive:
            _run_batch_repl(sess, line_parser, args.interval)
        else:
            lines = _read_lines(args.path)
            success = _run_batch_lines(sess, lines, line_parser=line_parser,
                                        continue_on_error=args.continue_on_error, interval=args.interval)
            if not success:
                sys.exit(1)


def main() -> None:
    args = build_parser().parse_args()

    # Message-only format: library progress from pyg7.* is routed
    # through logging, and on a CLI it should look exactly like the plain
    # print()s it replaced -- no level prefixes or timestamps.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.action == "list":
        _print_list()
        return

    if args.action == "new-state":
        state_mod.save_state(args.path, state_mod.default_state_dict(args.name))
        print(f"Wrote a new default state to {args.path}")
        return

    # Checked before the device is touched: profile_layer_byte() rejects this
    # too, but only once a session is open, so the user waits through a
    # handshake and settle to be told something knowable from the arguments
    # alone. See pyg7/session.py for why these profiles have no Shift layer.
    if getattr(args, "shift", False) and not shift_layer_supported(getattr(args, "profile", 1)):
        print(f"Error: profile {args.profile} has no Shift layer -- the controller stores "
              f"Shift-layer bindings for profile(s) "
              f"{', '.join(str(p) for p in SHIFT_LAYER_PROFILES)} only.", file=sys.stderr)
        sys.exit(1)

    # Everything below touches the device, directly or via _dispatch() (which
    # can also load/validate a state JSON file or parse a raw hex payload) --
    # one try/except covers all of it. Previously this only wrapped the
    # VendorSession block, so a USBError from enter_vendor_mode() (called
    # just below, and again as the auto-handshake fallback) surfaced as a
    # raw libusb traceback instead of _explain_usb_error()'s message -- on
    # the single most likely first-run failure (device busy/permission
    # denied) for a new user of this tool.
    try:
        if args.action == "enter-vendor":
            enter_vendor_mode()
            return

        if args.action == "batch":
            _handle_batch(args)
            return

        with _connect_session() as sess:
            _dispatch(sess, args)
    except usb.core.USBError as exc:
        print(_explain_usb_error(exc), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as exc:
        # Covers a bad/missing write-state JSON path (OSError), malformed
        # JSON or a failed validate_state() (json.JSONDecodeError and
        # state_mod.StateError are both ValueError subclasses), and a
        # malformed remap/stick-set/etc. argument (buttons.resolve_keycode()
        # and values.percent()/boolean() raise plain ValueError) -- none of
        # these were caught before, so each surfaced as a raw Python
        # traceback rather than a clean, actionable message.
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
