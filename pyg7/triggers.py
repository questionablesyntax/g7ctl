"""Triggers tab: Left/Right Trigger hair-trigger mode/deadzone/curve.

Category prefix `03 [profile] 00` (different from Sticks' `03 [profile] 01`,
though coincidentally the same 3 leading bytes as the Buttons default-layer
write -- unrelated, there's no "layer" concept here). Right Trigger reuses
the exact same shape with every SETTING_ID shifted by a fixed +0x1C (a
DIFFERENT offset than Sticks' +0x20 -- confirmed each category has its own
offset, not a universal constant -- see PROTOCOL.md "Triggers").
The prefix's middle byte is a plain PROFILE number (1-4), same targeting
model as Buttons -- confirmed 2026-07-28, see PROTOCOL.md "Profile
scoping" and sticks.py's module docstring (an
earlier single test had wrongly suggested no profile targeting existed
here).
"""
from .constants import CMD_WRITE, RIGHT_TRIGGER_OFFSET, prefix_triggers_vibration
from .curves import CURVE_PRESET_NAMES, curve_preset_payload
from .session import VendorSession
from .values import SettingValue, percent as _percent, side_offset

SETTING_IDS = {
    "hair_trigger_mode": 0xD8,
    "deadzone_initial": 0xCF,
    "deadzone_max": 0xD0,
    "anti_deadzone_initial": 0xD1,
    "anti_deadzone_max": 0xD2,
    "curve": 0xDC,
}
SETTINGS = set(SETTING_IDS)

HAIR_TRIGGER_MODES = {"off": 0x00, "adaptive": 0x81, "fixed": 0x82}
_HAIR_TRIGGER_MODE_NAMES = {v: k for k, v in HAIR_TRIGGER_MODES.items()}

# Triggers' `03 01 00` prefix addresses directly into the blob from offset 0
# (no per-side base beyond RIGHT_TRIGGER_OFFSET) -- see PROTOCOL.md "Sticks/
# Triggers/Vibration storage offsets" for the general offset-formula table.
STORAGE_BASE = 0x00

# Long-form Deadzone/Anti-Deadzone templates, re-extracted directly from the
# stored live USB captures, same approach as
# sticks.py -- the marker byte appears inconsequential (varied 0x14/0x15/0x16
# across real samples for the same setting), value byte is what matters.
#
# The trailing suffix bytes are NOT sent verbatim: see
# VendorSession.read_live_suffix(), which reads the live span instead. These
# constants now only supply the required suffix LENGTH.
_DEADZONE_INITIAL_MARKER = 0x14
_DEADZONE_INITIAL_SUFFIX_LEN = len(bytes.fromhex("5f00640113000000000a5a0100640000282981"))
_DEADZONE_MAX_MARKER = 0x15
_DEADZONE_MAX_SUFFIX_LEN = len(bytes.fromhex("00640113000000000a5a01006400002a298080d4"))
_ANTI_DEADZONE_INITIAL_MARKER = 0x15
_ANTI_DEADZONE_INITIAL_SUFFIX_LEN = len(bytes.fromhex("640113000000000a5a0100640000281c808ed7e3"))
_ANTI_DEADZONE_MAX_MARKER = 0x14
_ANTI_DEADZONE_MAX_SUFFIX_LEN = len(bytes.fromhex("0113000000000a5a010064000028338080d7cc"))


def _side_offset(side: str) -> int:
    return side_offset(side, RIGHT_TRIGGER_OFFSET)


def decode_settings(blob: bytes, side: str = "left") -> dict:
    """Decode one side's Triggers settings from a profile config blob's
    DEFAULT-layer read (Triggers isn't layer-scoped, so only one read per
    profile is needed -- see state.py's read_state()). Storage offset
    equals SETTING_ID + _side_offset(side) exactly -- the `03 01 00` prefix
    addresses directly into the blob starting at offset 0, same as
    Vibration's settings (which share this prefix) -- confirmed 2026-07-27
    via live write+read-diff on every setting here, including the Right
    Trigger +0x1C rule already documented for writes. Returns a dict shaped
    like one side of the "triggers" section of a state dict."""
    off = _side_offset(side)

    def b(setting):
        i = SETTING_IDS[setting] + off
        return blob[i] if i < len(blob) else None

    return {
        "hair_trigger_mode": _HAIR_TRIGGER_MODE_NAMES.get(b("hair_trigger_mode")),
        "deadzone": {"initial": b("deadzone_initial"), "max": b("deadzone_max")},
        "anti_deadzone": {"initial": b("anti_deadzone_initial"), "max": b("anti_deadzone_max")},
        "curve": {"preset": CURVE_PRESET_NAMES.get(b("curve"))},
    }


def set_value(session: VendorSession, side: str, setting: str, value: SettingValue, profile: int = 1) -> bytes:
    setting = setting.lower()
    if setting not in SETTING_IDS:
        raise ValueError(f"unknown trigger setting {setting!r}")
    offset = _side_offset(side)
    sid = SETTING_IDS[setting] + offset
    prefix = prefix_triggers_vibration(profile)

    if setting == "hair_trigger_mode":
        val = HAIR_TRIGGER_MODES.get(str(value).lower())
        if val is None:
            raise ValueError(f"hair_trigger_mode must be one of {list(HAIR_TRIGGER_MODES)}")
        payload = prefix + bytes([sid, 0x01, val])
    elif setting == "curve":
        payload = prefix + curve_preset_payload(sid, value)
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
    else:
        raise ValueError(f"unhandled setting {setting!r}")

    return session.send_raw(CMD_WRITE, payload)
