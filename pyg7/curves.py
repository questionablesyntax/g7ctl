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
import time
from collections.abc import Iterable, Sequence
from typing import Optional, Union

from .constants import CMD_WRITE

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

# The scale byte (block offset 1) is 0x64 on every configured curve and 0x00
# where the block has never been written -- Profiles 3 and 4 on the
# development controller read `00 00 00 00 ...` across the whole block.
#
# So it doubles as a "configured" marker, and decoding an unwritten block
# yields three points at (0,0) rather than None unless something checks it.
# That matters twice over: three handles stacked on the origin look like a
# rendering bug, and writing them back would store a degenerate curve where
# the firmware previously had nothing. Same convention this protocol uses
# for unconfigured button slots and LT/RT keycodes -- an empty record means
# "never configured", not "configured to zero".
CURVE_SCALE_CONFIGURED = 0x64

# Preset index meaning "not one of the named presets". Selecting it is what
# makes a curve's own control points the active shape.
CURVE_CUSTOM_INDEX = 0x03


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


def curve_point_payloads(setting_id: int, points: Iterable[tuple[int, int]],
                          page: int = 0) -> list[tuple[int, bytes]]:
    """One (page, payload) per interior point: [addr] 02 [x] [y].

    Deliberately three separate 2-byte writes rather than one 10-byte write
    of the whole block. Both forms exist on the wire, but this is the one
    that was hardware-verified end to end (write, read back, diff: exactly
    the intended bytes changed and nothing else). The single-write form is
    what the presets use, and rewriting the whole block would also clobber
    the scale and origin bytes for no benefit.
    """
    out = []
    for off, (x, y) in zip(CURVE_POINT_OFFSETS, points):
        addr = (page << 8) + setting_id + off
        # Right Trigger's third point lands at absolute 0x100 -- past the end
        # of the one-byte SETTING_ID field, so it carries into the next page
        # and the prefix changes mid-sequence. Confirmed on the wire
        # 2026-08-08 (test62): dragging it emitted `03 01 01 00 02 e4 82`,
        # i.e. page 1 offset 0x00, exactly as the register-file model
        # predicted. Note a *trigger* write then uses the same prefix bytes
        # as a *stick* write, which is the clearest demonstration that the
        # "category prefix" is a page number and not a category.
        out.append(((addr >> 8) & 0xFF, bytes([addr & 0xFF, 0x02, x, y])))
    return out


# Pacing between the three point writes. Every other setting in this
# library is ONE write, so its caller (write_state, the CLI's
# _wrapped_write) supplies the heartbeats around it. Curve points are the
# first multi-write setting, and firing all three back-to-back does not
# work: hardware, 2026-08-08, the third write was silently discarded every
# time while the first two landed. The firmware drops writes that are not
# heartbeat-wrapped -- documented since the very first captures -- so a
# multi-write setting has to pace itself.
CURVE_POINT_WRITE_INTERVAL = 0.3


def curve_block_payload(setting_id: int, points: Iterable[tuple[int, int]],
                         preset_index: int = CURVE_CUSTOM_INDEX) -> bytes:
    """The whole 10-byte curve block in one write:

        [SETTING_ID] 0A [index] [scale] [origin x2] [P1] [P2] [P3]

    Same shape the presets use (`curve_preset_payload()` with a named
    preset), which is why the firmware is known to accept it.

    This exists because writing only the points leaves the block
    half-initialised. The scale byte marks a block as written (see
    CURVE_SCALE_CONFIGURED) and a points-only write never sets it, so on a
    profile whose curve was never configured the points land correctly and
    then decode as None -- the tool writing a curve it cannot read back.
    Confirmed on hardware 2026-08-08, Profile 4: index and all three points
    stored, scale still 0x00, `decode_settings()` reporting points=None.
    """
    flat = []
    for x, y in points:
        flat += [x, y]
    return bytes([setting_id, 0x0A, preset_index, CURVE_SCALE_CONFIGURED, 0x00, 0x00]) + bytes(flat)


def write_curve_points(session, prefix: bytes, setting_id: int,
                       points: Iterable[tuple[int, int]],
                       interval: Optional[float] = None,
                       whole_block: bool = True) -> bytes:
    """Write a curve's three interior points, heartbeat-paced.

    `whole_block` (the default) sends one 10-byte write that also sets the
    preset index, scale and origin -- necessary on a profile whose curve
    block has never been written, and harmless on one that has. Pass False
    to send three 2-byte pokes instead, which is what editing a single
    point on an already-configured curve looks like on the wire.

    Shared by sticks.py and triggers.py so the pacing cannot drift between
    them. Returns the last packet sent, matching set_value()'s contract.
    """
    # Resolved here rather than as a default argument so a test can patch
    # CURVE_POINT_WRITE_INTERVAL down to 0 -- a default is bound once at
    # import time and would ignore the patch. Same pattern session.py uses
    # for its read timeouts.
    if interval is None:
        interval = CURVE_POINT_WRITE_INTERVAL

    points = list(points)
    if whole_block:
        # One write, so there is nothing to pace and no page to carry into:
        # the block starts at the curve's own SETTING_ID and is 10 bytes,
        # which cannot cross a page for any curve we address.
        return session.send_raw(CMD_WRITE, prefix + curve_block_payload(setting_id, points))

    base_page = prefix[2]
    pkt = b""
    for page, payload in curve_point_payloads(setting_id, points, page=base_page):
        # The page lives in the prefix's third byte, so a point that carries
        # into the next page needs its own prefix -- see
        # curve_point_payloads().
        this_prefix = prefix[:2] + bytes([page])
        pkt = session.send_raw(CMD_WRITE, this_prefix + payload)
        time.sleep(interval)
        session.heartbeat()
        time.sleep(interval)
    return pkt


def decode_curve_points(blob: bytes, storage_offset: int) -> "list[list[int]] | None":
    """Read the three interior points out of a config blob. Returns
    [[x, y], ...] (lists, so it round-trips through JSON), or None if the
    blob is too short to cover them."""
    start = storage_offset + CURVE_POINTS_BLOCK_OFFSET
    end = start + CURVE_POINT_COUNT * 2
    if end > len(blob):
        return None
    if blob[storage_offset + 1] != CURVE_SCALE_CONFIGURED:
        return None          # block never written -- see CURVE_SCALE_CONFIGURED
    chunk = blob[start:end]
    return [[chunk[i], chunk[i + 1]] for i in range(0, len(chunk), 2)]


def preset_points(preset: str) -> list:
    """The three interior points a named preset carries, as [[x, y], ...].

    Lets a UI seed a fresh Custom curve from whatever preset is showing,
    which is what Nexus does -- switching preset -> Custom keeps the points
    on screen rather than starting from nothing.
    """
    idx = CURVE_PRESET_INDEX.get(preset.lower())
    if idx is None:
        return None
    shape = _CURVE_SHAPE_DATA[idx]
    pts = shape[3:9]         # [scale][origin x2] then the three (x, y) pairs
    return [[pts[i], pts[i + 1]] for i in range(0, len(pts), 2)]


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
