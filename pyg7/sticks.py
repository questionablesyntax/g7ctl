"""Sticks tab: Left/Right Stick deadzone/curve/trajectory/advanced-mapping.

Category prefix `03 [profile] 01` for Left Stick (Resolution/Bit is the one
exception, using `03 [profile] 00` -- see PROTOCOL.md "Sticks").
Right Stick reuses the exact same shape with every SETTING_ID shifted by a
fixed +0x20 (confirmed on 2 settings, treated as a general rule -- see
PROTOCOL.md "Sticks"). The prefix's middle byte is a plain PROFILE
number (1-4), same targeting model as Buttons -- confirmed 2026-07-28 via
live GameSir Nexus capture and a direct hardware test (see PROTOCOL.md
"Profile scoping"); an earlier single test had wrongly suggested these
writes carry no profile targeting at all, which stayed unverified for a
while, but that read of the evidence didn't hold up.
"""
from .buttons import decode_keycode, resolve_keycode
from .constants import CMD_WRITE, RIGHT_STICK_OFFSET, prefix_sticks, prefix_triggers_vibration
from .curves import (
    CURVE_PRESET_NAMES,
    curve_preset_payload,
    decode_curve_points,
    parse_points,
    write_curve_points,
)
from .session import VendorSession
from .values import SettingValue, side_offset
from .values import boolean as _bool
from .values import percent as _percent

SETTING_IDS = {
    "trajectory": 0x3D,
    "curve": 0x44,
    # The curve's three interior control points. Shares the curve's own
    # SETTING_ID because the points are addressed relative to it (+4/+6/+8)
    # -- see curves.CURVE_POINT_OFFSETS. The side offset applies once, to
    # the curve ID, and the points follow.
    "curve_points": 0x44,
    "deadzone_initial": 0x3F,
    "deadzone_max": 0x40,
    "anti_deadzone_initial": 0x41,
    "anti_deadzone_max": 0x42,
    "resolution_bits": 0x32,   # uses the Triggers/Vibration-shaped prefix, see set_value
    "output_mode": 0x55,
    "invert_x": 0x51,
    "invert_y": 0x52,
    "sensitivity": 0x53,
    "dpi": 0x54,               # Simulate Mouse output mode only
    "overlap_area": 0x56,      # Directional Buttons output mode only
    "direction_bindings": 0x57,  # Directional Buttons output mode only, bulk write
}
SETTINGS = set(SETTING_IDS)

OUTPUT_MODES = {"left_stick": 0x01, "right_stick": 0x02, "directional": 0x03, "mouse": 0x04}
_OUTPUT_MODE_NAMES = {v: k for k, v in OUTPUT_MODES.items()}

# Every Sticks setting except resolution_bits stores its "value" byte (the
# 3rd byte of its own write payload, right after [SETTING_ID, marker]) at
# SETTING_ID + STORAGE_BASE in the blob -- confirmed 2026-07-27 via live
# write+read-diff on every setting here, spanning both single-byte settings
# and the 6-byte curve-shape/5-byte direction_bindings ranges. The `03 01 01`
# prefix's settings appear to address into their own region of the blob
# starting at this base, distinct from the `03 01 00` prefix's settings
# (Triggers/Vibration/resolution_bits), which address directly from blob
# offset 0 -- see PROTOCOL.md "Sticks/Triggers/Vibration storage offsets".
# resolution_bits uses the OTHER prefix (03 01 00, see set_value below), so
# it does NOT get this base added -- handled as a special case in
# decode_settings().
STORAGE_BASE = 0x100

