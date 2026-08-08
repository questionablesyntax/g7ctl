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

The 9 shape bytes are `[scale=0x64] [origin] [P1] [P2] [P3]`: a scale byte,
a fixed `00 00` origin corner, and the three draggable interior points as
(x, y) pairs in 0-255 space.

A curve has FIVE handles in Nexus, but only these three live here. The
other two are the endpoints, and they are the Deadzone/Anti-Deadzone
registers -- deadzone initial/max are the endpoints' X coordinates and
anti-deadzone initial/max are their Y coordinates. So `set_value(...,
"curve_points", ...)` below moves the interior of the curve, and the
deadzone/anti-deadzone setters move its ends. See PROTOCOL.md "A curve is
five handles".

Two units are in play, which is a real trap: **interior points are 0-255,
the endpoints are 0-100 percentages.** Confirmed by writing 0x00 and 0xFF
to an interior point and reading both back unchanged (2026-08-08,
Profile 4).

The interpolation drawn through the points is NOT established -- Bezier and
Catmull-Rom both fit the presets. Nothing here needs it; a renderer would.
"""
from collections.abc import Iterable, Sequence
from typing import Union

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


# The three interior points sit at the curve SETTING_ID + these offsets --
# so Left Stick's curve at 0x44 puts them at 0x48/0x4A/0x4C, and every side
# offset (Sticks +0x20, Triggers +0x1C) carries through automatically
# because it is applied to the curve ID before these are added. All six
# addresses hardware-confirmed 2026-08-08 (left stick, right stick, both
# triggers).
CURVE_POINT_OFFSETS = (4, 6, 8)
CURVE_POINT_COUNT = len(CURVE_POINT_OFFSETS)

# Where the points sit inside the 10-byte block, for decoding a blob read:
# [index][scale][origin x2][P1 x2][P2 x2][P3 x2]
CURVE_POINTS_BLOCK_OFFSET = 4


def parse_points(value: Union[str, Sequence]) -> list[tuple[int, int]]:
    """Coerce a curve-points value to [(x, y), (x, y), (x, y)].

    Accepts what the CLI passes (a string "x1,y1,x2,y2,x3,y3") and what the
    GUI/state JSON passes (a nested sequence [[x, y], ...] or a flat one).
    """
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip() != ""]
        flat = [int(p, 0) for p in parts]
    else:
        flat = []
        for item in value:
            if isinstance(item, (list, tuple)):
                flat.extend(int(v) for v in item)
            else:
                flat.append(int(item))
    if len(flat) != CURVE_POINT_COUNT * 2:
        raise ValueError(
            f"curve_points needs {CURVE_POINT_COUNT} (x, y) pairs "
            f"({CURVE_POINT_COUNT * 2} numbers), got {len(flat)}")
    for v in flat:
        # 0-255, NOT 0-100. The endpoints are percentages; these are not.
        if not 0 <= v <= 255:
            raise ValueError(f"curve point coordinate {v} out of range: must be 0-255")
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


def curve_point_payloads(setting_id: int, points: Iterable[tuple[int, int]]) -> list[bytes]:
    """One payload per interior point: [addr] 02 [x] [y].

    Deliberately three separate 2-byte writes rather than one 10-byte write
    of the whole block. Both forms exist on the wire, but this is the one
    that was hardware-verified end to end (write, read back, diff: exactly
    the intended bytes changed and nothing else). The single-write form is
    what the presets use, and rewriting the whole block would also clobber
    the scale and origin bytes for no benefit.
    """
    payloads = []
    for off, (x, y) in zip(CURVE_POINT_OFFSETS, points):
        addr = setting_id + off
        if addr > 0xFF:
            # Right Trigger's third point lands at 0x100 -- past the end of
            # the one-byte SETTING_ID field. Under the register-file model
            # that is page 1, offset 0x00, so it would need a *different
            # prefix* mid-sequence (03 [profile] 01 instead of ...00).
            #
            # That encoding is inferred, never observed: test60 confirmed
            # the Right Trigger's curve preset (0xF8) and second point
            # (0xFE), but nothing has ever written its third. Refusing is
            # deliberate -- guessing an address wrong here does not fail
            # loudly, it writes a byte into someone's persistent config.
            # One capture of dragging that point in Nexus closes it.
            raise ValueError(
                f"curve point address {addr:#05x} crosses the page boundary "
                "(Right Trigger's third point). The encoding for this is "
                "inferred but unverified, so it is refused rather than "
                "guessed -- see PROTOCOL.md 'Editing points'.")
        payloads.append(bytes([addr, 0x02, x, y]))
    return payloads


def decode_curve_points(blob: bytes, storage_offset: int) -> "list[list[int]] | None":
    """Read the three interior points out of a config blob. Returns
    [[x, y], ...] (lists, so it round-trips through JSON), or None if the
    blob is too short to cover them."""
    start = storage_offset + CURVE_POINTS_BLOCK_OFFSET
    end = start + CURVE_POINT_COUNT * 2
    if end > len(blob):
        return None
    chunk = blob[start:end]
    return [[chunk[i], chunk[i + 1]] for i in range(0, len(chunk), 2)]


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
