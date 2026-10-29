"""State schema: a full declared controller configuration as JSON,
write_state() to push one to the device in a single continuous session,
and read_state() to read a profile slot's current button bindings back.

Design (see the project's approved GUI build plan): the state dict is the
source of truth for applying. "Sync" (write_state) always means writing
the entire declared state, never an incremental read-modify-write.

read_state() exists alongside this for a different purpose -- inspecting
real device state (e.g. detecting drift from the onboard on-the-fly remap
shortcuts, or scripting write->read->compare tests) -- not for a
read-modify-write workflow. It decodes Buttons plus Sticks/Triggers/
Vibration -- see PROTOCOL.md "Reading current config" for the wire format
and "Sticks/Triggers/Vibration storage offsets" for where each value lives
(offsets confirmed 2026-07-27 via live write+read-diff on every setting).

Sticks/Triggers/Vibration are decoded from the **Default layer's blob
only**, and that is correct rather than a gap: nothing can write those
categories on the Shift layer. Their prefixes carry a plain profile number
(1-4), and no profile number addresses blob 0x05 -- see PROTOCOL.md "The
Shift layer is button bindings only".

The Shift blob does carry stick/trigger/vibration bytes, but only because
all five blobs share one 480-byte layout, and Nexus never exposes them.
Their values are close to an untouched profile's but not identical:
measured 2026-08-08 from a capture's own read responses, blob 0x05 differs
from Profile 2 in five non-button bytes, all of them the left stick's curve
control points (0x05 holds the Standard preset; untouched profiles hold a
different curve). That does not affect anything here -- the reason to read
only the Default layer is that nothing can *write* those bytes -- but the
blob is not the byte-identical factory copy an earlier version of this
docstring claimed. An earlier revision claimed something stronger -- that
the Shift layer had its own deadzones, curves and vibration levels, making
this a known gap. That was wrong: it compared blob 0x05 against Profile 1,
the one *configured* profile, and read the difference as layer-scoping.
Profiles 2, 3 and 4 show the same values as 0x05. The difference was
configured-versus-factory, not default-versus-shift.

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

from . import buttons, dock_settings, dpad_options, motion, report_rate, sticks, triggers, vibration
from .constants import DOCK_READ_CATEGORY, FULL_BLOB_LENGTH
from .curves import CURVE_PRESETS as _CURVE_PRESETS
from .curves import parse_points as _parse_points
from .field_spec import (
    BUTTON_FIELDS,
    CT_FIELDS,
    DOCK_FIELDS,
    DPAD_FIELDS,
    MOTION_FIELDS,
    REPORT_RATE_FIELD,
    STICK_FIELDS,
    TRIGGER_FIELDS,
    VIBRATION_FLAGS_FIELDS,
    VIBRATION_LEVEL_FIELDS,
    Intent,
)
from .operations import Operation
from .session import VendorSession, profile_layer_byte

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_HAIR_TRIGGER_MODES = set(triggers.HAIR_TRIGGER_MODES)
_OUTPUT_MODES = set(sticks.OUTPUT_MODES)
_MOTION_X_AXIS_MODES = set(motion.X_AXIS_OUTPUT_MODES)
_MOTION_ACTIVATE_METHODS = set(motion.ACTIVATE_METHODS)

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
    # output_mode: None, NOT "left_stick" -- real, found 2026-09-17 while
    # fixing the B2 bug-sweep finding (a real device's factory-default
    # output_mode decodes to None for BOTH sticks, confirmed via
    # tests/fixtures/live_read.json's profile3_factory; this used to give
    # both sides "left_stick" identically, so a brand-new "New State"'s
    # right stick showed "Left Stick" as its output mode from the moment
    # it was loaded, never matching real hardware). None flows correctly
    # through the existing machinery with no other change needed:
    # _stick_steps()'s output_mode _add() already skips a None value
    # (there's no wire operation to "clear" it, same reasoning as
    # invert_x/sensitivity/etc.), validate_state() already accepts None
    # for this field, and _StickSideWidget's own side-aware display
    # fallback (state.py's B2 fix, 2026-09-17, same night) shows "Left
    # Stick"/"Right Stick" correctly for whichever side this loads into,
    # without writing a spurious value unless the user actually edits it.
    return {
        "trajectory": "circle",
        "curve": {"preset": "standard", "points": None},
        "deadzone": {"initial": 0, "max": 100},
        "anti_deadzone": {"initial": 0, "max": 100},
        "resolution_bits": 12,
        "advanced_mapping": {
            "output_mode": None,
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
        "curve": {"preset": "standard", "points": None},
    }


def _default_motion_settings(side: str) -> dict:
    """`side`-dependent only in one field: `invert_roll` is Aim-only (see
    motion.py's module docstring) -- `False` (a real, settable default) on
    Aim, `None` (not applicable) on Tilt."""
    return {
        "activate_method": "off",
        "activate_button": None,
        "x_axis_output_mode": "yaw",
        "curve": {"preset": "standard", "points": None},
        "deadzone": {"initial": 0, "max": 100},
        "anti_deadzone": {"initial": 0, "max": 100},
        "invert_roll": False if side == "aim" else None,
        "invert_y": False,
        "invert_yaw": False,
        "sensitivity_scale": 50,
        "output": "left_stick",
        "overlap_area": 50,
        "direction_bindings": {"up": None, "down": None, "left": None, "right": None},
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
        # Per-button Continuous Trigger. Additive optional field, same convention as
        # report_rate_hz below -- absent from older state files, which still
        # validate. Default layer only: the Shift layer has its own button
        # table and so plausibly its own flags, but that is untested and
        # nothing is known about whether Nexus even exposes it there.
        "continuous_trigger": {},
        "report_rate_hz": 1000,
        "dpad_diagonal_lock": False,
        "swap_stick_dpad": False,
        "dock_led_brightness": 100,
        "dock_auto_on_off": True,
        "sticks": {"left": _default_stick_settings(), "right": _default_stick_settings()},
        "triggers": {"left": _default_trigger_settings(), "right": _default_trigger_settings()},
        # Additive, same reasoning as report_rate_hz/continuous_trigger above:
        # added well after schema_version 1 shipped, so a state dict missing
        # this section entirely (an older export) still validates -- see
        # validate_state() below, where "motion" is checked only if present.
        "motion": {"aim": _default_motion_settings("aim"), "tilt": _default_motion_settings("tilt")},
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


def _require_dict(v: object, label: str) -> None:
    """Raise StateError (not AttributeError) if `v` isn't a dict/object --
    guards every `.items()`/`.get()` call this function makes on a section
    or sub-section, one level deep. REAL BUG, found 2026-09-18 (a code
    review): before this existed, a hand-edited "buttons": [] (wrong
    container type) hit .items() on a list and raised a plain
    AttributeError -- a different exception class than every other
    rejection in this function, so it escaped the CLI's and GUI's
    `except (OSError, ValueError)` handlers as a raw traceback."""
    if not isinstance(v, dict):
        raise StateError(f"{label} must be an object, got {v!r}")


def validate_state(data: dict) -> None:
    """Raises StateError with a clear message on the first problem found.
    Not exhaustive on arbitrarily-deep nested structure (trusts JSON-shape
    mistakes past the first level to surface as KeyError/TypeError during
    write_state instead), but catches the mistakes most likely from
    hand-editing or a GUI bug: unknown names, out-of-range values, wrong
    top-level shape, and wrong container type one level into each section
    (`_require_dict()` above).
    """
    if not isinstance(data, dict):
        raise StateError("state must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise StateError(f"unsupported schema_version {data.get('schema_version')!r}, expected {SCHEMA_VERSION}")
    for key in ("buttons", "sticks", "triggers", "vibration"):
        if key not in data:
            raise StateError(f"missing top-level section {key!r}")

    slot = data.get("controller_slot")
    # isinstance(slot, bool) check: REAL BUG, found 2026-09-18 (a code
    # review). Python's bool is an int subclass and True == 1, so
    # "controller_slot": true in a hand-edited file passed this membership
    # check and behaved as slot 1 -- a plausible hand-editing typo silently
    # retargeting a write. Same reasoning applies to dock_led_brightness and
    # _validate_percent() below.
    if slot is not None and (isinstance(slot, bool) or slot not in (1, 2, 3, 4)):
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

    # Continuous Trigger: additive optional field. Keys are validated against
    # the button table rather than KNOWN_BUTTON_IDS, because LT/RT are real
    # buttons with no table record and therefore no flag -- see
    # buttons.continuous_trigger_offset().
    ct = data.get("continuous_trigger")
    if ct is not None:
        if not isinstance(ct, dict):
            raise StateError(f"continuous_trigger must be an object or null, got {ct!r}")
        for btn, enabled in ct.items():
            if btn not in buttons.BUTTON_TABLE_SLOTS or btn is None:
                raise StateError(f"continuous_trigger: unknown button {btn!r}")
            if enabled is not None and not isinstance(enabled, bool):
                raise StateError(f"continuous_trigger[{btn!r}] must be a bool or null, got {enabled!r}")

    # Dock settings: same additive-field reasoning, and genuinely global/
    # device-wide (see dock_settings.py) -- not tied to controller_slot.
    brightness = data.get("dock_led_brightness")
    # isinstance(brightness, bool) check: see controller_slot's identical
    # 2026-09-18 fix/comment just above -- bool is an int subclass, so
    # "dock_led_brightness": true used to pass isinstance(x, int) and reach
    # the percent coercer as 1, writing 1% brightness.
    if brightness is not None and (
        isinstance(brightness, bool) or not (isinstance(brightness, int) and 0 <= brightness <= 100)
    ):
        raise StateError(f"dock_led_brightness must be 0-100 or null, got {brightness!r}")
    auto = data.get("dock_auto_on_off")
    if auto is not None and not isinstance(auto, bool):
        raise StateError(f"dock_auto_on_off must be a bool or null, got {auto!r}")

    # _require_dict() calls below: REAL BUG, found 2026-09-18 (a code
    # review). A hand-edited snapshot with e.g. "buttons": [] (wrong
    # container type, not just a wrong-shaped dict) hit .items() on a list
    # and raised a raw AttributeError -- a different exception class than
    # the StateError (a ValueError subclass) every other rejection here
    # raises, so it escaped the CLI's and GUI's `except (OSError, ValueError)`
    # handlers as an unhandled traceback instead of a clean error message.
    _require_dict(data["buttons"], "buttons")
    for layer_name, bindings in data["buttons"].items():
        if layer_name not in ("default", "shift"):
            raise StateError(f"unknown button layer {layer_name!r}, expected 'default' or 'shift'")
        _require_dict(bindings, f"buttons.{layer_name}")
        for btn, keycode_name in bindings.items():
            if btn.lower() not in buttons.KNOWN_BUTTON_IDS:
                raise StateError(f"unknown button {btn!r}")
            if keycode_name is not None and not _is_valid_keycode_value(keycode_name):
                raise StateError(f"unknown keycode {keycode_name!r} for button {btn!r}")

    _require_dict(data["sticks"], "sticks")
    for side_name, side_data in data["sticks"].items():
        if side_name not in ("left", "right"):
            raise StateError(f"unknown stick side {side_name!r}")
        _require_dict(side_data, f"sticks.{side_name}")
        _validate_stick_settings(side_data)

    _require_dict(data["triggers"], "triggers")
    for side_name, side_data in data["triggers"].items():
        if side_name not in ("left", "right"):
            raise StateError(f"unknown trigger side {side_name!r}")
        _require_dict(side_data, f"triggers.{side_name}")
        _validate_trigger_settings(side_data)

    # Additive, same reasoning as report_rate_hz/continuous_trigger above --
    # older state JSON exported before this section existed still validates.
    motion_data = data.get("motion")
    if motion_data is not None:
        _require_dict(motion_data, "motion")
        for side_name, side_data in motion_data.items():
            if side_name not in ("aim", "tilt"):
                raise StateError(f"unknown motion side {side_name!r}")
            if side_data is not None:
                _require_dict(side_data, f"motion.{side_name}")
            _validate_motion_settings(side_name, side_data or {})

    # 0-100, NOT vibration.LEVELS. The five-value restriction is a rule about
    # what is worth *writing* (see vibration.LEVELS), not about what the
    # device can hold: the firmware stores any 0-100 byte faithfully, so a
    # controller configured by an older g7ctl -- or mid-experiment -- really
    # can be sitting at 47. Validating that away here made read_state() raise
    # on a perfectly readable controller and made older exports un-importable.
    # The restriction is enforced in _vibration_steps(), at the point a write
    # is actually produced.
    _require_dict(data["vibration"], "vibration")
    _validate_percent(data["vibration"].get("left_grip"), "vibration.left_grip")
    _validate_percent(data["vibration"].get("right_grip"), "vibration.right_grip")
    _validate_percent(data["vibration"].get("left_trigger"), "vibration.left_trigger")
    _validate_percent(data["vibration"].get("right_trigger"), "vibration.right_trigger")
    # Real gap, found 2026-09-01 (second bug-hunt pass): these four went
    # unchecked here entirely, unlike dpad_diagonal_lock/swap_stick_dpad/
    # continuous_trigger just above, which are all isinstance(bool)-checked.
    # _vibration_steps() built its wire value straight from Python
    # truthiness on whatever was declared -- a state dict with
    # "left_trigger_force": "off" (a natural hand-editing mistake, since
    # vibration.set_value()'s own string-token form legitimately uses "on"/
    # "off" elsewhere in this library) passed silently and then wrote
    # force=ON, the exact opposite of what was declared, with no exception
    # anywhere in the pipeline.
    _validate_bool(data["vibration"].get("left_trigger_force"), "vibration.left_trigger_force")
    _validate_bool(data["vibration"].get("left_trigger_sync"), "vibration.left_trigger_sync")
    _validate_bool(data["vibration"].get("right_trigger_force"), "vibration.right_trigger_force")
    _validate_bool(data["vibration"].get("right_trigger_sync"), "vibration.right_trigger_sync")


def _is_valid_keycode_value(s: str) -> bool:
    """Matches what buttons.resolve_keycode() actually accepts: a known
    name, or a raw hex string (e.g. decode_button_table()'s fallback for a
    keycode not in KNOWN_KEYCODES' still-incomplete coverage -- see
    PROTOCOL.md "Keycodes" for the full table, including which entries are
    hardware-confirmed versus predicted).

    Range-checked against 0-255 (a keycode is one wire byte) -- without this,
    a value like "1ff" passed validation cleanly and then crashed
    write_state()/remap() with an opaque bytes-range error far from here.

    isinstance(s, str) check: REAL BUG, found 2026-09-18 (a code review).
    A hand-edited binding like "a": 123 (a raw int, not a string) reached
    s.lower() and raised a plain AttributeError -- same escaped-exception
    problem as _require_dict() above, just here instead of a container
    type."""
    if not isinstance(s, str):
        return False
    if s.lower() in buttons.KNOWN_KEYCODES:
        return True
    try:
        return 0 <= int(s, 16) <= 255
    except ValueError:
        return False


def _validate_percent(v: object, label: str) -> None:
    if v is None:
        return
    # isinstance(v, bool) check: same 2026-09-18 fix as controller_slot/
    # dock_led_brightness above -- bool is an int subclass, so a vibration
    # level of "true" used to pass this check as 1.
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100:
        raise StateError(f"{label} must be 0-100, got {v!r}")


def _validate_bool(v: object, label: str) -> None:
    """Same shape as the inline dpad_diagonal_lock/swap_stick_dpad checks
    above -- pulled out as its own helper since vibration's force/sync
    fields need the identical check four times (added 2026-09-01)."""
    if v is None:
        return
    if not isinstance(v, bool):
        raise StateError(f"{label} must be a bool or null, got {v!r}")


def _validate_vibration_level(v: object, label: str) -> None:
    """Narrower than _validate_percent -- see vibration.LEVELS for why
    vibration is the one percent-style setting restricted to five values
    instead of the full 0-100 range every other one of these allows.

    Deliberately NOT called from validate_state(): a state dict is also how
    a *reading* of the device is carried around, and the device can hold any
    0-100 byte. This is the write-side rule, so it runs in _vibration_steps()
    while steps are being built -- before any of them execute, so a rejected
    value can't leave a half-applied sync behind -- and only for a value that
    is actually about to be written. A setting that already matches the
    device is skipped and never checked, so an off-scale value the user
    isn't touching doesn't block a sync of everything else."""
    if v is None:
        return
    if not isinstance(v, int) or v not in vibration.LEVELS:
        raise StateError(f"{label} must be one of {vibration.LEVELS}, got {v!r}")


def _validate_curve(curve: dict, label: str) -> None:
    """Preset name plus, optionally, the three interior control points.

    `points` is validated through curves.parse_points() so the accepted
    shapes stay identical to what set_value() will accept -- a value that
    validates here but blows up at write time is the failure mode this
    whole validation layer exists to prevent. Note the range is 0-255, not
    0-100: interior points and the deadzone endpoints use different units
    (see curves.py).
    """
    if curve.get("preset") is not None and curve["preset"] not in _CURVE_PRESETS:
        raise StateError(f"unknown curve preset {curve.get('preset')!r}")
    pts = curve.get("points")
    if pts is not None:
        try:
            _parse_points(pts)
        except (ValueError, TypeError) as exc:
            raise StateError(f"{label}.curve.points: {exc}") from exc


def _validate_stick_settings(s: dict) -> None:
    if s.get("trajectory") not in (None, "circle", "raw"):
        raise StateError(f"stick trajectory must be 'circle' or 'raw', got {s.get('trajectory')!r}")
    _validate_curve(s.get("curve") or {}, "stick")
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


def _validate_motion_settings(side: str, s: dict) -> None:
    am = s.get("activate_method")
    if am is not None and am not in _MOTION_ACTIVATE_METHODS:
        raise StateError(f"unknown motion activate_method {am!r}")
    ab = s.get("activate_button")
    if ab is not None and not _is_valid_keycode_value(ab):
        raise StateError(f"unknown keycode {ab!r} for motion.{side}.activate_button")
    xom = s.get("x_axis_output_mode")
    if xom is not None and xom not in _MOTION_X_AXIS_MODES:
        raise StateError(f"unknown x_axis_output_mode {xom!r}")
    _validate_curve(s.get("curve") or {}, f"motion.{side}")
    for field_name in ("deadzone", "anti_deadzone"):
        block = s.get(field_name) or {}
        _validate_percent(block.get("initial"), f"motion.{side}.{field_name}.initial")
        _validate_percent(block.get("max"), f"motion.{side}.{field_name}.max")
    ir = s.get("invert_roll")
    if side == "tilt" and ir is not None:
        raise StateError("motion.tilt.invert_roll must be null -- Tilt has no equivalent control")
    if ir is not None and not isinstance(ir, bool):
        raise StateError(f"motion.{side}.invert_roll must be a bool or null, got {ir!r}")
    for field_name in ("invert_y", "invert_yaw"):
        v = s.get(field_name)
        if v is not None and not isinstance(v, bool):
            raise StateError(f"motion.{side}.{field_name} must be a bool or null, got {v!r}")
    out = s.get("output")
    if out is not None and out not in _OUTPUT_MODES:
        raise StateError(f"unknown motion output {out!r}")
    _validate_percent(s.get("sensitivity_scale"), f"motion.{side}.sensitivity_scale")
    _validate_percent(s.get("overlap_area"), f"motion.{side}.overlap_area")
    db = s.get("direction_bindings")
    if db is not None:
        for zone in ("up", "down", "left", "right"):
            if zone not in db:
                raise StateError(f"motion.{side}.direction_bindings missing zone {zone!r}")
            if db[zone] is not None and not _is_valid_keycode_value(db[zone]):
                raise StateError(f"unknown keycode {db[zone]!r} for motion.{side}.direction_bindings.{zone}")


def _validate_trigger_settings(s: dict) -> None:
    if s.get("hair_trigger_mode") is not None and s["hair_trigger_mode"] not in _HAIR_TRIGGER_MODES:
        raise StateError(f"unknown hair_trigger_mode {s.get('hair_trigger_mode')!r}")
    _validate_curve(s.get("curve") or {}, "trigger")
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
    # REAL BUG, found 2026-09-17 (a code review), reproduced live:
    # _drop_mislabelled_legacy_shift() immediately calls data.get(...) --
    # valid JSON that isn't a dict (a bare list, null, or a scalar) raised
    # a raw AttributeError here, before validate_state()'s own
    # isinstance() check (right below, but too late) ever got a chance to
    # turn it into a clean StateError. Checked directly, not assumed:
    # load_state() on a file containing "[]" raised
    # "'list' object has no attribute 'get'" instead of "state must be a
    # JSON object". Callers (the GUI's Import, the CLI's --state loader)
    # only expect StateError from this function; an AttributeError leaking
    # through was an uncaught crash for either one.
    if not isinstance(data, dict):
        raise StateError("state must be a JSON object")
    _drop_mislabelled_legacy_shift(data, path)
    validate_state(data)
    return data


# The exact moment profile_layer_byte() was fixed to read the real shared
# Shift layer for every profile (commit a57cae2, "Shift is one shared
# layer") -- 2026-08-07T23:03:43-05:00, converted to UTC for a timezone-safe
# comparison against updated_at (which may carry any offset). This is the
# real dividing line between "this file's Shift section is Profile 1's
# Default layer, mislabelled" and "this file's Shift section is the real
# shared layer" -- see _drop_mislabelled_legacy_shift()'s docstring for why
# schema_version alone can no longer tell the two apart.
_SHIFT_FIX_CUTOFF_UTC = datetime(2026, 8, 8, 4, 3, 43, tzinfo=timezone.utc)


def _drop_mislabelled_legacy_shift(data: dict, source: str) -> None:
    """Strip a Shift section that a pre-0.1.4 read got wrong -- but only
    when the file is actually old enough to have been produced by that bug.

    Before 0.1.4, reading a profile other than 1 asked for category
    0x06/0x07/0x08, which the firmware answers with Profile 1's *Default*
    layer -- so an exported Profile 2/3/4 state recorded Profile 1's default
    bindings in its "shift" section. Those bindings were never a Shift layer
    at all.

    That was harmless while Shift writes for those profiles were refused. It
    is not harmless now: the Shift layer is device-global, so writing such a
    file would push Profile 1's Default bindings over the real Shift layer
    that every profile shares.

    REAL BUG, found 2026-09-17 by a code review,
    independently verified and traced further here: this function's own
    docstring used to claim "detection is exact rather than heuristic...
    schema 1 + controller_slot != 1 + a populated shift section ==
    mislabelled, always." That was true for exactly as long as it took to
    write it -- commit a57cae2 fixed profile_layer_byte() to read the real
    shared layer correctly for every profile IN THE SAME COMMIT that added
    this stripper, and SCHEMA_VERSION was never bumped afterward. So from
    the moment this function shipped, "schema_version == SCHEMA_VERSION"
    stopped meaning "could only have been produced by the bug" and started
    meaning "produced by literally any version, bugged or fixed" -- this
    has been silently destroying real Shift bindings on every Profile 2-4
    export/import round trip since v0.1.5, all the way through the current
    release. Confirmed live: a real file already on this machine
    (~/Documents/Gamesir G7 Pro/Default2.json, controller_slot=2, saved
    2026-08-09 -- two days after the fix) carries 15 real, correct Shift
    bindings that this function would have wiped to {} on its next load.

    Fixed by using `updated_at` (present in every export since v0.1.0) as
    the real distinguishing signal instead of schema_version: a file
    demonstrably saved at or after the fix commit's own timestamp
    (_SHIFT_FIX_CUTOFF_UTC) is trusted; only a file with no parseable
    updated_at, or one saved before that moment, is treated as
    old-and-poisoned and stripped as before. Known, deliberately accepted
    imprecision: updated_at reflects SAVE time, not READ time (`_on_export`
    exports whatever is currently in memory, with no forced re-read first)
    -- a controller read before the fix but not exported until after it
    would show a post-fix timestamp while still carrying poisoned data.
    Narrow (the fix is now 6+ weeks old, and the normal GUI flow reads
    fresh on every connect) and strictly better than the prior behavior,
    which struck every current file unconditionally, not just that edge
    case.
    """
    if data.get("schema_version") != SCHEMA_VERSION:
        return
    slot = data.get("controller_slot")
    shift = (data.get("buttons") or {}).get("shift")
    if slot not in (2, 3, 4) or not shift:
        return
    saved_at = None
    raw_updated_at = data.get("updated_at")
    if raw_updated_at:
        try:
            saved_at = datetime.fromisoformat(raw_updated_at)
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            saved_at = None
    if saved_at is not None and saved_at >= _SHIFT_FIX_CUTOFF_UTC:
        return  # demonstrably saved after the real fix landed -- trust it
    log.warning(
        "%s: dropping %d Shift binding(s) recorded for Profile %s by a version before "
        "0.1.4 -- they are Profile 1's Default layer, read through a category the "
        "firmware falls back on, and writing them would overwrite the shared Shift "
        "layer. Re-read the controller to get its real Shift bindings.",
        source, len(shift), slot)
    data["buttons"]["shift"] = {}


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
    (0x01-0x04) plus one Shift layer (0x05). Nothing addresses a Shift layer
    for Profiles 2-4 -- see session.py's profile_layer_byte(), including why
    that is not the same as saying they don't have one -- so their "shift"
    section comes back empty. All 4 stored profiles ARE readable
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
        "continuous_trigger": buttons.decode_continuous_triggers(default_blob),
        "buttons": {
            "default": buttons.decode_button_table(default_blob),
            # The Shift layer is device-global -- one layer shared by all
            # four profiles, read from category 0x05 whatever `slot` says
            # (see session.profile_layer_byte()). It is included in every
            # profile's state for the same reason dock settings are: the
            # user edits it from whichever profile they happen to be on.
            "shift": buttons.read_button_bindings(session, profile=slot, shift=True, interval=interval),
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
        "motion": {
            "aim": motion.decode_settings(default_blob, "aim"),
            "tilt": motion.decode_settings(default_blob, "tilt"),
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


def _points_key(points) -> Optional[str]:
    """Normalise curve points to a comparable string, or None.

    Baseline diffing compares target against live device state, and the two
    arrive in different shapes -- read_state() produces lists of lists while
    a hand-edited JSON file may hold tuples or a flat list. Comparing those
    directly reports a spurious difference and rewrites points that already
    match, so both sides go through the same normalisation.
    """
    if points is None:
        return None
    return ",".join(f"{x},{y}" for x, y in _parse_points(points))


ProgressCallback = Optional[Callable[[int, int, str], None]]


# One entry in the list _build_steps()/the *_steps() helpers return: a
# human-readable label paired with the Operation itself (see
# operations.py's own docstring for why Operation moved out of this
# file: field_spec.py needs it too, and keeping it here would cycle
# back through state.py).
Step = tuple[str, Operation]


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

    for i, (label, op) in enumerate(steps, start=1):
        _report(i, label)
        op.execute(session)
        time.sleep(interval)
        session.heartbeat()
        time.sleep(interval)

    for _ in range(WRITE_POST_HEARTBEATS):
        time.sleep(interval)
        session.heartbeat()

    return skipped


def _build_steps(state: dict, baseline: Optional[dict] = None) -> tuple[list[Step], int]:
    """Returns (steps, skipped): a list of (label, Operation) pairs in
    application order, and a count of Buttons writes skipped via baseline
    diffing (always 0 if `baseline` is None)."""
    steps = []
    skipped = 0
    slot = state.get("controller_slot") or 1
    baseline_buttons = (baseline or {}).get("buttons", {})

    # S3's last FieldSpec migration (Projects/g7ctl/redesign/
    # IMPLEMENTATION-PLAN.md, Track S) -- see ButtonFieldSpec's own
    # docstring for why buttons never needed the has_baseline
    # disambiguation Motion did: an undeclared button is structurally
    # absent from this dict, never iterated at all, so the skip-vs-write
    # decision below is unchanged from before this migration.
    for layer_name in ("default", "shift"):
        baseline_layer = baseline_buttons.get(layer_name, {})
        for btn, keycode_name in state["buttons"].get(layer_name, {}).items():
            if baseline is not None and baseline_layer.get(btn) == keycode_name:
                skipped += 1
                continue  # already matches live device state -- see baseline diffing above
            field = BUTTON_FIELDS[layer_name][btn]
            desired = Intent.CLEAR if keycode_name is None else keycode_name
            # baseline is accepted and ignored by ButtonFieldSpec -- see
            # its own docstring. Passed for documentation's sake even
            # though this loop already made its own skip-vs-write call
            # via baseline_layer above.
            op = field.plan_operation(desired, baseline_layer.get(btn), slot)
            label = (f"Button {btn} ({layer_name}): unbind" if keycode_name is None
                     else f"Button {btn} ({layer_name}) -> {keycode_name}")
            steps.append((label, op))

    # Count binding writes before anything else is appended. The diff
    # summary below exists to tell "sync did nothing because everything
    # matched" apart from "sync did nothing because the diff is broken", so
    # its numbers have to mean what they say -- and Continuous Trigger
    # steps, appended next, were briefly being reported as button writes.
    button_step_count = len(steps)

    # Continuous Trigger, one boolean per button. Written after
    # the bindings above deliberately: a remap of an unconfigured slot uses
    # the 2-byte allocate form, which rewrites the record's marker+keycode,
    # and applying Continuous Trigger first would leave it fighting a later allocate
    # on the same record. Bindings first, flags second.
    baseline_ct = (baseline or {}).get("continuous_trigger") or {}
    for btn, enabled in (state.get("continuous_trigger") or {}).items():
        if enabled is None:
            continue
        op = CT_FIELDS[btn].plan_operation(enabled, baseline_ct.get(btn) if baseline is not None else None, slot)
        if op is None:
            skipped += 1
            continue
        steps.append((f"Continuous Trigger {btn}={enabled}", op))

    total_button_entries = sum(len(state["buttons"].get(layer, {})) for layer in ("default", "shift"))

    # S3's first FieldSpec migration (Projects/g7ctl/redesign/
    # IMPLEMENTATION-PLAN.md, Track S) -- report rate has no clear
    # semantics (always some rate, never "unset"), so an undeclared
    # value maps to Intent.PRESERVE, never Intent.CLEAR. plan_operation()
    # is the one place this field's "declared and differs from baseline"
    # decision is made now, not inlined here.
    rate = state.get("report_rate_hz")
    baseline_rate = (baseline or {}).get("report_rate_hz")
    rate_op = REPORT_RATE_FIELD.plan_operation(
        Intent.PRESERVE if rate is None else rate, baseline_rate, slot)
    if rate_op is not None:
        steps.append((f"Report rate={rate}Hz", rate_op))
    elif rate is not None:
        skipped += 1

    # S3 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S):
    # DPAD_FIELDS/DOCK_FIELDS now own the declared-vs-baseline decision;
    # this function still owns the undeclared-is-None-not-PRESERVE
    # translation and the `skipped` counter, same split as every other
    # migrated field above.
    diag = state.get("dpad_diagonal_lock")
    baseline_diag = (baseline or {}).get("dpad_diagonal_lock")
    diag_op = DPAD_FIELDS["dpad_diagonal_lock"].plan_operation(
        Intent.PRESERVE if diag is None else diag, baseline_diag, slot)
    if diag_op is not None:
        steps.append((f"D-Pad Diagonal Lock={diag}", diag_op))
    elif diag is not None:
        skipped += 1

    # Write-enabled 2026-07-28 -- set_swap_stick_dpad()
    # reads its collateral 53-byte span live rather than trusting a captured
    # constant, same reasoning as Sticks/Triggers deadzone -- see
    # PROTOCOL.md "Sticks".
    swap = state.get("swap_stick_dpad")
    baseline_swap = (baseline or {}).get("swap_stick_dpad")
    swap_op = DPAD_FIELDS["swap_stick_dpad"].plan_operation(
        Intent.PRESERVE if swap is None else swap, baseline_swap, slot)
    if swap_op is not None:
        steps.append((f"Swap Left Stick and D-pad={swap}", swap_op))
    elif swap is not None:
        skipped += 1

    # Dock settings are genuinely global (see dock_settings.py) -- no
    # `profile=` argument, unlike everything else here. DOCK_FIELDS'
    # own build_kwargs already knows this; `slot` is still passed through
    # plan_operation()'s signature uniformly but DOCK_FIELDS ignores it.
    brightness = state.get("dock_led_brightness")
    baseline_brightness = (baseline or {}).get("dock_led_brightness")
    brightness_op = DOCK_FIELDS["dock_led_brightness"].plan_operation(
        Intent.PRESERVE if brightness is None else brightness, baseline_brightness, slot)
    if brightness_op is not None:
        steps.append((f"Dock LED Brightness={brightness}%", brightness_op))
    elif brightness is not None:
        skipped += 1

    dock_auto = state.get("dock_auto_on_off")
    baseline_dock_auto = (baseline or {}).get("dock_auto_on_off")
    dock_auto_op = DOCK_FIELDS["dock_auto_on_off"].plan_operation(
        Intent.PRESERVE if dock_auto is None else dock_auto, baseline_dock_auto, slot)
    if dock_auto_op is not None:
        steps.append((f"Dock Auto On/Off={dock_auto}", dock_auto_op))
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

    # Additive section (see validate_state()) -- state.get() rather than
    # state[...] since an older state dict may not have "motion" at all.
    baseline_motion = (baseline or {}).get("motion", {})
    for side in ("aim", "tilt"):
        m = (state.get("motion") or {}).get(side)
        if not m:
            continue
        side_steps, side_skipped = _motion_steps(side, m, baseline_motion.get(side), profile=slot)
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

    fields = STICK_FIELDS[side]

    def _add(value, baseline_value, write_label, field_spec):
        """S3 migration (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md,
        Track S): `field_spec` now does the declared-vs-baseline decision
        `FieldSpec.plan_operation()` owns; this wrapper only still
        translates this function's own None-means-undeclared convention
        into `Intent.PRESERVE` and keeps the `skipped` counter, which is
        local to this call (`nonlocal`), not something FieldSpec tracks
        itself."""
        nonlocal skipped
        desired = Intent.PRESERVE if value is None else value
        op = field_spec.plan_operation(desired, baseline_value, profile)
        if op is None:
            if value is not None:
                skipped += 1
            return
        steps.append((write_label, op))

    _add(s.get("trajectory"), baseline.get("trajectory"),
         f"{label}: trajectory={s.get('trajectory')}", fields["trajectory"])
    curve = s.get("curve") or {}
    baseline_curve = baseline.get("curve") or {}
    _add(curve.get("preset"), baseline_curve.get("preset"),
         f"{label}: curve={curve.get('preset')}", fields["curve"])
    # Points go after the preset deliberately: selecting a preset rewrites
    # the whole block including the points, so writing them first would be
    # undone by the preset write that follows.
    #
    # REAL BUG, found 2026-09-17 (a code review): a points write is
    # ALWAYS whole_block=True (write_curve_points()'s own default), and
    # curve_block_payload() defaults preset_index to Custom whenever one
    # isn't explicitly passed -- sticks.set_value()'s "curve_points" branch
    # never passes one. So this write not only followed the preset write,
    # it silently OVERWROTE it back to Custom every time, even though
    # curve_preset_payload() (the preset write itself) already sends the
    # named preset's real shape data in one 10-byte write -- a follow-up
    # points write is not just redundant for a named preset, it actively
    # undoes the write right before it. Only reachable with points
    # actually populated alongside a named preset, which the GUI itself
    # never produces (curve["points"] is always None unless preset ==
    # "custom") -- but a real device read does (decode_settings() decodes
    # both fields unconditionally), which is exactly the restore-a-
    # snapshot path this was found through. Fixed by only ever scheduling
    # this write for a genuinely Custom curve; a named preset's own write
    # already fully defines the block, points included.
    if curve.get("preset") == "custom":
        _add(curve.get("points"), baseline_curve.get("points"),
             f"{label}: curve points={_points_key(curve.get('points'))}", fields["curve_points"])
    # Deadzone/anti-deadzone: re-enabled 2026-07-28 now that sticks.set_value()
    # builds the write's trailing suffix from a live read of the device's own
    # current state (see VendorSession.read_live_suffix()) instead of a stale captured
    # constant -- see PROTOCOL.md "Sticks" (the live-suffix note) for the
    # corruption mechanism this fixes.
    deadzone = s.get("deadzone") or {}
    baseline_dz = baseline.get("deadzone") or {}
    _add(deadzone.get("initial"), baseline_dz.get("initial"),
         f"{label}: deadzone.initial={deadzone.get('initial')}", fields["deadzone_initial"])
    _add(deadzone.get("max"), baseline_dz.get("max"),
         f"{label}: deadzone.max={deadzone.get('max')}", fields["deadzone_max"])
    anti_deadzone = s.get("anti_deadzone") or {}
    baseline_adz = baseline.get("anti_deadzone") or {}
    _add(anti_deadzone.get("initial"), baseline_adz.get("initial"),
         f"{label}: anti_deadzone.initial={anti_deadzone.get('initial')}", fields["anti_deadzone_initial"])
    _add(anti_deadzone.get("max"), baseline_adz.get("max"),
         f"{label}: anti_deadzone.max={anti_deadzone.get('max')}", fields["anti_deadzone_max"])
    _add(s.get("resolution_bits"), baseline.get("resolution_bits"),
         f"{label}: resolution_bits={s.get('resolution_bits')}", fields["resolution_bits"])
    am = s.get("advanced_mapping") or {}
    _add(am.get("output_mode"), baseline_am.get("output_mode"),
         f"{label}: output_mode={am.get('output_mode')}", fields["output_mode"])
    _add(am.get("invert_x"), baseline_am.get("invert_x"),
         f"{label}: invert_x={am.get('invert_x')}", fields["invert_x"])
    _add(am.get("invert_y"), baseline_am.get("invert_y"),
         f"{label}: invert_y={am.get('invert_y')}", fields["invert_y"])
    _add(am.get("sensitivity"), baseline_am.get("sensitivity"),
         f"{label}: sensitivity={am.get('sensitivity')}", fields["sensitivity"])
    _add(am.get("overlap_area"), baseline_am.get("overlap_area"),
         f"{label}: overlap_area={am.get('overlap_area')}", fields["overlap_area"])
    _add(am.get("dpi"), baseline_am.get("dpi"),
         f"{label}: dpi={am.get('dpi')}", fields["dpi"])
    db = am.get("direction_bindings")
    if db is not None:
        value_str = ",".join(db[z] or "ff" for z in ("up", "down", "left", "right", "ring"))
        baseline_db = baseline_am.get("direction_bindings")
        baseline_value_str = (",".join(baseline_db[z] or "ff" for z in ("up", "down", "left", "right", "ring"))
                               if baseline_db else None)
        _add(value_str, baseline_value_str,
             f"{label}: direction_bindings={value_str}", fields["direction_bindings"])
    return steps, skipped


def _trigger_steps(side: str, t: dict, baseline: Optional[dict] = None, profile: int = 1) -> tuple[list[Step], int]:
    """Returns (steps, skipped) -- see _stick_steps()'s docstring for the
    baseline-diffing approach; `profile` targets every write here too."""
    baseline = baseline or {}
    steps = []
    skipped = 0
    label = f"{side.capitalize()} Trigger"

    fields = TRIGGER_FIELDS[side]

    def _add(value, baseline_value, write_label, field_spec):
        """See _stick_steps()'s `_add()` docstring -- same migration,
        same reason."""
        nonlocal skipped
        desired = Intent.PRESERVE if value is None else value
        op = field_spec.plan_operation(desired, baseline_value, profile)
        if op is None:
            if value is not None:
                skipped += 1
            return
        steps.append((write_label, op))

    _add(t.get("hair_trigger_mode"), baseline.get("hair_trigger_mode"),
         f"{label}: hair_trigger_mode={t.get('hair_trigger_mode')}", fields["hair_trigger_mode"])
    curve = t.get("curve") or {}
    baseline_curve = baseline.get("curve") or {}
    _add(curve.get("preset"), baseline_curve.get("preset"),
         f"{label}: curve={curve.get('preset')}", fields["curve"])
    # After the preset, for the same reason as _stick_steps() -- including
    # the same real bug and fix, see its own comment: only ever schedule
    # this for a genuinely Custom curve, since a named preset's own write
    # already fully defines the block (including points) and a follow-up
    # points write would silently overwrite that preset index back to
    # Custom.
    if curve.get("preset") == "custom":
        _add(curve.get("points"), baseline_curve.get("points"),
             f"{label}: curve points={_points_key(curve.get('points'))}", fields["curve_points"])
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
         f"{label}: deadzone.initial={deadzone.get('initial')}", fields["deadzone_initial"])
    _add(deadzone.get("max"), baseline_dz.get("max"),
         f"{label}: deadzone.max={deadzone.get('max')}", fields["deadzone_max"])
    anti_deadzone = t.get("anti_deadzone") or {}
    baseline_adz = baseline.get("anti_deadzone") or {}
    _add(anti_deadzone.get("initial"), baseline_adz.get("initial"),
         f"{label}: anti_deadzone.initial={anti_deadzone.get('initial')}", fields["anti_deadzone_initial"])
    _add(anti_deadzone.get("max"), baseline_adz.get("max"),
         f"{label}: anti_deadzone.max={anti_deadzone.get('max')}", fields["anti_deadzone_max"])
    return steps, skipped


def _motion_steps(side: str, s: dict, baseline: Optional[dict] = None, profile: int = 1) -> tuple[list[Step], int]:
    """Returns (steps, skipped) -- see _stick_steps()'s docstring for the
    baseline-diffing approach. `side` is "aim" or "tilt"; `invert_roll` is
    skipped entirely on Tilt (see motion.py's module docstring -- Tilt has
    no equivalent control, and motion.set_value() raises if asked)."""
    has_baseline = baseline is not None  # captured before the collapse below --
    # see _add()'s allow_none branch for why this has to survive separately
    # from "this field's own baseline value happens to be None."
    baseline = baseline or {}
    steps = []
    skipped = 0
    label = f"Motion {side.capitalize()}"

    fields = MOTION_FIELDS[side]

    def _add(value, baseline_value, write_label, field_spec, allow_none=False):
        """S3 migration (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md,
        Track S): `field_spec` now owns the declared-vs-baseline decision
        for the plain case. `allow_none` fields (activate_button, each
        direction zone) keep their own resolution here rather than
        inside `FieldSpec.plan_operation()` -- see `field_spec.py`'s own
        comment on `MOTION_FIELDS` for why: `baseline=None` means "no
        known baseline, write unconditionally" for every other field,
        but these fields' real "unbound" state also decodes to `None`,
        indistinguishable from "unknown" at the single-value level.
        `has_baseline` (the OUTER dict's presence, not this one field's
        value) is the signal `plan_operation()` doesn't have access to.
        """
        nonlocal skipped
        if value is None and not allow_none:
            return
        if allow_none and value is None:
            if not has_baseline:
                steps.append((write_label, field_spec.plan_operation(Intent.CLEAR, None, profile)))
                return
            if baseline_value is None:
                skipped += 1
                return
            steps.append((write_label, field_spec.plan_operation(Intent.CLEAR, baseline_value, profile)))
            return
        op = field_spec.plan_operation(value, baseline_value, profile)
        if op is None:
            skipped += 1
            return
        steps.append((write_label, op))

    _add(s.get("activate_method"), baseline.get("activate_method"),
         f"{label}: activate_method={s.get('activate_method')}", fields["activate_method"])
    # S2 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md), the
    # absent-vs-null decision DESIGN-SPEC.md 10.4 asked for: a key
    # genuinely ABSENT from `s` (a hand-edited partial state JSON that
    # never mentions this field) means "not declared, leave it alone" --
    # same as every other field's None. Only a key PRESENT with an
    # explicit `None` value is a real clear, matching buttons.py's own
    # sparse-dict convention (an unmentioned button is never touched; a
    # button present with value None is unbound). `dict.get()` alone
    # can't tell the two apart, which is exactly the real bug this
    # closes (plan section 7: "Partial state JSON clears Motion
    # bindings"). Guarding the call, not `_add()`'s own allow_none
    # branch, keeps every other field's behaviour untouched.
    if "activate_button" in s:
        _add(s.get("activate_button"), baseline.get("activate_button"),
             f"{label}: activate_button={s.get('activate_button')}",
             fields["activate_button"], allow_none=True)
    _add(s.get("x_axis_output_mode"), baseline.get("x_axis_output_mode"),
         f"{label}: x_axis_output_mode={s.get('x_axis_output_mode')}", fields["x_axis_output_mode"])
    curve = s.get("curve") or {}
    baseline_curve = baseline.get("curve") or {}
    _add(curve.get("preset"), baseline_curve.get("preset"),
         f"{label}: curve={curve.get('preset')}", fields["curve"])
    # Deadzone/anti-deadzone after the curve preset, same reasoning as
    # _stick_steps(): a preset selection rewrites the whole curve block.
    deadzone = s.get("deadzone") or {}
    baseline_dz = baseline.get("deadzone") or {}
    _add(deadzone.get("initial"), baseline_dz.get("initial"),
         f"{label}: deadzone.initial={deadzone.get('initial')}", fields["deadzone_initial"])
    _add(deadzone.get("max"), baseline_dz.get("max"),
         f"{label}: deadzone.max={deadzone.get('max')}", fields["deadzone_max"])
    anti_deadzone = s.get("anti_deadzone") or {}
    baseline_adz = baseline.get("anti_deadzone") or {}
    _add(anti_deadzone.get("initial"), baseline_adz.get("initial"),
         f"{label}: anti_deadzone.initial={anti_deadzone.get('initial')}", fields["anti_deadzone_initial"])
    _add(anti_deadzone.get("max"), baseline_adz.get("max"),
         f"{label}: anti_deadzone.max={anti_deadzone.get('max')}", fields["anti_deadzone_max"])
    if side == "aim":
        _add(s.get("invert_roll"), baseline.get("invert_roll"),
             f"{label}: invert_roll={s.get('invert_roll')}", fields["invert_roll"])
    _add(s.get("invert_y"), baseline.get("invert_y"),
         f"{label}: invert_y={s.get('invert_y')}", fields["invert_y"])
    _add(s.get("invert_yaw"), baseline.get("invert_yaw"),
         f"{label}: invert_yaw={s.get('invert_yaw')}", fields["invert_yaw"])
    _add(s.get("sensitivity_scale"), baseline.get("sensitivity_scale"),
         f"{label}: sensitivity_scale={s.get('sensitivity_scale')}", fields["sensitivity_scale"])
    _add(s.get("output"), baseline.get("output"),
         f"{label}: output={s.get('output')}", fields["output"])
    _add(s.get("overlap_area"), baseline.get("overlap_area"),
         f"{label}: overlap_area={s.get('overlap_area')}", fields["overlap_area"])
    db = s.get("direction_bindings") or {}
    baseline_db = baseline.get("direction_bindings") or {}
    for zone in ("up", "down", "left", "right"):
        # Same absent-vs-null fix as activate_button just above, per zone:
        # a zone genuinely missing from a partial `direction_bindings`
        # dict is left alone, not read as a clear.
        if zone not in db:
            continue
        _add(db.get(zone), baseline_db.get(zone),
             f"{label}: direction_bindings.{zone}={db.get(zone)}",
             fields[f"direction_{zone}"], allow_none=True)
    return steps, skipped


def _vibration_steps(v: dict, baseline: Optional[dict] = None, profile: int = 1) -> tuple[list[Step], int]:
    """Returns (steps, skipped) -- see _stick_steps()'s docstring for the
    baseline-diffing approach; `profile` targets every write here too."""
    baseline = baseline or {}
    steps = []
    skipped = 0
    # S3's second FieldSpec migration (Projects/g7ctl/redesign/
    # IMPLEMENTATION-PLAN.md, Track S): the four simple levels, not the
    # packed force/sync pair below -- see VIBRATION_LEVEL_FIELDS's own
    # comment for why those stay on the old inline path for now.
    for setting, level_field in VIBRATION_LEVEL_FIELDS.items():
        value = v.get(setting)
        desired = Intent.PRESERVE if value is None else value
        op = level_field.plan_operation(desired, baseline.get(setting), profile)
        if op is not None:
            # About to actually write this one, so now the five-value rule
            # applies. Raising here happens during the build, before any
            # step has run against the device -- same ordering as before
            # this migration: validate only on the write path, not when
            # plan_operation() is about to skip anyway.
            _validate_vibration_level(value, f"vibration.{setting}")
            steps.append((f"Vibration: {setting}={value}", op))
        elif value is not None:
            skipped += 1
    # S3's coupled-field migration (Projects/g7ctl/redesign/
    # IMPLEMENTATION-PLAN.md, Track S): CoupledFieldSpec now owns the
    # "undeclared half carries forward from baseline" rule (the real
    # 2026-09-01 bug fix) -- this loop only still decides the one thing
    # a coupled field's own plan_operation() can't: whether BOTH halves
    # are undeclared, which must skip without counting (continue, not
    # skipped += 1), same as before this migration.
    for side in ("left", "right"):
        force = v.get(f"{side}_trigger_force")
        sync = v.get(f"{side}_trigger_sync")
        if force is None and sync is None:
            continue
        desired = {
            "force": Intent.PRESERVE if force is None else force,
            "sync": Intent.PRESERVE if sync is None else sync,
        }
        field_baseline = {
            "force": baseline.get(f"{side}_trigger_force"),
            "sync": baseline.get(f"{side}_trigger_sync"),
        }
        op = VIBRATION_FLAGS_FIELDS[side].plan_operation(desired, field_baseline, profile)
        if op is None:
            skipped += 1
            continue
        steps.append((f"Vibration: {side}_trigger_flags={op.args[1]}", op))
    return steps, skipped
