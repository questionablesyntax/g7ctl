"""State schema: a full declared controller configuration as JSON,
write_state() to push one to the device in a single continuous session,
and read_state() to read a profile slot's current button bindings back.

Design (see the project's approved GUI build plan): the state dict is the
source of truth for applying. "Sync" (write_state) always means writing
the entire declared state, never an incremental read-modify-write.

read_state() exists alongside this for a different purpose -- inspecting
real device state (e.g. detecting drift from the onboard on-the-fly remap
shortcuts, or scripting write->read->compare tests) -- not for a
read-modify-write workflow. It decodes Buttons (both layers) plus Sticks/
Triggers/Vibration (Default layer's blob only -- those categories aren't
layer-scoped, there's no Shift-layer variant of a deadzone or a vibration
level) -- see PROTOCOL.md "Reading current config" for the wire format and
"Sticks/Triggers/Vibration storage offsets" for where each value lives
(offsets confirmed 2026-07-27 via live write+read-diff on every setting).

Every category targets `controller_slot` explicitly and deterministically,
independent of whichever profile is physically active on the controller:
Buttons via the PROFILE+LAYER byte, Sticks/Triggers/Vibration/report rate
via a plain profile number in their own prefix's middle byte (confirmed
2026-07-28 -- see PROTOCOL.md "Profile scoping"; an earlier single test
had wrongly suggested the latter categories carried no profile targeting
at all and just landed wherever was physically active, which didn't hold
up under closer testing). Dock settings (LED Brightness, Auto On/Off) are
the one exception -- genuinely global/device-wide, not profile-scoped at
all, and stored in a completely separate blob from the 4 per-profile ones
(see `dock_settings.py`).
"""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from . import buttons, dock_settings, dpad_options, report_rate, sticks, triggers, vibration
from .constants import DOCK_READ_CATEGORY, FULL_BLOB_LENGTH
from .curves import CURVE_PRESETS as _CURVE_PRESETS
from .session import SHIFT_LAYER_PROFILES, VendorSession, profile_layer_byte, shift_layer_supported

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_HAIR_TRIGGER_MODES = set(triggers.HAIR_TRIGGER_MODES)
_OUTPUT_MODES = set(sticks.OUTPUT_MODES)

# Default heartbeat pacing used while applying a state dict, matching the
# observed app cadence (see g7ctl/main.py's _wrapped_write).
WRITE_HEARTBEAT_INTERVAL = 0.316
WRITE_PRE_HEARTBEATS = 3
WRITE_POST_HEARTBEATS = 3


# ---------------------------------------------------------------------------
# Defaults
#
# The shape every other function in this module agrees on. Anything added
# here must also be handled by validate_state() below and by one of the
# *_steps() builders at the bottom, or it will round-trip through JSON and
# then quietly never reach the device.
# ---------------------------------------------------------------------------


def _default_stick_settings() -> dict:
    return {
        "trajectory": "circle",
        "curve": {"preset": "standard"},
        "deadzone": {"initial": 0, "max": 100},
        "anti_deadzone": {"initial": 0, "max": 100},
        "resolution_bits": 12,
        "advanced_mapping": {
            "output_mode": "left_stick",
            "invert_x": False,
            "invert_y": False,
            "sensitivity": 50,
            "overlap_area": 50,
            "direction_bindings": None,
            "dpi": 50,
        },
    }


def _default_trigger_settings() -> dict:
    return {
        "hair_trigger_mode": "off",
        "deadzone": {"initial": 0, "max": 100},
        "anti_deadzone": {"initial": 0, "max": 100},
        "curve": {"preset": "standard"},
    }


