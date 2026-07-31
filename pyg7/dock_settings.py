"""Dock settings: LED Brightness and Auto On/Off, found in Nexus's
top-level "Settings" section (not a per-category tab like Buttons/Sticks/
Triggers/Vibration). Genuinely global/device-wide, not per-profile --
confirmed 2026-07-28: the write prefix's middle byte stays a fixed `0x20`
regardless of which profile is active, unlike every other category this
project has mapped (see `constants.py`'s `PREFIX_DOCK`).

Confirmed via live GameSir Nexus capture (cycling brightness 100%->0%->
25%->50%->75%->100%, and toggling Auto On/Off off then back on) plus a
before/after read-diff to pin down the storage offset:

- **Dock LED Brightness** (`SETTING_ID = 0xF9`): plain `[id] 01 [percent]`,
  value is the literal 0-100 percentage (Nexus's UI only exposes 5 discrete
  steps -- 0/25/50/75/100 -- but the wire encoding is a normal percent byte
  like every other level setting in this project, not a small enum).
- **Auto On/Off** (`SETTING_ID = 0xF6`): plain `[id] 01 [0/1]` boolean.

Storage offset = `SETTING_ID + DOCK_STORAGE_BASE` (`0x100`, same base
Sticks' `03 [profile] 01` prefix uses) within a >480-byte blob read via
`CMD_READ` category `0x20` -- a different, separate blob from the 4
per-profile 480-byte ones, not an extension of any of them.
"""
from typing import Union

from .constants import CMD_WRITE, DOCK_READ_CATEGORY, DOCK_STORAGE_BASE, PREFIX_DOCK
from .session import VendorSession
from .values import SettingValue, boolean as _bool, percent as _percent

BRIGHTNESS_SETTING_ID = 0xF9
AUTO_ON_OFF_SETTING_ID = 0xF6

SETTINGS = {"brightness", "auto_on_off"}

# Long enough to cover both settings' storage offsets (0x1F6/0x1F9) plus
# margin -- read_blob() chunks this automatically, same as the per-profile
# blob reads elsewhere.
BLOB_LENGTH = 511


def decode_settings(blob: bytes) -> dict:
    """Decode both settings from a `read_blob(DOCK_READ_CATEGORY, ...)`
    read. Returns a dict with "dock_led_brightness" (0-100 or None) and
    "dock_auto_on_off" (bool or None)."""
    b_off = BRIGHTNESS_SETTING_ID + DOCK_STORAGE_BASE
    a_off = AUTO_ON_OFF_SETTING_ID + DOCK_STORAGE_BASE
    brightness = blob[b_off] if b_off < len(blob) else None
    auto = blob[a_off] if a_off < len(blob) else None
    return {
        "dock_led_brightness": brightness,
        "dock_auto_on_off": bool(auto) if auto is not None else None,
    }


def set_brightness(session: VendorSession, percent: Union[int, str]) -> bytes:
    payload = PREFIX_DOCK + bytes([BRIGHTNESS_SETTING_ID, 0x01, _percent(percent)])
    return session.send_raw(CMD_WRITE, payload)


def set_auto_on_off(session: VendorSession, enabled: SettingValue) -> bytes:
    # Routes through values.boolean() (`_bool`), not raw truthiness -- see
    # dpad_options.py's identical fix for why: a non-bool `enabled` (e.g.
    # the string "off") is truthy in plain Python and silently wrote ON.
    payload = PREFIX_DOCK + bytes([AUTO_ON_OFF_SETTING_ID, 0x01, 0x01 if _bool(enabled) else 0x00])
    return session.send_raw(CMD_WRITE, payload)


def set_value(session: VendorSession, setting: str, value: SettingValue) -> bytes:
    """Dispatch by name -- matches sticks.py/triggers.py/vibration.py/
    report_rate.py's shape. No `profile=` parameter,
    unlike every sibling module's set_value(): dock settings are genuinely
    device-global (see module docstring), not per-profile."""
    setting = setting.lower()
    if setting == "brightness":
        return set_brightness(session, value)
    if setting == "auto_on_off":
        return set_auto_on_off(session, value)
    raise ValueError(f"unknown dock setting {setting!r}, expected one of {sorted(SETTINGS)}")