# Long-form Deadzone/Anti-Deadzone templates. The byte right after the
# setting ID is a LENGTH -- how many bytes follow it -- not a format/type
# marker. It was read as an inconsequential marker for a long time because
# it was seen varying across writes for the same setting; what was actually
# varying is how much trailing data Nexus batched in, which is a length
# doing its job. See PROTOCOL.md "Config writes are addressed writes into a
# register file". The constants below still pair one confirmed-good length
# with a matching suffix length, so the pairing must stay consistent.
#
# The trailing suffix bytes are NOT sent verbatim: see
# VendorSession.read_live_suffix(), which reads the live span instead. These
# constants now only supply the required suffix LENGTH (a fixed, previously-
# confirmed-good payload size), extracted from the stored live USB
# captures for exactness, not from memory.
_DEADZONE_INITIAL_MARKER = 0x0E
# Real bug, found 2026-09-01 (second bug-hunt pass): this hex string used
# to be "640064010064000026298080d900" -- one byte too long for its own
# marker (marker must equal 1 + len(suffix), the same invariant
# triggers.py enforces with an explicit assert and motion.py states
# outright). The leading "64" was the write's own VALUE byte, accidentally
# captured as part of the suffix -- confirmed by comparing shapes: with it
# dropped, this string's own leading bytes exactly match
# _DEADZONE_MAX_SUFFIX_LEN's below ("0064010064000...", differing only in
# the setting-specific tail), the same relationship every other adjacent
# pair in this family already has.
_DEADZONE_INITIAL_SUFFIX_LEN = len(bytes.fromhex("0064010064000026298080d900"))
_DEADZONE_MAX_MARKER = 0x0D
# Same bug, same fix: leading "00" trimmed -- was "0064010064000029298080d600".
_DEADZONE_MAX_SUFFIX_LEN = len(bytes.fromhex("64010064000029298080d600"))
_ANTI_DEADZONE_INITIAL_MARKER = 0x0D
_ANTI_DEADZONE_INITIAL_SUFFIX_LEN = len(bytes.fromhex("64010064000028278080d7d8"))
_ANTI_DEADZONE_MAX_MARKER = 0x0C
_ANTI_DEADZONE_MAX_SUFFIX_LEN = len(bytes.fromhex("010064000028278081d7d8"))


def _side_offset(side: str) -> int:
    return side_offset(side, RIGHT_STICK_OFFSET)


def decode_settings(blob: bytes, side: str = "left") -> dict:
    """Decode one side's Sticks settings from a profile config blob's
    DEFAULT-layer read (Sticks isn't layer-scoped, so only one read per
    profile is needed -- see state.py's read_state()). See STORAGE_BASE
    above for the offset formula; confirmed 2026-07-27 via live
    write+read-diff on every setting, including the Right Stick +0x20 rule
    already documented for writes. Returns a dict shaped like one side of
    the "sticks" section of a state dict."""
    off = _side_offset(side)

    def b(setting):
        i = SETTING_IDS[setting] + STORAGE_BASE + off
        return blob[i] if i < len(blob) else None

    res_off = SETTING_IDS["resolution_bits"] + off  # uses the OTHER prefix's address space -- see STORAGE_BASE note
    res_val = blob[res_off] if res_off < len(blob) else None

    db_off = SETTING_IDS["direction_bindings"] + STORAGE_BASE + off
    db_bytes = blob[db_off:db_off + 5]
    direction_bindings = None
    if len(db_bytes) == 5:
        zones = ("up", "down", "left", "right", "ring")
        direction_bindings = {
            zone: (None if code == 0xFF else decode_keycode(code))
            for zone, code in zip(zones, db_bytes)
        }

    return {
        "trajectory": "raw" if b("trajectory") == 0x01 else "circle",
        "curve": {
            "preset": CURVE_PRESET_NAMES.get(b("curve")),
            "points": decode_curve_points(blob, SETTING_IDS["curve"] + STORAGE_BASE + off),
        },
        "deadzone": {"initial": b("deadzone_initial"), "max": b("deadzone_max")},
        "anti_deadzone": {"initial": b("anti_deadzone_initial"), "max": b("anti_deadzone_max")},
        "resolution_bits": (12 - res_val) if res_val is not None else None,
        "advanced_mapping": {
            "output_mode": _OUTPUT_MODE_NAMES.get(b("output_mode")),
            "invert_x": bool(b("invert_x")),
            "invert_y": bool(b("invert_y")),
            "sensitivity": b("sensitivity"),
            "overlap_area": b("overlap_area"),
            "direction_bindings": direction_bindings,
            "dpi": b("dpi"),
        },
    }


