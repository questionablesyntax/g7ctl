"""Motion tab: Aim/Tilt gyro settings.

Structurally a stick config, reusing Sticks' own category prefix
`03 [profile] 01` (page 1) and the same `SETTING_ID + STORAGE_BASE + off`
storage convention -- confirmed by direct write+read-diff capture, not by
resemblance alone (see PROTOCOL.md "Motion"). Aim and Tilt are one register
block each, `0x22` (34 bytes) apart -- NOT the `0x20` a stick's Left/Right
offset uses, and not the `+0x61` layout an earlier session inferred from
the block's shape before any field had actually been captured (see
PROTOCOL.md "Motion" for that history; it matters only as a cautionary
note now that every field below is measured).

Two fields do not follow the clean `0x22` stride, and both are documented
where they're used rather than glossed over:

- `invert_yaw`'s Tilt address is `0x1B4 + 0x20`, not `+0x22` -- the one
  off-stride field in the whole category, first noticed because it broke
  the naive layout inferred from `test65`. Still address-only: what it's
  actually called on the Tilt side (if it's shown there at all outside
  the specific mode this was measured under) is unconfirmed.
- `invert_roll` exists on Aim only. Tilt has no equivalent control under
  any combination of Output/X-Axis Output Mode tested.

Two gates were mistaken for one during the capture session, worth stating
plainly since it shapes `decode_settings()`/`set_value()` below:
`x_axis_output_mode` (not `output`) decides whether an invert control
exists at all -- only `"yaw_roll"` shows one -- and `output`'s Button
Binds setting then decides which byte/label it is: `invert_yaw` outside
Button Binds, `invert_roll` inside it (Aim only).

Not covered here, flagged rather than silently assumed complete:
Mouse output mode may have its own extra field(s) the way Sticks' Mouse
mode has DPI -- never captured, no capture attempted. Custom curve point
dragging was never exercised either (only the three named presets plus
Custom's mode-select flag) -- `decode_settings()` will decode a Custom
curve's stored points if the block is configured, matching Sticks'
`decode_curve_points()`, but `set_value()` has no `curve_points` setting
the way `sticks.SETTING_IDS`/`triggers.SETTING_IDS` do, so writing
individual points isn't supported yet.
"""
from .buttons import decode_keycode, resolve_keycode
from .constants import CMD_WRITE, prefix_sticks
from .curves import CURVE_PRESET_INDEX, CURVE_PRESET_NAMES, decode_curve_points
from .session import VendorSession
from .sticks import OUTPUT_MODES
from .values import SettingValue
from .values import boolean as _bool
from .values import percent as _percent

_OUTPUT_MODE_NAMES = {v: k for k, v in OUTPUT_MODES.items()}

X_AXIS_OUTPUT_MODES = {"yaw": 0x01, "yaw_roll": 0x03}
_X_AXIS_OUTPUT_MODE_NAMES = {v: k for k, v in X_AXIS_OUTPUT_MODES.items()}

# Confirmed 2026-08-18 (owner, reading Nexus's own Activate Method dropdown
# directly) -- not inferred from convention the way the earlier guess that
# 0x00 = "Off" was. Matches the guess for 0x00, but the other three values
# had no candidate names before this.
ACTIVATE_METHODS = {
    "off": 0x00,
    "hold_to_activate": 0x01,
    "press_to_activate": 0x02,
    "always_on": 0x03,
}
_ACTIVATE_METHOD_NAMES = {v: k for k, v in ACTIVATE_METHODS.items()}

# Local (page-1) offsets, valid for Aim. Add TILT_OFFSET for Tilt, except
# "invert_yaw" (its own, off-stride TILT_INVERT_YAW_OFFSET) and
# "invert_roll" (Aim only -- see _side_offset()).
#
# Confirmed 2026-08-18 by direct capture (test72-test77), one control at a
# time with pauses, decoded straight off the wire -- not inferred from the
# blob's shape. See PROTOCOL.md "Motion" for the full record, including
# the two prior partial passes (test61, test65) this superseded.
SETTING_IDS = {
    "activate_method": 0x9C,   # named enum, ACTIVATE_METHODS -- see above
    "activate_button": 0x9D,   # keycode -- which button, held/pressed, activates motion input
    "x_axis_output_mode": 0x9E,
    "deadzone_initial": 0xA0,
    "deadzone_max": 0xA1,
    "anti_deadzone_initial": 0xA2,
    "anti_deadzone_max": 0xA3,
    "curve": 0xA5,
    "invert_roll": 0xB2,       # Aim only -- see module docstring
    "invert_y": 0xB3,
    "invert_yaw": 0xB4,        # Tilt: +0x20, not +0x22 -- see TILT_INVERT_YAW_OFFSET
    "sensitivity_scale": 0xB5,  # single slider (Horizontal<->Vertical balance), like
                                 # sticks.py's "sensitivity" -- not two handles like Deadzone
    "output": 0xB7,
    "overlap_area": 0xB8,      # Output=directional (Button Binds) only
    "direction_up": 0xB9,      # Output=directional only. Four independent single-byte
    "direction_down": 0xBA,    # settings, NOT one bulk write the way sticks.py's
    "direction_left": 0xBB,    # direction_bindings is -- confirmed on the wire, one write
    "direction_right": 0xBC,   # per direction. No "ring" zone (motion has no stick click).
}
SETTINGS = set(SETTING_IDS)

