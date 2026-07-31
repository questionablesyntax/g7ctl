"""Report/polling rate: a per-profile setting with no Left/Right side and
no tab of its own in the app's per-category sense, sharing the same
`03 [profile] 00` prefix as Triggers/Vibration/Sticks' resolution_bits.
Confirmed genuinely per-profile, not a single global device setting -- see
PROTOCOL.md "Profile scoping".

Confirmed 2026-07-28 via 3 independent live GameSir Nexus captures, one
clean `0x3c` write per transition (1000->500, 500->250, 250->1000):
`SETTING_ID = 0x30`, payload
`03 [profile] 00 30 01 [VALUE]`, `VALUE` = 0/1/2 for 250/500/1000 Hz
respectively. Also hardware-confirmed the same day via our own tool's
write+read round trip, and confirmed genuinely per-profile (the middle
prefix byte is a real PROFILE number, not a fixed constant) -- see
PROTOCOL.md "Profile scoping".
"""
from typing import Union

from .constants import CMD_WRITE, prefix_triggers_vibration
from .session import VendorSession

SETTING_ID = 0x30

RATES_HZ = {250: 0x00, 500: 0x01, 1000: 0x02}
_RATE_NAMES = {v: k for k, v in RATES_HZ.items()}


def decode_settings(blob: bytes) -> dict:
    """Decode the report rate from a profile config blob's DEFAULT-layer
    read -- lives at the same absolute offset as SETTING_ID (the general
    `03 [profile] 00`-prefix formula every other setting in this prefix
    follows -- see PROTOCOL.md "Sticks/Triggers/Vibration storage
    offsets"), hardware-confirmed 2026-07-28."""
    val = blob[SETTING_ID] if SETTING_ID < len(blob) else None
    return {"report_rate_hz": _RATE_NAMES.get(val)}


def set_value(session: VendorSession, hz: Union[int, str], profile: int = 1) -> bytes:
    hz = int(hz)
    if hz not in RATES_HZ:
        raise ValueError(f"report rate must be one of {sorted(RATES_HZ)}, got {hz}")
    payload = prefix_triggers_vibration(profile) + bytes([SETTING_ID, 0x01, RATES_HZ[hz]])
    return session.send_raw(CMD_WRITE, payload)
