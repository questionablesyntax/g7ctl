"""D-pad-related options shown on Nexus's Buttons tab, below the button
diagram: "Swap Left Stick and D-pad" and "D-Pad Diagonal Lock". Distinct
from actual button remapping -- two simple per-profile toggles under the
same `03 [profile] 00` prefix as Triggers/Vibration/Report Rate.

Confirmed 2026-07-28 via live GameSir Nexus capture + before/after
read-diff (toggle one setting, diff the full 480-byte blob):

- **D-Pad Diagonal Lock** (`SETTING_ID = 0x2D`): simple `[id] 01 [0/1]`
  boolean, same shape as every other simple flag in this prefix family
  (`invert_x`, etc.) -- hardware-confirmed both read and write.
- **Swap Left Stick and D-pad** (`SETTING_ID = 0x2B`): a "long form" write.
  Decoded byte-for-byte from a live USB capture (2026-07-28) rather
  than inferred: `[0x2B] [0x37] [val_2B] [val_2C] [53-byte suffix]`. `0x37`
  (55) is the byte LENGTH of everything after it, not a type/format marker
  like Sticks/Triggers' deadzone writes use -- `4 (header) + 3 (prefix) + 1
  (SETTING_ID) + 1 (length byte) + 55 = 64`, exactly one packet. The
  before/after blob diff showed only registers `0x2B` and `0x2C` actually
  change (both `0x00`->`0x01` in the one captured toggle), confirming
  `val_2B`/`val_2C` are the two leading bytes of that 55-byte span and the
  remaining 53 bytes are collateral storage this write's payload happens to
  carry along -- the same "long form write spans registers it doesn't
  conceptually own" shape as the Deadzone/Anti-deadzone bug. Fixed the same way: `VendorSession.read_live_suffix()` reads the
  live 53-byte span immediately before building the payload instead of
  trusting a value captured once, so whatever else lives in that span
  (D-Pad Diagonal Lock's own byte at `0x2D` sits right inside it) gets
  replayed unchanged rather than stomped. Only the ON direction was ever
  captured -- OFF (`val_2B`/`val_2C` = `0x00`) is inferred by the same
  boolean convention every other flag in this protocol uses.
  **Hardware-verified 2026-07-29**: a full-blob diff of a real ON then OFF
  write showed exactly the two intended bytes changing each time, with the
  OFF-state blob coming back byte-identical to the pre-write baseline.
"""

from .constants import CMD_WRITE, prefix_triggers_vibration
from .session import VendorSession
from .values import SettingValue
from .values import boolean as _bool

DIAGONAL_LOCK_SETTING_ID = 0x2D
SWAP_STICK_DPAD_SETTING_ID = 0x2B

# Named to match state.py's own field names ("dpad_diagonal_lock",
# "swap_stick_dpad") minus the "dpad_"/redundant prefix, since the CLI's
# generic dpad-set/dock-set subcommands (see g7ctl/main.py) expose
# these names directly as argparse choices.
SETTINGS = {"diagonal_lock", "swap_stick_dpad"}

# Length byte, not a format marker -- see module docstring. 4 (header) +
# 3 (prefix) + 1 (SETTING_ID) + 1 (this byte) + 0x37 = 64, exactly one packet.
_SWAP_STICK_DPAD_LEN = 0x37

# The 53 bytes following [val_2B, val_2C], extracted from the same capture
# for exactness (not from memory) -- only its LENGTH is used; the actual
# bytes sent are read live via VendorSession.read_live_suffix(), never this
# stale capture, precisely to avoid the collateral-corruption class this
# same live-suffix read fixed for Sticks/Triggers deadzone -- see
# PROTOCOL.md "Sticks" and VendorSession.read_live_suffix().
_SWAP_STICK_DPAD_SUFFIX_LEN = len(bytes.fromhex(
    "0000000200000000000000000000000000000000000101000000000001020000000000010300000000000104000000000001050000"
))


# Both setters route through values.boolean() (`_bool`) rather than raw
# Python truthiness -- `0x01 if enabled else 0x00` on a non-bool `enabled`
# silently wrote ON for any non-empty string, including the CLI's own "off"
# convention. Matches sticks.py/vibration.py, which already did this right.


def set_diagonal_lock(session: VendorSession, enabled: SettingValue, profile: int = 1) -> bytes:
    payload = prefix_triggers_vibration(profile) + bytes([DIAGONAL_LOCK_SETTING_ID, 0x01, 0x01 if _bool(enabled) else 0x00])
    return session.send_raw(CMD_WRITE, payload)


def set_swap_stick_dpad(session: VendorSession, enabled: SettingValue, profile: int = 1) -> bytes:
    """Set "Swap Left Stick and D-pad". See module docstring for the write
    shape and why the trailing 53 bytes are read live rather than sent from
    a fixed template."""
    val = 0x01 if _bool(enabled) else 0x00
    suffix = session.read_live_suffix(profile, SWAP_STICK_DPAD_SETTING_ID + 1, _SWAP_STICK_DPAD_SUFFIX_LEN)
    payload = (prefix_triggers_vibration(profile)
               + bytes([SWAP_STICK_DPAD_SETTING_ID, _SWAP_STICK_DPAD_LEN, val, val])
               + suffix)
    return session.send_raw(CMD_WRITE, payload)


def set_value(session: VendorSession, setting: str, value: SettingValue, profile: int = 1) -> bytes:
    """Dispatch by name -- matches sticks.py/triggers.py/vibration.py/
    report_rate.py's shape (this module used to be the odd
    one out, one bespoke function per setting with no common entry point,
    which is why the CLI needed two bespoke subcommands instead of one
    generic `dpad-set <setting> <value>` the way stick-set/trigger-set/
    vibration-set already work). The two settings stay implemented as
    their own functions above -- `set_swap_stick_dpad()`'s live-suffix read
    is real, setting-specific behavior, not boilerplate worth inlining --
    this just gives them a shared name-based front door."""
    setting = setting.lower()
    if setting == "diagonal_lock":
        return set_diagonal_lock(session, value, profile=profile)
    if setting == "swap_stick_dpad":
        return set_swap_stick_dpad(session, value, profile=profile)
    raise ValueError(f"unknown dpad option {setting!r}, expected one of {sorted(SETTINGS)}")


def decode_settings(blob: bytes) -> dict:
    """Decode both settings from a profile config blob's DEFAULT-layer
    read (neither is layer-scoped). Returns a dict with
    "swap_stick_dpad"/"dpad_diagonal_lock", both bool or None."""
    diag = blob[DIAGONAL_LOCK_SETTING_ID] if DIAGONAL_LOCK_SETTING_ID < len(blob) else None
    swap = blob[SWAP_STICK_DPAD_SETTING_ID] if SWAP_STICK_DPAD_SETTING_ID < len(blob) else None
    return {
        "dpad_diagonal_lock": bool(diag) if diag is not None else None,
        "swap_stick_dpad": bool(swap) if swap is not None else None,
    }