STORAGE_BASE = 0x100
TILT_OFFSET = 0x22
TILT_INVERT_YAW_OFFSET = 0x20  # off-stride -- see module docstring

_DIRECTION_SETTINGS = ("direction_up", "direction_down", "direction_left", "direction_right")
_DIRECTION_ZONES = {"direction_up": "up", "direction_down": "down",
                     "direction_left": "left", "direction_right": "right"}

# Motion's own curve shape data -- numerically different from Sticks'/
# Triggers' (see curves.py), same 9-byte structure
# ([scale][origin x2][P1 x2][P2 x2][P3 x2]). Captured 2026-08-18 (test72),
# cycling all four Curve Adjustment presets on the Aim sub-tab with pauses:
#   Standard: 03 01 01 a5 0a 00 64 00 00 28 28 80 81 d7 d7
#   Concave:  03 01 01 a5 0a 01 64 00 00 5e 17 ae 4f e8 a2
#   S-Curve:  03 01 01 a5 0a 02 64 00 00 28 4c 80 81 d7 b3
#   Custom:   03 01 01 a5 01 03            (mode-select only, no shape data --
#                                            LEN=1, unlike Sticks'/Triggers'
#                                            4-byte custom form; not touched
#                                            here, this is Motion's own
#                                            measured shape)
_CURVE_SHAPE_DATA = {
    0x00: bytes.fromhex("64000028288081d7d7"),
    0x01: bytes.fromhex("6400005e17ae4fe8a2"),
    0x02: bytes.fromhex("64000028 4c 80 81 d7 b3".replace(" ", "")),
}

# Long-form Deadzone/Anti-Deadzone templates -- same convention as
# sticks.py/triggers.py (the byte after the setting ID is a LENGTH, and the
# firmware drops a write that isn't heartbeat-wrapped, not relevant to the
# marker itself). Re-extracted directly from Motion's own captured writes
# (test72), Aim and Tilt cross-checked against each other where both
# produced a full long-form write for the same field -- markers matched
# exactly between sides in every case that gave two samples. Suffix length
# is `marker - 1` (marker counts the value byte plus the suffix), unlike
# a discrepancy visible in sticks.py's own constants that this module does
# not attempt to explain, only to avoid repeating: these are computed
# directly from Motion's own wire bytes, not derived from Sticks'.
_DEADZONE_INITIAL_MARKER = 0x0E
_DEADZONE_INITIAL_SUFFIX_LEN = 13
_DEADZONE_MAX_MARKER = 0x0D
_DEADZONE_MAX_SUFFIX_LEN = 12
_ANTI_DEADZONE_INITIAL_MARKER = 0x0D
_ANTI_DEADZONE_INITIAL_SUFFIX_LEN = 12
_ANTI_DEADZONE_MAX_MARKER = 0x0C
_ANTI_DEADZONE_MAX_SUFFIX_LEN = 11


def _side_offset(side: str, setting: str) -> int:
    side = side.lower()
    if side not in ("aim", "tilt"):
        raise ValueError(f"side must be 'aim' or 'tilt', got {side!r}")
    if side == "aim":
        return 0
    if setting == "invert_roll":
        raise ValueError("invert_roll is Aim-only -- Tilt has no equivalent control")
    if setting == "invert_yaw":
        return TILT_INVERT_YAW_OFFSET
    return TILT_OFFSET


def _curve_preset_payload(setting_id: int, preset: str) -> bytes:
    """Motion's own version of curves.curve_preset_payload() -- same shape
    convention, Motion's own captured bytes. See _CURVE_SHAPE_DATA above."""
    preset = preset.lower()
    if preset == "custom":
        return bytes([setting_id, 0x01, 0x03])
    if preset not in CURVE_PRESET_INDEX:
        raise ValueError(f"unknown curve preset {preset!r}, expected one of {list(CURVE_PRESET_INDEX) + ['custom']}")
    idx = CURVE_PRESET_INDEX[preset]
    return bytes([setting_id, 0x0A, idx]) + _CURVE_SHAPE_DATA[idx]


