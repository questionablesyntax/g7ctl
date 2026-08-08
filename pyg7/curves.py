"""Curve Adjustment preset data, shared byte-for-byte between Sticks (SETTING_ID
0x44 for Left Stick) and Triggers (0xDC for Left Trigger) -- see PROTOCOL.md
"Curve preset payload".

Standard/Concave/S-Curve carry real curve-shape data (the "long form", 0x0A
after the setting ID); Custom is just a mode-select flag (the "short form",
0x01) since Custom has no fixed preset curve of its own.

That byte is a LENGTH, not a format marker: 0x0A = 10 = the preset index
plus its 9 shape bytes, and 0x01 = 1 = the index alone. Same convention as
every other write in this protocol -- see PROTOCOL.md "Config writes are
addressed writes into a register file".

The 9 shape bytes are `[scale=0x64] [P0] [P1] [P2] [P3]`, four (x, y)
control points in 0-255 space with P0 always (0, 0). Only preset selection
is implemented here; individual control-point editing is decoded but not
implemented (see PROTOCOL.md "Editing a single control point"), and the
interpolation used to draw a curve through the points is not established.
"""

CURVE_PRESET_INDEX = {"standard": 0x00, "concave": 0x01, "s_curve": 0x02}

# Decode direction: stored index -> preset name. Includes 0x03 for Custom,
# which has no entry in CURVE_PRESET_INDEX above because it carries no curve
# data to write -- it's only ever a mode-select flag (see the module
# docstring), but it does read back from the blob like any other preset, so
# a decoder that omitted it would report Custom as None.
#
# Sticks and Triggers each used to build and patch their own private copy of
# this table with identical code; it's shared here so the 0x03 special case
# is stated once.
CURVE_PRESET_NAMES = {v: k for k, v in CURVE_PRESET_INDEX.items()}
CURVE_PRESET_NAMES[0x03] = "custom"

# Every preset name a payload builder or validator will accept, Custom
# included -- state.py used to assemble this itself.
CURVE_PRESETS = frozenset(CURVE_PRESET_INDEX) | {"custom"}

# Trailing curve-shape bytes for the "long form", identical across Sticks
# and Triggers and across Left/Right (only the SETTING_ID differs). Taken
# directly from confirmed live-capture payloads (Sticks 0x44):
#   Standard: 03 01 01 44 0A 00 64 00 00 28 29 80 80 D7 D6
#   Concave:  03 01 01 44 0A 01 64 00 00 5E 17 B0 4F E8 A1
#   S-Curve:  03 01 01 44 0A 02 64 00 00 28 4C 80 80 D7 B2
_CURVE_SHAPE_DATA = {
    0x00: bytes.fromhex("64000028298080d7d6"),
    0x01: bytes.fromhex("6400005e17b04fe8a1"),
    0x02: bytes.fromhex("64000028 4c 80 80 d7 b2".replace(" ", "")),
}


def curve_preset_payload(setting_id: int, preset: str) -> bytes:
    """Build the payload (after the fixed category prefix) for selecting a
    curve preset: [SETTING_ID] [LEN] [index] [shape data or nothing], where
    LEN counts everything after it (10 for a preset, 1 for Custom)."""
    preset = preset.lower()
    if preset == "custom":
        return bytes([setting_id, 0x01, 0x03, 0x00])
    if preset not in CURVE_PRESET_INDEX:
        raise ValueError(f"unknown curve preset {preset!r}, expected one of {list(CURVE_PRESET_INDEX) + ['custom']}")
    idx = CURVE_PRESET_INDEX[preset]
    return bytes([setting_id, 0x0A, idx]) + _CURVE_SHAPE_DATA[idx]