def default_state_dict(name: str = "New State") -> dict:
    """A brand-new state dict with sensible defaults, ready to hand-edit or feed to a GUI."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "id": str(uuid.uuid4()),
        "name": name,
        "created_at": now,
        "updated_at": now,
        "controller_slot": None,
        "buttons": {"default": {}, "shift": {}},
        "report_rate_hz": 1000,
        "dpad_diagonal_lock": False,
        "swap_stick_dpad": False,
        "dock_led_brightness": 100,
        "dock_auto_on_off": True,
        "sticks": {"left": _default_stick_settings(), "right": _default_stick_settings()},
        "triggers": {"left": _default_trigger_settings(), "right": _default_trigger_settings()},
        "vibration": {
            "left_grip": 50, "right_grip": 50,
            "left_trigger": 50, "right_trigger": 50,
            "left_trigger_force": False, "left_trigger_sync": False,
            "right_trigger_force": False, "right_trigger_sync": False,
        },
    }


# ---------------------------------------------------------------------------
# Validation
#
# The only thing between a hand-edited or imported JSON file and a write to
# persistent device config. Deliberately strict about names and ranges --
# an unknown keycode name here is far cheaper than an unintended byte on the
# wire -- and deliberately shallow about nested structure, leaving genuine
# JSON-shape mistakes to surface as KeyError/TypeError during write_state().
# ---------------------------------------------------------------------------


class StateError(ValueError):
    """Raised by validate_state() / load_state() on a malformed state dict."""


def validate_state(data: dict) -> None:
    """Raises StateError with a clear message on the first problem found.
    Not exhaustive on deeply-nested structure (trusts JSON-shape mistakes to
    surface as KeyError/TypeError during write_state instead), but catches
    the mistakes most likely from hand-editing or a GUI bug: unknown names,
    out-of-range values, wrong top-level shape.
    """
    if not isinstance(data, dict):
        raise StateError("state must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise StateError(f"unsupported schema_version {data.get('schema_version')!r}, expected {SCHEMA_VERSION}")
    for key in ("buttons", "sticks", "triggers", "vibration"):
        if key not in data:
            raise StateError(f"missing top-level section {key!r}")

    slot = data.get("controller_slot")
    if slot is not None and slot not in (1, 2, 3, 4):
        raise StateError(f"controller_slot must be 1-4 or null, got {slot!r}")

    # report_rate_hz is optional (added after schema_version 1 already shipped,
    # not bumped since it's additive -- older state JSON files without this key
    # still validate fine, see default_state_dict()).
    rate = data.get("report_rate_hz")
    if rate is not None and rate not in report_rate.RATES_HZ:
        raise StateError(f"report_rate_hz must be one of {sorted(report_rate.RATES_HZ)} or null, got {rate!r}")

    # dpad_diagonal_lock/swap_stick_dpad: same additive-field reasoning as
    # report_rate_hz above -- only type-checked here, not required.
    diag = data.get("dpad_diagonal_lock")
    if diag is not None and not isinstance(diag, bool):
        raise StateError(f"dpad_diagonal_lock must be a bool or null, got {diag!r}")
    swap = data.get("swap_stick_dpad")
    if swap is not None and not isinstance(swap, bool):
        raise StateError(f"swap_stick_dpad must be a bool or null, got {swap!r}")

    # Dock settings: same additive-field reasoning, and genuinely global/
    # device-wide (see dock_settings.py) -- not tied to controller_slot.
    brightness = data.get("dock_led_brightness")
    if brightness is not None and not (isinstance(brightness, int) and 0 <= brightness <= 100):
        raise StateError(f"dock_led_brightness must be 0-100 or null, got {brightness!r}")
    auto = data.get("dock_auto_on_off")
    if auto is not None and not isinstance(auto, bool):
        raise StateError(f"dock_auto_on_off must be a bool or null, got {auto!r}")

    slot = data.get("controller_slot") or 1
    for layer_name, bindings in data["buttons"].items():
        if layer_name not in ("default", "shift"):
            raise StateError(f"unknown button layer {layer_name!r}, expected 'default' or 'shift'")
        # Refuse Shift bindings for a profile with no Shift storage, here
        # rather than at write time: writing one corrupts Profile 1's
        # Default layer (see session.profile_layer_byte()), and failing
        # mid-sync would leave the earlier steps already applied. A state
        # read back by a version before this check carries Profile 1's
        # Default bindings mislabelled as this profile's Shift layer, so
        # refusing is also refusing to write back bogus data.
        if layer_name == "shift" and bindings and not shift_layer_supported(slot):
            raise StateError(
                f"profile {slot} declares {len(bindings)} Shift-layer binding(s), but the "
                f"controller has no Shift layer for it -- only profile(s) "
                f"{', '.join(str(p) for p in SHIFT_LAYER_PROFILES)}. Writing them would "
                "overwrite Profile 1's Default layer. Clear the shift layer for this profile, "
                "or re-read the profile from the device to get a correct state.")
        for btn, keycode_name in bindings.items():
            if btn.lower() not in buttons.KNOWN_BUTTON_IDS:
                raise StateError(f"unknown button {btn!r}")
            if keycode_name is not None and not _is_valid_keycode_value(keycode_name):
                raise StateError(f"unknown keycode {keycode_name!r} for button {btn!r}")

    for side_name, side_data in data["sticks"].items():
        if side_name not in ("left", "right"):
            raise StateError(f"unknown stick side {side_name!r}")
        _validate_stick_settings(side_data)

    for side_name, side_data in data["triggers"].items():
        if side_name not in ("left", "right"):
            raise StateError(f"unknown trigger side {side_name!r}")
        _validate_trigger_settings(side_data)

    _validate_percent(data["vibration"].get("left_grip"), "vibration.left_grip")
    _validate_percent(data["vibration"].get("right_grip"), "vibration.right_grip")
    _validate_percent(data["vibration"].get("left_trigger"), "vibration.left_trigger")
    _validate_percent(data["vibration"].get("right_trigger"), "vibration.right_trigger")


def _is_valid_keycode_value(s: str) -> bool:
    """Matches what buttons.resolve_keycode() actually accepts: a known
    name, or a raw hex string (e.g. decode_button_table()'s fallback for a
    keycode not in KNOWN_KEYCODES' still-incomplete coverage -- see
    PROTOCOL.md "Keycodes" for the full table, including which entries are
    hardware-confirmed versus predicted).

    Range-checked against 0-255 (a keycode is one wire byte) -- without this,
    a value like "1ff" passed validation cleanly and then crashed
    write_state()/remap() with an opaque bytes-range error far from here."""
    if s.lower() in buttons.KNOWN_KEYCODES:
        return True
    try:
        return 0 <= int(s, 16) <= 255
    except ValueError:
        return False


def _validate_percent(v: object, label: str) -> None:
    if v is None:
        return
    if not isinstance(v, int) or not 0 <= v <= 100:
        raise StateError(f"{label} must be 0-100, got {v!r}")


def _validate_stick_settings(s: dict) -> None:
    if s.get("trajectory") not in (None, "circle", "raw"):
        raise StateError(f"stick trajectory must be 'circle' or 'raw', got {s.get('trajectory')!r}")
    curve = s.get("curve") or {}
    if curve.get("preset") is not None and curve["preset"] not in _CURVE_PRESETS:
        raise StateError(f"unknown curve preset {curve.get('preset')!r}")
    for field_name in ("deadzone", "anti_deadzone"):
        block = s.get(field_name) or {}
        _validate_percent(block.get("initial"), f"{field_name}.initial")
        _validate_percent(block.get("max"), f"{field_name}.max")
    bits = s.get("resolution_bits")
    if bits is not None and not 8 <= bits <= 12:
        raise StateError(f"resolution_bits must be 8-12, got {bits!r}")
    am = s.get("advanced_mapping") or {}
    if am.get("output_mode") is not None and am["output_mode"] not in _OUTPUT_MODES:
        raise StateError(f"unknown output_mode {am.get('output_mode')!r}")
    _validate_percent(am.get("sensitivity"), "advanced_mapping.sensitivity")
    _validate_percent(am.get("overlap_area"), "advanced_mapping.overlap_area")
    _validate_percent(am.get("dpi"), "advanced_mapping.dpi")
    db = am.get("direction_bindings")
    if db is not None:
        for zone in ("up", "down", "left", "right", "ring"):
            if zone not in db:
                raise StateError(f"direction_bindings missing zone {zone!r}")
            if db[zone] is not None and not _is_valid_keycode_value(db[zone]):
                raise StateError(f"unknown keycode {db[zone]!r} for direction_bindings.{zone}")


def _validate_trigger_settings(s: dict) -> None:
    if s.get("hair_trigger_mode") is not None and s["hair_trigger_mode"] not in _HAIR_TRIGGER_MODES:
        raise StateError(f"unknown hair_trigger_mode {s.get('hair_trigger_mode')!r}")
    curve = s.get("curve") or {}
    if curve.get("preset") is not None and curve["preset"] not in _CURVE_PRESETS:
        raise StateError(f"unknown curve preset {curve.get('preset')!r}")
    for field_name in ("deadzone", "anti_deadzone"):
        block = s.get(field_name) or {}
        _validate_percent(block.get("initial"), f"{field_name}.initial")
        _validate_percent(block.get("max"), f"{field_name}.max")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def load_state(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    validate_state(data)
    return data


def save_state(path: str, data: dict) -> None:
    validate_state(data)
    data = dict(data)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Reading device state
# ---------------------------------------------------------------------------


def read_state(session: VendorSession, slot: int = 1, interval: float = 0.05,
                pre_heartbeats: int = WRITE_PRE_HEARTBEATS, include_dock: bool = True) -> dict:
    """Read Profile `slot`'s current bindings/settings directly from the
    device -- see PROTOCOL.md "Reading current config". Buttons come from
    both Default and Shift layers; Sticks/Triggers/Vibration/report rate
    come from the Default layer's blob only (not layer-scoped -- see this
    module's docstring). The result validates and is safe to hand to
    write_state(). Report rate is nested at the top level (not per-side)
    because it's genuinely per-profile, not per-side -- confirmed both by
    the real GameSir Nexus app's own UI and, since 2026-07-28, by direct
    wire-level testing (see PROTOCOL.md "Profile scoping").

    `include_dock`: dock settings (LED Brightness, Auto On/Off) are
    genuinely device-global, not tied to `slot` at all (see
    dock_settings.py) -- nothing about them can change just because a
    different profile was selected, or because this function was called
    again against the same live connection. Pass `include_dock=False` to
    skip that extra ~10-chunk read and get `dock_led_brightness`/
    `dock_auto_on_off` back as `None` ("not read this time", same "not
    declared" meaning validate_state()/write_state() already give a `None`
    dock field) -- for a caller that already has a known-good dock reading
    from earlier in the same connection and doesn't want to pay for a
    provably-unchanged re-read on every profile switch. Defaults to `True`
    (the original, always-read-it
    behavior) so every other caller, including the CLI's standalone
    `read-state`, is unaffected.

    NOTE on scope: this reads ONE profile per call. The `category` byte
    addresses five profile blobs, not eight: Profiles 1-4's Default layers
    (0x01-0x04) plus Profile 1's Shift layer (0x05). Profiles 2-4 have no
    Shift layer -- see session.py's profile_layer_byte() -- so their
    "shift" section comes back empty. All 4 stored profiles ARE readable
    this same way, just one call per profile; this function doesn't loop
    over all of them itself.

    Sends a few heartbeats before the first read, same reasoning as
    WRITE_PRE_HEARTBEATS for writes: a session with no recent heartbeat
    activity appears to get dropped (the device reverts out of vendor
    mode) before a bare first request gets a chance to land -- confirmed
    the hard way (an immediate first read_chunk() with zero prior
    heartbeats hit a mid-request USBError as the device reverted)."""
    if not 1 <= slot <= 4:
        raise ValueError("slot must be 1-4")
    for _ in range(pre_heartbeats):
        session.heartbeat()
        time.sleep(WRITE_HEARTBEAT_INTERVAL)

    # One full-blob read of the Default layer serves Buttons' default layer
    # AND Sticks/Triggers/Vibration (all decoded from the same 480 bytes);
    # the Shift layer only has Buttons, read separately via the narrower,
    # already-proven read_button_bindings() path (unchanged, to avoid any
    # risk of regressing it).
    default_category = profile_layer_byte(slot, shift=False)
    default_blob = session.read_blob(default_category, FULL_BLOB_LENGTH, interval=interval)

    # Dock settings live in a completely separate, non-profile-scoped blob
    # (category 0x20, not profile_layer_byte()) -- see dock_settings.py.
    if include_dock:
        dock_blob = session.read_blob(DOCK_READ_CATEGORY, dock_settings.BLOB_LENGTH, interval=interval)
        dock_decoded = dock_settings.decode_settings(dock_blob)
    else:
        dock_decoded = {"dock_led_brightness": None, "dock_auto_on_off": None}
    dpad_decoded = dpad_options.decode_settings(default_blob)

    now = datetime.now(timezone.utc).isoformat()
    state = {
        "schema_version": SCHEMA_VERSION,
        "id": str(uuid.uuid4()),
        "name": f"Read from device (Profile {slot})",
        "created_at": now,
        "updated_at": now,
        "controller_slot": slot,
        "buttons": {
            "default": buttons.decode_button_table(default_blob),
            # Only Profile 1 has a Shift layer the firmware can address. For
            # the others this used to read category 0x06/0x07/0x08, which the
            # device answers with Profile 1's Default-layer blob -- so the
            # GUI showed Profile 1's bindings labelled as Profile 3's Shift
            # layer. An empty dict is "this profile declares no Shift
            # bindings", which write_state() correctly treats as nothing to
            # write. See session.profile_layer_byte().
            "shift": (buttons.read_button_bindings(session, profile=slot, shift=True, interval=interval)
                      if shift_layer_supported(slot) else {}),
        },
        "report_rate_hz": report_rate.decode_settings(default_blob)["report_rate_hz"],
        # Both D-pad options come out of a single decode -- calling it once
        # per key re-parsed the same blob twice for no reason.
        "dpad_diagonal_lock": dpad_decoded["dpad_diagonal_lock"],
        "swap_stick_dpad": dpad_decoded["swap_stick_dpad"],
        "dock_led_brightness": dock_decoded["dock_led_brightness"],
        "dock_auto_on_off": dock_decoded["dock_auto_on_off"],
        "sticks": {
            "left": sticks.decode_settings(default_blob, "left"),
            "right": sticks.decode_settings(default_blob, "right"),
        },
        "triggers": {
            "left": triggers.decode_settings(default_blob, "left"),
            "right": triggers.decode_settings(default_blob, "right"),
        },
        "vibration": vibration.decode_settings(default_blob),
    }
    validate_state(state)
    return state


# ---------------------------------------------------------------------------
# Writing device state
#
# write_state() handles pacing (the firmware drops writes that aren't
# surrounded by heartbeats); _build_steps() and the per-category *_steps()
# helpers below decide WHAT to write. Keeping the two apart is what makes
# the diff logic testable without a controller attached.
# ---------------------------------------------------------------------------


ProgressCallback = Optional[Callable[[int, int, str], None]]
# One entry in the list _build_steps()/the *_steps() helpers return: a
# human-readable label paired with the write itself, deferred as a closure
# so write_state() can pace it with heartbeats before actually calling it.
Step = tuple[str, Callable[[VendorSession], bytes]]


def write_state(
    session: VendorSession,
    state: dict,
    on_progress: ProgressCallback = None,
    interval: float = WRITE_HEARTBEAT_INTERVAL,
    baseline: Optional[dict] = None,
) -> int:
    """Push a declared state dict to the device in one continuous session.
    Sends heartbeats before/after/between writes throughout (a write with
    no heartbeat around it gets silently discarded -- see PROTOCOL.md
    "Packet framing"), so
    this can take a while for a fully-populated state; on_progress(step,
    total, label) is called before each individual write. Returns the
    number of writes skipped because `baseline` showed they already matched
    (always 0 if `baseline` is None).

    `baseline`, if given, is a state dict (typically fresh output from
    read_state()) to diff writes against -- a setting whose target value
    already matches `baseline` is skipped entirely, rather than rewriting
    values that already match live device state. Covers Buttons, Sticks,
    Triggers, and Vibration (read_state() decodes all of these as of
    2026-07-27 -- see PROTOCOL.md "Reading current config"), including
    Deadzone/Anti-deadzone as of 2026-07-28 (see _stick_steps()/
    _trigger_steps() and their live-suffix fix).
    Pass `baseline=None` (the default) for the original write-everything
    behavior.
    """
    validate_state(state)
    steps, skipped = _build_steps(state, baseline=baseline)
    total = len(steps)

    def _report(i, label):
        if on_progress:
            on_progress(i, total, label)

    for _ in range(WRITE_PRE_HEARTBEATS):
        session.heartbeat()
        time.sleep(interval)

    for i, (label, write_fn) in enumerate(steps, start=1):
        _report(i, label)
        write_fn(session)
        time.sleep(interval)
        session.heartbeat()
        time.sleep(interval)

    for _ in range(WRITE_POST_HEARTBEATS):
        time.sleep(interval)
        session.heartbeat()

    return skipped


def _build_steps(state: dict, baseline: Optional[dict] = None) -> tuple[list[Step], int]:
    """Returns (steps, skipped): a list of (label, fn(session)) pairs in
    application order, and a count of Buttons writes skipped via baseline
    diffing (always 0 if `baseline` is None)."""
    steps = []
    skipped = 0
    slot = state.get("controller_slot") or 1
    baseline_buttons = (baseline or {}).get("buttons", {})

    for layer_name in ("default", "shift"):
        shift = layer_name == "shift"
        baseline_layer = baseline_buttons.get(layer_name, {})
        for btn, keycode_name in state["buttons"].get(layer_name, {}).items():
            if baseline is not None and baseline_layer.get(btn) == keycode_name:
                skipped += 1
                continue  # already matches live device state -- see baseline diffing above
            btn_id = buttons.resolve_button_id(btn)
            if keycode_name is None:
                steps.append((f"Button {btn} ({layer_name}): unbind",
                              lambda s, b=btn_id, sh=shift: buttons.unbind(s, b, profile=slot, shift=sh)))
            else:
                kc = buttons.resolve_keycode(keycode_name)
                steps.append((f"Button {btn} ({layer_name}) -> {keycode_name}",
                              lambda s, b=btn_id, k=kc, sh=shift: buttons.remap(s, b, k, profile=slot, shift=sh)))

    button_step_count = len(steps)
    total_button_entries = sum(len(state["buttons"].get(layer, {})) for layer in ("default", "shift"))

    rate = state.get("report_rate_hz")
    baseline_rate = (baseline or {}).get("report_rate_hz")
    if rate is not None and baseline_rate != rate:
        steps.append((f"Report rate={rate}Hz",
                       lambda sess, v=rate: report_rate.set_value(sess, v, profile=slot)))
    elif rate is not None:
        skipped += 1

    diag = state.get("dpad_diagonal_lock")
    baseline_diag = (baseline or {}).get("dpad_diagonal_lock")
    if diag is not None and baseline_diag != diag:
        steps.append((f"D-Pad Diagonal Lock={diag}",
                       lambda sess, v=diag: dpad_options.set_value(sess, "diagonal_lock", v, profile=slot)))
    elif diag is not None:
        skipped += 1

    # Write-enabled 2026-07-28 -- set_swap_stick_dpad()
    # reads its collateral 53-byte span live rather than trusting a captured
    # constant, same reasoning as Sticks/Triggers deadzone (item 12).
    swap = state.get("swap_stick_dpad")
    baseline_swap = (baseline or {}).get("swap_stick_dpad")
    if swap is not None and baseline_swap != swap:
        steps.append((f"Swap Left Stick and D-pad={swap}",
                       lambda sess, v=swap: dpad_options.set_value(sess, "swap_stick_dpad", v, profile=slot)))
    elif swap is not None:
        skipped += 1

    # Dock settings are genuinely global (see dock_settings.py) -- no
    # `profile=` argument, unlike everything else here.
    brightness = state.get("dock_led_brightness")
    baseline_brightness = (baseline or {}).get("dock_led_brightness")
    if brightness is not None and baseline_brightness != brightness:
        steps.append((f"Dock LED Brightness={brightness}%",
                       lambda sess, v=brightness: dock_settings.set_value(sess, "brightness", v)))
    elif brightness is not None:
        skipped += 1

    dock_auto = state.get("dock_auto_on_off")
    baseline_dock_auto = (baseline or {}).get("dock_auto_on_off")
    if dock_auto is not None and baseline_dock_auto != dock_auto:
        steps.append((f"Dock Auto On/Off={dock_auto}",
                       lambda sess, v=dock_auto: dock_settings.set_value(sess, "auto_on_off", v)))
    elif dock_auto is not None:
        skipped += 1

    baseline_sticks = (baseline or {}).get("sticks", {})
    baseline_triggers = (baseline or {}).get("triggers", {})
    baseline_vibration = (baseline or {}).get("vibration", {})

    for side in ("left", "right"):
        s = state["sticks"].get(side)
        if not s:
            continue
        side_steps, side_skipped = _stick_steps(side, s, baseline_sticks.get(side), profile=slot)
        steps.extend(side_steps)
        skipped += side_skipped

    for side in ("left", "right"):
        t = state["triggers"].get(side)
        if not t:
            continue
        side_steps, side_skipped = _trigger_steps(side, t, baseline_triggers.get(side), profile=slot)
        steps.extend(side_steps)
        skipped += side_skipped

    vib_steps, vib_skipped = _vibration_steps(state["vibration"], baseline_vibration, profile=slot)
    steps.extend(vib_steps)
    skipped += vib_skipped
    nonbutton_step_count = len(steps) - button_step_count

    if baseline is not None:
        # Diff summary: the quickest way to tell "sync did nothing because
        # everything already matched" apart from "sync did nothing because
        # the diff is broken". Logged at INFO so the CLI shows it by default
        # and the GUI can route it wherever it likes.
        log.info(
            "diff summary: %d button entries in state, %d skipped total (matched baseline), "
            "%d button writes, %d non-button writes, %d total steps this run",
            total_button_entries, skipped, button_step_count, nonbutton_step_count, len(steps),
        )

    return steps, skipped


# --- Per-category step builders --------------------------------------------
#
# Each returns (steps, skipped) and shares the same contract: a value of None
# means "not declared, leave the device alone", and a value equal to the
# baseline means "already correct, skip it". They are separate functions
# rather than one loop because each category addresses its settings
# differently -- and each therefore needs its own change-detection test (see
# tests/test_state.py, where a mutation that broke only one of them
# originally went unnoticed).


def _stick_steps(side: str, s: dict, baseline: Optional[dict] = None, profile: int = 1) -> tuple[list[Step], int]:
    """Returns (steps, skipped). `baseline`, if given, is this side's
    "sticks" sub-dict (e.g. baseline["sticks"]["left"]) from a fresh
    read_state() -- see write_state()'s docstring. A target value already
    matching baseline is skipped entirely, same diffing write_state()
    already did for Buttons -- confirmed safe to extend here 2026-07-27 now
    that read_state() decodes real Sticks/Triggers/Vibration values (see
    PROTOCOL.md "Reading current config"). `profile` targets every write
    here (confirmed 2026-07-28 that Sticks writes carry a real profile
    byte, same as Buttons -- see PROTOCOL.md "Profile scoping")."""
    baseline = baseline or {}
    baseline_am = baseline.get("advanced_mapping") or {}
    steps = []
    skipped = 0
    label = f"{side.capitalize()} Stick"

    def _add(value, baseline_value, write_label, fn):
        """fn: Callable[[VendorSession, Any], bytes], called as fn(session, value).

        `value` is bound into the deferred closure here, once it's already
        known non-None -- not via a `lambda sess, v=whatever["key"]: ...`
        default at each call site below. A default-argument expression is
        evaluated eagerly, at lambda-construction time, so a call site of
        that shape crashed with KeyError on a state dict missing the
        sub-section entirely (e.g. no "curve" key), even though `value` was
        already None and this function was about to skip the write anyway.
        """
        nonlocal skipped
        if value is None:
            return
        if baseline_value == value:
            skipped += 1
            return
        steps.append((write_label, lambda sess, _fn=fn, _v=value: _fn(sess, _v)))

    _add(s.get("trajectory"), baseline.get("trajectory"),
         f"{label}: trajectory={s.get('trajectory')}",
         lambda sess, v: sticks.set_value(sess, side, "trajectory", v, profile=profile))
    curve = s.get("curve") or {}
    baseline_curve = baseline.get("curve") or {}
    _add(curve.get("preset"), baseline_curve.get("preset"),
         f"{label}: curve={curve.get('preset')}",
         lambda sess, v: sticks.set_value(sess, side, "curve", v, profile=profile))
    # Deadzone/anti-deadzone: re-enabled 2026-07-28 now that sticks.set_value()
    # builds the write's trailing suffix from a live read of the device's own
    # current state (see VendorSession.read_live_suffix()) instead of a stale captured
    # constant -- see PROTOCOL.md "Sticks" (the live-suffix note) for the
    # corruption mechanism this fixes.
    deadzone = s.get("deadzone") or {}
    baseline_dz = baseline.get("deadzone") or {}
    _add(deadzone.get("initial"), baseline_dz.get("initial"),
         f"{label}: deadzone.initial={deadzone.get('initial')}",
         lambda sess, v: sticks.set_value(sess, side, "deadzone_initial", v, profile=profile))
    _add(deadzone.get("max"), baseline_dz.get("max"),
         f"{label}: deadzone.max={deadzone.get('max')}",
         lambda sess, v: sticks.set_value(sess, side, "deadzone_max", v, profile=profile))
    anti_deadzone = s.get("anti_deadzone") or {}
    baseline_adz = baseline.get("anti_deadzone") or {}
    _add(anti_deadzone.get("initial"), baseline_adz.get("initial"),
         f"{label}: anti_deadzone.initial={anti_deadzone.get('initial')}",
         lambda sess, v: sticks.set_value(sess, side, "anti_deadzone_initial", v, profile=profile))
    _add(anti_deadzone.get("max"), baseline_adz.get("max"),
         f"{label}: anti_deadzone.max={anti_deadzone.get('max')}",
         lambda sess, v: sticks.set_value(sess, side, "anti_deadzone_max", v, profile=profile))
    _add(s.get("resolution_bits"), baseline.get("resolution_bits"),
         f"{label}: resolution_bits={s.get('resolution_bits')}",
         lambda sess, v: sticks.set_value(sess, side, "resolution_bits", v, profile=profile))
    am = s.get("advanced_mapping") or {}
    _add(am.get("output_mode"), baseline_am.get("output_mode"),
         f"{label}: output_mode={am.get('output_mode')}",
         lambda sess, v: sticks.set_value(sess, side, "output_mode", v, profile=profile))
    _add(am.get("invert_x"), baseline_am.get("invert_x"),
         f"{label}: invert_x={am.get('invert_x')}",
         lambda sess, v: sticks.set_value(sess, side, "invert_x", v, profile=profile))
    _add(am.get("invert_y"), baseline_am.get("invert_y"),
         f"{label}: invert_y={am.get('invert_y')}",
         lambda sess, v: sticks.set_value(sess, side, "invert_y", v, profile=profile))
    _add(am.get("sensitivity"), baseline_am.get("sensitivity"),
         f"{label}: sensitivity={am.get('sensitivity')}",
         lambda sess, v: sticks.set_value(sess, side, "sensitivity", v, profile=profile))
    _add(am.get("overlap_area"), baseline_am.get("overlap_area"),
         f"{label}: overlap_area={am.get('overlap_area')}",
         lambda sess, v: sticks.set_value(sess, side, "overlap_area", v, profile=profile))
    _add(am.get("dpi"), baseline_am.get("dpi"),
         f"{label}: dpi={am.get('dpi')}",
         lambda sess, v: sticks.set_value(sess, side, "dpi", v, profile=profile))
    db = am.get("direction_bindings")
    if db is not None:
        value_str = ",".join(db[z] or "ff" for z in ("up", "down", "left", "right", "ring"))
        baseline_db = baseline_am.get("direction_bindings")
        baseline_value_str = (",".join(baseline_db[z] or "ff" for z in ("up", "down", "left", "right", "ring"))
                               if baseline_db else None)
        _add(value_str, baseline_value_str,
             f"{label}: direction_bindings={value_str}",
             lambda sess, v: sticks.set_value(sess, side, "direction_bindings", v, profile=profile))
    return steps, skipped


def _trigger_steps(side: str, t: dict, baseline: Optional[dict] = None, profile: int = 1) -> tuple[list[Step], int]:
    """Returns (steps, skipped) -- see _stick_steps()'s docstring for the
    baseline-diffing approach; `profile` targets every write here too."""
    baseline = baseline or {}
    steps = []
    skipped = 0
    label = f"{side.capitalize()} Trigger"

    def _add(value, baseline_value, write_label, fn):
        """See _stick_steps()'s `_add()` docstring -- same fix, same reason:
        `value` is bound into the deferred closure here, not via a
        `lambda sess, v=whatever["key"]: ...` default at each call site."""
        nonlocal skipped
        if value is None:
            return
        if baseline_value == value:
            skipped += 1
            return
        steps.append((write_label, lambda sess, _fn=fn, _v=value: _fn(sess, _v)))

    _add(t.get("hair_trigger_mode"), baseline.get("hair_trigger_mode"),
         f"{label}: hair_trigger_mode={t.get('hair_trigger_mode')}",
         lambda sess, v: triggers.set_value(sess, side, "hair_trigger_mode", v, profile=profile))
    curve = t.get("curve") or {}
    baseline_curve = baseline.get("curve") or {}
    _add(curve.get("preset"), baseline_curve.get("preset"),
         f"{label}: curve={curve.get('preset')}",
         lambda sess, v: triggers.set_value(sess, side, "curve", v, profile=profile))
    # Deadzone/anti-deadzone: re-enabled 2026-07-28 now that triggers.set_value()
    # builds the write's trailing suffix from a live, side-aware read of the
    # device's own current state (see VendorSession.read_live_suffix()) instead of a
    # stale Left-side constant used verbatim for both sides -- see PROTOCOL.md
    # "Sticks/Triggers/Vibration storage offsets" for the corruption mechanism
    # this fixes (previously: Right Trigger deadzone writes stomped RT's own
    # keycode with LT's).
    deadzone = t.get("deadzone") or {}
    baseline_dz = baseline.get("deadzone") or {}
    _add(deadzone.get("initial"), baseline_dz.get("initial"),
         f"{label}: deadzone.initial={deadzone.get('initial')}",
         lambda sess, v: triggers.set_value(sess, side, "deadzone_initial", v, profile=profile))
    _add(deadzone.get("max"), baseline_dz.get("max"),
         f"{label}: deadzone.max={deadzone.get('max')}",
         lambda sess, v: triggers.set_value(sess, side, "deadzone_max", v, profile=profile))
    anti_deadzone = t.get("anti_deadzone") or {}
    baseline_adz = baseline.get("anti_deadzone") or {}
    _add(anti_deadzone.get("initial"), baseline_adz.get("initial"),
         f"{label}: anti_deadzone.initial={anti_deadzone.get('initial')}",
         lambda sess, v: triggers.set_value(sess, side, "anti_deadzone_initial", v, profile=profile))
    _add(anti_deadzone.get("max"), baseline_adz.get("max"),
         f"{label}: anti_deadzone.max={anti_deadzone.get('max')}",
         lambda sess, v: triggers.set_value(sess, side, "anti_deadzone_max", v, profile=profile))
    return steps, skipped


def _vibration_steps(v: dict, baseline: Optional[dict] = None, profile: int = 1) -> tuple[list[Step], int]:
    """Returns (steps, skipped) -- see _stick_steps()'s docstring for the
    baseline-diffing approach; `profile` targets every write here too."""
    baseline = baseline or {}
    steps = []
    skipped = 0
    for setting in ("left_grip", "right_grip", "left_trigger", "right_trigger"):
        value = v.get(setting)
        if value is None:
            continue
        if baseline.get(setting) == value:
            skipped += 1
            continue
        steps.append((f"Vibration: {setting}={value}",
                       lambda sess, s=setting, val=value: vibration.set_value(sess, s, val, profile=profile)))
    for side in ("left", "right"):
        force = v.get(f"{side}_trigger_force")
        sync = v.get(f"{side}_trigger_sync")
        if force is not None or sync is not None:
            val = f"{'on' if force else 'off'},{'on' if sync else 'off'}"
            baseline_force = baseline.get(f"{side}_trigger_force")
            baseline_sync = baseline.get(f"{side}_trigger_sync")
            baseline_val = (f"{'on' if baseline_force else 'off'},{'on' if baseline_sync else 'off'}"
                             if (baseline_force is not None or baseline_sync is not None) else None)
            if baseline_val == val:
                skipped += 1
                continue
            steps.append((f"Vibration: {side}_trigger_flags={val}",
                           lambda sess, s=f"{side}_trigger_flags", val=val: vibration.set_value(sess, s, val, profile=profile)))
    return steps, skipped