def decode_settings(blob: bytes, side: str = "aim") -> dict:
    """Decode one sub-tab's Motion settings from a profile config blob's
    DEFAULT-layer read -- Motion isn't layer-scoped, same reasoning as
    Sticks (see state.py's read_state()). Returns a dict shaped like one
    side of the "motion" section of a state dict."""
    side = side.lower()

    def off(setting):
        return _side_offset(side, setting)

    def b(setting):
        i = SETTING_IDS[setting] + STORAGE_BASE + off(setting)
        return blob[i] if i < len(blob) else None

    invert_roll = None
    if side == "aim":
        invert_roll = bool(b("invert_roll"))

    directions = {}
    for setting in _DIRECTION_SETTINGS:
        i = SETTING_IDS[setting] + STORAGE_BASE + off(setting)
        code = blob[i] if i < len(blob) else None
        directions[_DIRECTION_ZONES[setting]] = None if code in (None, 0xFF) else decode_keycode(code)

    return {
        "activate_method": _ACTIVATE_METHOD_NAMES.get(b("activate_method")),
        "activate_button": (None if b("activate_button") in (None, 0xFF)
                             else decode_keycode(b("activate_button"))),
        "x_axis_output_mode": _X_AXIS_OUTPUT_MODE_NAMES.get(b("x_axis_output_mode")),
        "curve": {
            "preset": CURVE_PRESET_NAMES.get(b("curve")),
            "points": decode_curve_points(blob, SETTING_IDS["curve"] + STORAGE_BASE + off("curve")),
        },
        "deadzone": {"initial": b("deadzone_initial"), "max": b("deadzone_max")},
        "anti_deadzone": {"initial": b("anti_deadzone_initial"), "max": b("anti_deadzone_max")},
        "invert_roll": invert_roll,
        "invert_y": bool(b("invert_y")),
        "invert_yaw": bool(b("invert_yaw")),
        "sensitivity_scale": b("sensitivity_scale"),
        "output": _OUTPUT_MODE_NAMES.get(b("output")),
        "overlap_area": b("overlap_area"),
        "direction_bindings": directions,
    }


def set_value(session: VendorSession, side: str, setting: str, value: SettingValue, profile: int = 1) -> bytes:
    setting = setting.lower()
    if setting not in SETTING_IDS:
        raise ValueError(f"unknown motion setting {setting!r}")
    offset = _side_offset(side, setting)
    sid = SETTING_IDS[setting] + offset
    prefix = prefix_sticks(profile)

    if setting == "activate_method":
        val = ACTIVATE_METHODS.get(str(value).lower())
        if val is None:
            raise ValueError(f"activate_method must be one of {list(ACTIVATE_METHODS)}")
        payload = prefix + bytes([sid, 0x01, val])
    elif setting == "activate_button":
        payload = prefix + bytes([sid, 0x01, resolve_keycode(value)])
    elif setting == "x_axis_output_mode":
        val = X_AXIS_OUTPUT_MODES.get(str(value).lower())
        if val is None:
            raise ValueError(f"x_axis_output_mode must be one of {list(X_AXIS_OUTPUT_MODES)}")
        payload = prefix + bytes([sid, 0x01, val])
    elif setting == "curve":
        payload = prefix + _curve_preset_payload(sid, value)
    elif setting == "deadzone_initial":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _DEADZONE_INITIAL_SUFFIX_LEN)
        payload = prefix + bytes([sid, _DEADZONE_INITIAL_MARKER, _percent(value)]) + suffix
    elif setting == "deadzone_max":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _DEADZONE_MAX_SUFFIX_LEN)
        payload = prefix + bytes([sid, _DEADZONE_MAX_MARKER, _percent(value)]) + suffix
    elif setting == "anti_deadzone_initial":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _ANTI_DEADZONE_INITIAL_SUFFIX_LEN)
        payload = prefix + bytes([sid, _ANTI_DEADZONE_INITIAL_MARKER, _percent(value)]) + suffix
    elif setting == "anti_deadzone_max":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _ANTI_DEADZONE_MAX_SUFFIX_LEN)
        payload = prefix + bytes([sid, _ANTI_DEADZONE_MAX_MARKER, _percent(value)]) + suffix
    elif setting in ("invert_roll", "invert_y", "invert_yaw"):
        payload = prefix + bytes([sid, 0x01, 0x01 if _bool(value) else 0x00])
    elif setting in ("sensitivity_scale", "overlap_area"):
        payload = prefix + bytes([sid, 0x01, _percent(value)])
    elif setting == "output":
        val = OUTPUT_MODES.get(str(value).lower())
        if val is None:
            raise ValueError(f"output must be one of {list(OUTPUT_MODES)}")
        payload = prefix + bytes([sid, 0x01, val])
    elif setting in _DIRECTION_SETTINGS:
        payload = prefix + bytes([sid, 0x01, resolve_keycode(value)])
    else:
        raise ValueError(f"unhandled setting {setting!r}")

    return session.send_raw(CMD_WRITE, payload)
