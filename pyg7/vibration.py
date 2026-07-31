"""Vibrations tab: grip/trigger levels, and trigger force/sync flags.

Same `03 [profile] 00` prefix as Triggers. All settings are simple
single-byte writes: `03 [profile] 00 [SETTING_ID] 01 [VALUE]`. The middle
byte is a plain PROFILE number (1-4), same targeting model as Buttons --
confirmed 2026-07-28, see PROTOCOL.md "Profile scoping" and sticks.py's
module docstring.
"""
from .constants import CMD_WRITE, prefix_triggers_vibration
from .session import VendorSession
from .values import SettingValue, percent as _percent

LEVEL_SETTING_IDS = {
    "left_grip": 0x20,
    "right_grip": 0x21,
    "left_trigger": 0x22,
    "right_trigger": 0x23,
}

# Force+Sync are bit flags on ONE byte per side, not two separate settings:
# bit0=Force, bit1=Sync. Confirmed via the toggle sequence
# 01(Force on)->00(Force off)->02(Sync on)->00(Sync off) -- see PROTOCOL.md
# "Vibration".
FLAGS_SETTING_IDS = {
    "left_trigger_flags": 0x24,
    "right_trigger_flags": 0x25,
}

SETTINGS = set(LEVEL_SETTING_IDS) | set(FLAGS_SETTING_IDS)


def flags_byte(force: bool, sync: bool) -> int:
    return (0x01 if force else 0x00) | (0x02 if sync else 0x00)


def decode_settings(blob: bytes) -> dict:
    """Decode Vibration settings from a profile config blob's DEFAULT-layer
    read (Vibration isn't layer-scoped, so only one read per profile is
    needed -- see state.py's read_state()). Storage offset equals
    SETTING_ID exactly for every setting here -- confirmed 2026-07-27 via
    live write+read-diff on all 6 settings, each landing in exactly one
    profile's blob with the other 3 unaffected -- and confirmed
    2026-07-28 to be genuine per-profile addressing via the write's own
    profile byte (see PROTOCOL.md "Profile scoping"), not just "whichever
    profile happened to be active". Returns a dict shaped like the
    "vibration" section of a state dict."""
    result = {}
    for name, sid in LEVEL_SETTING_IDS.items():
        result[name] = blob[sid] if sid < len(blob) else None
    for flags_name, sid in FLAGS_SETTING_IDS.items():
        side = flags_name.rsplit("_trigger_flags", 1)[0]
        flags = blob[sid] if sid < len(blob) else 0
        result[f"{side}_trigger_force"] = bool(flags & 0x01)
        result[f"{side}_trigger_sync"] = bool(flags & 0x02)
    return result


def set_value(session: VendorSession, setting: str, value: SettingValue, profile: int = 1) -> bytes:
    setting = setting.lower()
    prefix = prefix_triggers_vibration(profile)
    if setting in LEVEL_SETTING_IDS:
        sid = LEVEL_SETTING_IDS[setting]
        payload = prefix + bytes([sid, 0x01, _percent(value)])
    elif setting in FLAGS_SETTING_IDS:
        sid = FLAGS_SETTING_IDS[setting]
        if isinstance(value, int):
            val = value
        else:
            # "force,sync" as two on/off tokens, e.g. "on,off"
            parts = [p.strip().lower() for p in str(value).split(",")]
            if len(parts) != 2:
                raise ValueError("flags value must be an int 0-3, or 'force,sync' e.g. 'on,off'")
            force = parts[0] in ("1", "true", "on", "yes")
            sync = parts[1] in ("1", "true", "on", "yes")
            val = flags_byte(force, sync)
        payload = prefix + bytes([sid, 0x01, val])
    else:
        raise ValueError(f"unknown vibration setting {setting!r}")

    return session.send_raw(CMD_WRITE, payload)
