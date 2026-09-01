"""Vibrations tab: grip/trigger levels, and trigger force/sync flags.

Same `03 [profile] 00` prefix as Triggers. All settings are simple
single-byte writes: `03 [profile] 00 [SETTING_ID] 01 [VALUE]`. The middle
byte is a plain PROFILE number (1-4), same targeting model as Buttons --
confirmed 2026-07-28, see PROTOCOL.md "Profile scoping" and sticks.py's
module docstring.
"""
from .constants import CMD_WRITE, prefix_triggers_vibration
from .session import VendorSession
from .values import SettingValue

LEVEL_SETTING_IDS = {
    "left_grip": 0x20,
    "right_grip": 0x21,
    "left_trigger": 0x22,
    "right_trigger": 0x23,
}

# The firmware stores whatever byte it's sent (write 47, read back 47 --
# confirmed on hardware), so storage itself is a genuine 0-100 scale, not
# quantized. But felt-testing the actual motors found a hard floor: values
# below 25 produce no perceptible vibration on either grip motor (24 and 25
# were directly compared, repeatably -- 24 silent, 25 clearly felt), and
# 25/50/75/100 are each felt as progressively stronger with no plateau in
# between, which rules out the motor itself being quantized to some coarser
# step count above the floor. GameSir Nexus's own UI only ever offers these
# five values, which independently matches the same conclusion. Restricted
# here to the same five so the CLI, GUI and any state file agree on what a
# "valid" level actually is, rather than accepting 96 values whose only
# audience is a value equal to one of these five. Trigger motors (as
# opposed to grip) were not independently felt-tested, but Nexus applies
# the identical five-value scale to all four settings, so the same
# restriction is applied uniformly here rather than leaving two of the four
# settings on a different, untested rule.
LEVELS = (0, 25, 50, 75, 100)

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


def _level(value: SettingValue) -> int:
    """Coerce to one of LEVELS, or raise -- see that constant's comment for
    why this is five values rather than 0-100 like every other percent-style
    setting in this library."""
    v = int(value)
    if v not in LEVELS:
        raise ValueError(
            f"vibration level must be one of {LEVELS}, got {v} -- "
            "the firmware stores any 0-100 byte faithfully, but only these "
            "five produce distinct felt output; anything else is either "
            "identical to its nearest neighbor or below the motors' "
            "perceptible floor")
    return v


def set_value(session: VendorSession, setting: str, value: SettingValue, profile: int = 1) -> bytes:
    setting = setting.lower()
    prefix = prefix_triggers_vibration(profile)
    if setting in LEVEL_SETTING_IDS:
        sid = LEVEL_SETTING_IDS[setting]
        payload = prefix + bytes([sid, 0x01, _level(value)])
    elif setting in FLAGS_SETTING_IDS:
        sid = FLAGS_SETTING_IDS[setting]
        if isinstance(value, int):
            # Real gap, found 2026-09-01: unlike the string-token path just
            # below (which can only ever produce 0-3 via flags_byte()) and
            # _level()'s own validator above, this accepted any int 0-255
            # unvalidated. Only bits 0-1 (Force/Sync) are documented and
            # confirmed by this module's own docstring -- an out-of-range
            # value sets undefined upper bits on real hardware with
            # unconfirmed effect. pyg7 is a public library meant for direct
            # third-party use (see pyg7/__init__.py), so this path is
            # reachable outside g7ctl/g7ctlc's own callers, which only ever
            # construct the validated string form.
            if not 0 <= value <= 3:
                raise ValueError(f"flags value must be an int 0-3, or 'force,sync' e.g. 'on,off' -- got {value}")
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