def set_value(session: VendorSession, side: str, setting: str, value: SettingValue, profile: int = 1) -> bytes:
    setting = setting.lower()
    if setting not in SETTING_IDS:
        raise ValueError(f"unknown stick setting {setting!r}")
    offset = _side_offset(side)
    sid = SETTING_IDS[setting] + offset
    prefix = prefix_sticks(profile)

    if setting == "trajectory":
        val = 0x01 if str(value).lower() == "raw" else 0x00
        payload = prefix + bytes([sid, 0x01, val])
    elif setting == "curve":
        payload = prefix + curve_preset_payload(sid, value)
    elif setting == "curve_points":
        # Three writes, heartbeat-paced -- see curves.write_curve_points().
        # Returns early because this branch sends its own packets rather
        # than falling through to the single send_raw() below.
        return write_curve_points(session, prefix, sid, parse_points(value))
    elif setting == "deadzone_initial":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _DEADZONE_INITIAL_SUFFIX_LEN)
        assert len(suffix) + 1 == _DEADZONE_INITIAL_MARKER, "suffix length drifted from the captured template"
        payload = prefix + bytes([sid, _DEADZONE_INITIAL_MARKER, _percent(value)]) + suffix
    elif setting == "deadzone_max":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _DEADZONE_MAX_SUFFIX_LEN)
        assert len(suffix) + 1 == _DEADZONE_MAX_MARKER, "suffix length drifted from the captured template"
        payload = prefix + bytes([sid, _DEADZONE_MAX_MARKER, _percent(value)]) + suffix
    elif setting == "anti_deadzone_initial":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _ANTI_DEADZONE_INITIAL_SUFFIX_LEN)
        assert len(suffix) + 1 == _ANTI_DEADZONE_INITIAL_MARKER, "suffix length drifted from the captured template"
        payload = prefix + bytes([sid, _ANTI_DEADZONE_INITIAL_MARKER, _percent(value)]) + suffix
    elif setting == "anti_deadzone_max":
        suffix = session.read_live_suffix(profile, sid + STORAGE_BASE, _ANTI_DEADZONE_MAX_SUFFIX_LEN)
        assert len(suffix) + 1 == _ANTI_DEADZONE_MAX_MARKER, "suffix length drifted from the captured template"
        payload = prefix + bytes([sid, _ANTI_DEADZONE_MAX_MARKER, _percent(value)]) + suffix
    elif setting == "resolution_bits":
        bits = int(value)
        if not 8 <= bits <= 12:
            raise ValueError("resolution_bits must be 8-12")
        # NOTE: uses the Triggers/Vibration-shaped `03 [profile] 00` prefix,
        # not Sticks' usual `03 [profile] 01` -- see PROTOCOL.md
        # "Sticks". value = 12 - bits.
        payload = prefix_triggers_vibration(profile) + bytes([sid, 0x01, 12 - bits])
    elif setting == "output_mode":
        val = OUTPUT_MODES.get(str(value).lower())
        if val is None:
            raise ValueError(f"output_mode must be one of {list(OUTPUT_MODES)}")
        payload = prefix + bytes([sid, 0x01, val])
    elif setting in ("invert_x", "invert_y"):
        payload = prefix + bytes([sid, 0x01, 0x01 if _bool(value) else 0x00])
    elif setting in ("sensitivity", "dpi", "overlap_area"):
        payload = prefix + bytes([sid, 0x01, _percent(value)])
    elif setting == "direction_bindings":
        # value: "up,down,left,right,ring" keycode names, e.g. "w,s,a,d,shift"
        parts = [p.strip() for p in str(value).split(",")]
        if len(parts) != 5:
            raise ValueError("direction_bindings value must be 'up,down,left,right,ring'")
        keycodes = [resolve_keycode(p) for p in parts]
        payload = prefix + bytes([sid, 0x05]) + bytes(keycodes)
    else:
        raise ValueError(f"unhandled setting {setting!r}")

    return session.send_raw(CMD_WRITE, payload)
