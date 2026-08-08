"""Buttons category: remap/unbind/read, button IDs, and the shared keycode table.

Write payload shape: 03 [PROFILE+LAYER] 00 [BUTTON_ID] 01 [KEYCODE]  (remap)
                      03 [PROFILE+LAYER] 00 [BUTTON_ID] 00            (unbind)

Reading current bindings back uses a different mechanism entirely (a
chunked read of a per-profile config blob, not addressed by BUTTON_ID at
all) -- see read_button_bindings()/decode_button_table() below and
PROTOCOL.md "Reading current config".

BUTTON_ID is always sent in its 2-byte "allocate" form ([allocate_id, 0x02]),
never the 1-byte "compact" form -- see _to_allocate_form()'s docstring for
why (hardware testing: a compact-form write to a button not yet
allocated this session is silently ignored, while the allocate form works
identically whether or not the button was already configured).
"""
import time

from .constants import CMD_WRITE, READ_CHUNK_LENGTH
from .session import VendorSession, profile_layer_byte

# Known BUTTON_ID values, stored here as the compact 1-byte form for
# readability/history -- remap()/unbind() always convert to the 2-byte
# allocate form via _to_allocate_form() before sending, so it doesn't matter
# whether a given button has been configured before. compact_id ==
# allocate_id + 1 (confirmed on two independent buttons: A went 0x7A -> 0x7B,
# B went 0x81 -> 0x82).
# NOTE: a button's binding can apparently get reset back to "unconfigured"
# at some point (cause unknown) -- this is *why* always-allocate-form
# matters: L5 showed its allocate form again on a later test despite an
# earlier compact-form-eligible write, and RT needed it again during GUI
# Phase 6 testing despite being confirmed compact-eligible in an earlier
# capture. See PROTOCOL.md "Buttons" for the wire-level consequence.
KNOWN_BUTTON_IDS = {
    "share": bytes([0xAC]),
    "a": bytes([0x7B]),
    "b": bytes([0x82]),
    "x": bytes([0x89]),
    "y": bytes([0x90]),
    "lb": bytes([0x5F]),
    "rb": bytes([0x66]),
    "lt": bytes([0xD4]),
    "rt": bytes([0xF0]),
    "l3": bytes([0x6D]),
    "r3": bytes([0x74]),
    "view": bytes([0x9E]),   # "duplicate window" icon near L5
    "menu": bytes([0xA5]),   # hamburger icon near R5
    "l4": bytes([0xB3]),
    "r4": bytes([0xC1]),
    # D-pad directions: only ever captured in allocate form, +7 apart.
    "dpad_up": bytes([0x42, 0x02]),
    "dpad_down": bytes([0x49, 0x02]),
    "dpad_left": bytes([0x50, 0x02]),
    "dpad_right": bytes([0x57, 0x02]),
    # L5, R5: only ever captured in allocate form (compact form would be
    # +1 -- BA/C8 -- but unconfirmed); stored as the 2-byte form directly,
    # same as D-pad above. Always-allocate-form now makes this moot anyway.
    "l5": bytes([0xB9, 0x02]),
    "r5": bytes([0xC7, 0x02]),
    # NOTE: L4/R4 showed the compact form on their genuinely-first-ever
    # write, contradicting the allocate-on-first-write pattern every other
    # button has followed. Unexplained; always-allocate-form makes it moot.
}

# Known KEYCODE values (the byte AFTER the fixed 0x01 type/page marker).
# Full linear table matching the on-screen Keyboard tab's picker layout,
# confirmed at 17 points across the Keyboard tab with zero deviation from
# the predicted linear run. Entries marked "predicted" below are
# interpolated from that run and are not individually confirmed; the
# unmarked ones are the 17 that were hardware-confirmed directly.
#
# Anything added here must also be reachable from the GUI's picker: see
# g7ctlc/widgets.py, where _assert_keycode_coverage() fails loudly if
# this dict grows an entry the picker doesn't offer.
#
# There is no separate keyboard/mouse/numpad/native "page" concept at the
# wire level -- it's one flat byte-value space. The Keyboard/Mouse/Numpad/
# Controller tabs in the app UI are a display grouping only.
KNOWN_KEYCODES = {
    # Native D-pad direction enum -- confirmed 2026-07-28 via live write+
    # read-diff (remapped dpad_up to a distinctive keycode, diffed the
    # read-back blob). Matches the bulk "Direction bindings" write's own
    # enum (see sticks.py's direction_bindings: 01/02/03/04), now
    # also confirmed as the per-button native/default keycode value. A
    # small dedicated enum, NOT part of the native-gamepad-function range
    # below (which starts at 0x05).
    # -- D-pad direction enum (0x01-0x04) --
    "native_dpad_up": 0x01,
    "native_dpad_down": 0x02,
    "native_dpad_left": 0x03,
    "native_dpad_right": 0x04,
    # Controller tab (native gamepad passthrough). Not a single clean run --
    # LB/RB/L3/R3 come before A/B/X/Y, then a gap before LT/RT. 0x10
    # confirmed 2026-07-28 (a "Share/Capture" function, picker's
    # upload-icon slot).
    #
    # 0x0D/0x11/0x12 (plus 0x1F, below) resolved 2026-07-30 via a different
    # method than every other entry here: instead of reading the picker's
    # own labels, we *wrote* these raw keycode values to X/Y/B/A on a
    # scratch profile (profile 4) from this tool, then opened GameSir Nexus
    # and read back what IT displayed those buttons as now bound to.
    # Confirmed: X->"Home" (0x0D -- Nexus's name for the native Xbox/Guide
    # button; there is no separate Keyboard-tab "Home" key in this table to
    # collide with), Y->"L4" (0x11), B->"R4" (0x12), A->"L5" (0x1F). This
    # both resolves 0x0D (previously totally unexplained) and independently
    # confirms the "0x11/0x12 are native L4/R4" hypothesis this table
    # already carried as an inference from their appearing as L4/R4's
    # factory-default bindings. Xbox/Guide and M are still not valid
    # remap *targets* in Nexus's own UI (a red-circle grid entry that looked
    # like a candidate, tested 2026-07-28, turned out to be the dialog's own
    # "currently editing this button" self-reference) -- but the wire value
    # for native Home clearly exists and is readable/writable via this raw
    # protocol regardless of what Nexus's picker itself exposes.
    # -- Native gamepad functions (0x05-0x14) --
    "native_lb": 0x05,
    "native_rb": 0x06,
    "native_l3": 0x07,
    "native_r3": 0x08,
    "native_a": 0x09,
    "native_b": 0x0A,
    "native_x": 0x0B,
    "native_y": 0x0C,
    "native_home": 0x0D,   # confirmed 2026-07-30 via Nexus's own translation -- see comment above
    "native_view": 0x0E,
    "native_menu": 0x0F,
    "native_share_capture": 0x10,  # confirmed 2026-07-28, Controller-native picker's Share/Capture-icon slot
    "native_l4": 0x11,     # confirmed 2026-07-30 via Nexus's own translation -- see comment above
    "native_r4": 0x12,     # confirmed 2026-07-30 via Nexus's own translation -- see comment above
    "native_lt": 0x13,
    "native_rt": 0x14,
    # 0x1F/0x20 sit well outside the 0x01-0x14 native-gamepad block above --
    # a separate region, not a numbering mistake (the asymmetry was flagged
    # as suspicious before it was resolved, precisely because L4/R4 sit
    # inside the block and L5/R5 don't). Both confirmed 2026-07-30 the same way as
    # native_home/native_l4/native_r4 above: written to a scratch profile's
    # A button (0x1F) and Menu button (0x20) from this tool, then read back
    # via Nexus as "L5" and "R5" respectively.
    "native_l5": 0x1F,
    "native_r5": 0x20,
    # Controller-native picker also has a microphone icon and a bidirectional
    # swap-arrows icon (bottom row), confirmed 2026-07-28 -- both landed in a
    # completely different, previously-unseen keycode region (0xE6/0xE7),
    # nowhere near the 0x01-0x14 native-gamepad block above. Wire values are
    # certain (direct write+read-diff); the exact function each represents
    # is not confirmed, only guessed from the icon shape.
    # -- Outlying region (0xE6/0xE7), function guessed from picker icons --
    "mic_mute": 0xE6,          # tentative name -- byte confirmed, function guessed from a microphone icon
    "unknown_swap_0xe7": 0xE7,  # byte confirmed, function unknown -- bidirectional-arrows icon, name deliberately not guessed
    # -- Numeric keypad digits: numpad_n = 0x8B + n, confirmed at n=0,1,7,9 --
    "numpad0": 0x8B,
    "numpad1": 0x8C,
    "numpad2": 0x8D,    # predicted
    "numpad3": 0x8E,    # predicted
    "numpad4": 0x8F,    # predicted
    "numpad5": 0x90,    # predicted
    "numpad6": 0x91,    # predicted
    "numpad7": 0x92,
    "numpad8": 0x93,    # predicted
    "numpad9": 0x94,
    # -- Mouse tab (0xC8-0xCE, one contiguous run) --
    "mouse_left": 0xC8,
    "mouse_middle": 0xC9,   # confirmed 2026-07-28
    "mouse_right": 0xCA,
    "mouse_button5": 0xCB,  # confirmed 2026-07-28 -- side button, picker labels it "Mouse Button 5"
    "mouse_button4": 0xCC,  # confirmed 2026-07-28 -- side button, picker labels it "Mouse Button 4"
    "scroll_up": 0xCD,
    "scroll_down": 0xCE,
    # Keyboard tab -- the full linear table (Esc, F1-F12, number row, then
    # each subsequent row); the per-entry "predicted" markers below carry
    # confirmed-vs-predicted status. Existing names/values below are unchanged; this
    # just fills in the rest of the table so a real controller's Keyboard-
    # tab binding is never outside this dict's coverage (see
    # decode_button_table()'s raw-hex fallback note above -- landing there
    # for a common key would be a real GUI bug, not just cosmetic).
    # -- Keyboard: function row (0x32-0x3E) --
    "esc": 0x32,        # predicted
    "f1": 0x33,         # predicted
    "f2": 0x34,         # predicted
    "f3": 0x35,         # predicted
    "f4": 0x36,         # predicted
    "f5": 0x37,         # predicted
    "f6": 0x38,         # predicted
    "f7": 0x39,         # predicted
    "f8": 0x3A,         # predicted
    "f9": 0x3B,         # predicted
    "f10": 0x3C,        # predicted
    "f11": 0x3D,
    "f12": 0x3E,
    # -- Keyboard: number row (0x3F-0x4C) --
    "backtick": 0x3F,   # predicted, ` / ~
    "1": 0x40,
    "2": 0x41,
    "3": 0x42,
    "4": 0x43,
    "5": 0x44,          # predicted
    "6": 0x45,          # predicted
    "7": 0x46,          # predicted
    "8": 0x47,          # predicted
    "9": 0x48,
    "0": 0x49,          # predicted
    "minus": 0x4A,      # confirmed, - / _
    "equals": 0x4B,     # predicted, = / +
    "backspace": 0x4C,  # predicted
    # -- Keyboard: QWERTY row (0x4D-0x5A) --
    "tab": 0x4D,        # predicted
    "q": 0x4E,          # predicted
    "w": 0x4F,
    "e": 0x50,          # predicted
    "r": 0x51,          # predicted
    "t": 0x52,          # predicted
    "y": 0x53,          # predicted
    "u": 0x54,          # predicted
    "i": 0x55,          # predicted
    "o": 0x56,          # predicted
    "p": 0x57,          # predicted
    "lbracket": 0x58,   # predicted, [ / {
    "rbracket": 0x59,   # predicted, ] / }
    "backslash": 0x5A,  # predicted, \ / |
    # -- Keyboard: home row (0x5B-0x67) --
    "capslock": 0x5B,   # predicted
    "a": 0x5C,
    "s": 0x5D,
    "d": 0x5E,
    "f": 0x5F,          # predicted
    "g": 0x60,          # predicted
    "h": 0x61,          # predicted
    "j": 0x62,          # predicted
    "k": 0x63,          # predicted
    "l": 0x64,          # predicted
    "semicolon": 0x65,  # predicted, ; / :
    "quote": 0x66,      # predicted, ' / "
    "enter": 0x67,
    # -- Keyboard: bottom row (0x68-0x73) --
    "shift": 0x68,      # predicted, left shift
    "z": 0x69,          # predicted
    "x": 0x6A,          # predicted
    "c": 0x6B,          # predicted
    "v": 0x6C,          # predicted
    "b": 0x6D,          # predicted
    "n": 0x6E,          # predicted
    "m": 0x6F,          # predicted
    "comma": 0x70,      # predicted, , / <
    "period": 0x71,     # predicted, . / >
    "slash": 0x72,      # predicted, / / ?
    "rshift": 0x73,     # predicted, right shift
    # -- Keyboard: modifier row (0x74-0x79) --
    "ctrl": 0x74,       # confirmed, left ctrl
    "win": 0x75,        # confirmed
    "alt": 0x76,        # predicted, left alt
    "space": 0x77,
    "ralt": 0x78,       # confirmed, right alt
    "rctrl": 0x79,      # predicted, right ctrl
    # Numeric Keypad tab's operator keys -- confirmed 2026-07-28, a clean
    # consecutive run right before the digit block (numpad0 = 0x8B).
    "numpad_slash": 0x85,
    "numpad_star": 0x86,
    "numpad_minus": 0x87,
    "numpad_plus": 0x88,
    "numpad_period": 0x89,
    "numpad_enter": 0x8A,
}


# ---------------------------------------------------------------------------
# Name <-> wire value resolution
# ---------------------------------------------------------------------------


def resolve_button_id(s: str) -> bytes:
    if s.lower() in KNOWN_BUTTON_IDS:
        return KNOWN_BUTTON_IDS[s.lower()]
    return bytes.fromhex(s.replace(" ", ""))


def resolve_keycode(s: str) -> int:
    if s.lower() in KNOWN_KEYCODES:
        return KNOWN_KEYCODES[s.lower()]
    value = int(s, 16)
    # A keycode is one wire byte. Without this check a value like "1ff"
    # passes state.py's validate_state() (which just calls this same parse
    # to check validity) and then blows up deep inside remap()'s
    # bytes([0x01, keycode]) with a generic "bytes must be in range(0, 256)"
    # that doesn't say which field caused it.
    if not 0 <= value <= 255:
        raise ValueError(f"keycode {s!r} out of range: must be a known name or 00-ff")
    return value


def _to_allocate_form(button_id: bytes) -> bytes:
    """Normalize a button ID to its 2-byte allocate form ([compact_id - 1,
    0x02]). Hardware-confirmed: the compact 1-byte
    form is silently ignored if the button hasn't been allocated yet this
    session, while the allocate form works identically whether or not it
    was already configured -- so every write uses this form unconditionally
    rather than trying to guess which one a button currently needs. (A read
    mechanism does now exist -- see read_button_bindings() below -- but it
    reports keycodes per fixed slot, not this allocate/compact ID business,
    so it doesn't actually help decide which write form to use here.)"""
    if len(button_id) == 2:
        return button_id
    if len(button_id) == 1:
        if button_id[0] == 0x00:
            # button_id[0] - 1 would be -1, and bytes([-1, 0x02]) fails with
            # an opaque "bytes must be in range(0, 256)" that doesn't say
            # what's actually wrong. Reachable via the CLI's raw-hex button
            # fallback (resolve_button_id("00")).
            raise ValueError("button_id 0x00 has no compact-form representation")
        return bytes([button_id[0] - 1, 0x02])
    raise ValueError(f"button_id must be 1 or 2 bytes, got {len(button_id)}")


# ---------------------------------------------------------------------------
# Writing bindings
# ---------------------------------------------------------------------------


def remap(session: VendorSession, button_id: bytes, keycode: int, profile: int = 1, shift: bool = False) -> bytes:
    pl_byte = profile_layer_byte(profile, shift)
    payload = bytes([0x03, pl_byte, 0x00]) + _to_allocate_form(button_id) + bytes([0x01, keycode])
    return session.send_raw(CMD_WRITE, payload)


def unbind(session: VendorSession, button_id: bytes, profile: int = 1, shift: bool = False) -> bytes:
    # Distinct format from remap(): a single trailing 0x00 instead of
    # [0x01, keycode]. Confirmed on L5/R5. Also frees the button's slot --
    # its next remap write will use the 2-byte allocate form again.
    pl_byte = profile_layer_byte(profile, shift)
    payload = bytes([0x03, pl_byte, 0x00]) + _to_allocate_form(button_id) + bytes([0x00])
    return session.send_raw(CMD_WRITE, payload)


# --- Reading bindings back (see PROTOCOL.md "Reading current config") ---
#
# The per-profile config blob (read via VendorSession.read_chunk(), keyed
# by the same profile_layer_byte() category as writes) contains a button
# table starting at BUTTON_TABLE_OFFSET: one fixed 7-byte record per slot,
# `01 [KEYCODE] 00 00 00 00 00`. A slot not starting with 0x01 is treated
# as unbound -- inferred by symmetry with unbind()'s write format (a single
# trailing 0x00 instead of [0x01, keycode]), not independently confirmed
# for every possible slot.
BUTTON_TABLE_OFFSET = 0x42
BUTTON_TABLE_SLOT_SIZE = 7

# Slot order, confirmed via live capture cross-referenced against the
# controller's actual current bindings (2026-07-27), extended 2026-07-28
# with a live write+read-diff experiment (remap one slot to a distinctive
# keycode, diff the read-back blob against a pre-change read) to locate
# D-pad, which isn't visible in the app-observed capture the rest of this
# table came from: the 4 D-pad directions come first (confirmed spacing:
# exactly BUTTON_TABLE_SLOT_SIZE apart, immediately before the rest of the
# table), then the 8 native-gamepad slots in the same order as this file's
# own native_* keycodes, a reserved gap for the non-remappable Xbox/Guide
# button, then View/Menu, then the 5 "special" buttons in ascending
# BUTTON_ID order (Share < L4 < L5 < R4 < R5) -- NOT the L4/R4/L5/R5
# grouping used for readability elsewhere in this file.
BUTTON_TABLE_SLOTS = [
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "lb", "rb", "l3", "r3", "a", "b", "x", "y",
    None,  # reserved: Xbox/Guide, confirmed non-remappable
    "view", "menu",
    "share", "l4", "l5", "r4", "r5",
]
BUTTON_TABLE_END = BUTTON_TABLE_OFFSET + len(BUTTON_TABLE_SLOTS) * BUTTON_TABLE_SLOT_SIZE

# LT/RT don't fit the uniform table above -- confirmed 2026-07-28 via the
# same live write+read-diff technique, their current keycode is a single
# raw byte (no 0x01 marker, no zero padding) sitting at a fixed offset
# inside what's otherwise the Triggers category's own deadzone-constant-
# block data for that side (see PROTOCOL.md "Reading current config" for
# the byte-level detail). Very likely a firmware memory-layout
# coincidence/overlap rather than a deliberate shared field, but
# empirically confirmed stable. No confirmed "unbound" sentinel for these
# two (both were bound to their native function, 0x13/0x14, in every
# sample so far) -- the raw byte is always decoded as a keycode, never as
# None, unlike the slots above.
TRIGGER_BUTTON_OFFSETS = {"lt": 0xD4, "rt": 0xF0}

# Chunk offsets covering everything above (the uniform table AND the LT/RT
# single-byte offsets, whichever extends further), matching the exact
# chunking real captured traffic used (READ_CHUNK_LENGTH-sized requests
# starting at 0) -- deliberately not a generic paginator, since the
# firmware's tolerance for arbitrary/custom lengths isn't confirmed, only
# this exact observed shape.
_READ_COVERAGE_END = max(BUTTON_TABLE_END, max(TRIGGER_BUTTON_OFFSETS.values()) + 1)
_BUTTON_TABLE_CHUNK_OFFSETS = tuple(
    range(0, ((_READ_COVERAGE_END + READ_CHUNK_LENGTH - 1) // READ_CHUNK_LENGTH) * READ_CHUNK_LENGTH, READ_CHUNK_LENGTH)
)

_CODE_TO_KEYCODE_NAME = {}
for _name, _code in KNOWN_KEYCODES.items():
    _CODE_TO_KEYCODE_NAME.setdefault(_code, _name)


def decode_keycode(code: int) -> str:
    """Reverse of resolve_keycode(): a keycode byte -> its known name, or
    raw hex (e.g. "0x3e") if it's not in KNOWN_KEYCODES' still-incomplete
    coverage. Shared by decode_button_table() below and sticks.py's
    direction_bindings decode (the D-pad direction enum used there is
    already covered by KNOWN_KEYCODES' native_dpad_* entries)."""
    return _CODE_TO_KEYCODE_NAME.get(code, f"0x{code:02x}")


def decode_button_table(blob: bytes) -> dict:
    """Decode the button-binding table out of a profile config blob (`blob`
    must cover at least _READ_COVERAGE_END bytes). Returns
    {slot_name: keycode_name_or_raw_hex_or_None} -- None means unbound;
    a keycode not present in KNOWN_KEYCODES comes back as a raw hex string
    (e.g. "0x3e") rather than a name, and won't pass validate_profile()
    as-is -- that's an expected gap in KNOWN_KEYCODES' coverage, not a bug
    here."""
    result = {}
    offset = BUTTON_TABLE_OFFSET
    for slot in BUTTON_TABLE_SLOTS:
        record = blob[offset:offset + BUTTON_TABLE_SLOT_SIZE]
        offset += BUTTON_TABLE_SLOT_SIZE
        if slot is None:
            continue
        if len(record) < 2 or record[0] != 0x01:
            result[slot] = None
            continue
        code = record[1]
        result[slot] = decode_keycode(code)
    for slot, off in TRIGGER_BUTTON_OFFSETS.items():
        if off < len(blob):
            # 0x00 here means "never configured", the trigger's equivalent of
            # a table slot whose record doesn't start with 0x01 -- so it maps
            # to None like every other unconfigured slot, not to the raw hex
            # string "0x00". Confirmed 2026-08-07: Profile 2 carries 0x00 for
            # both triggers and both triggers work normally (Steam Input and
            # KDE controller settings), so the byte means "factory function",
            # not "no keycode". Rendering it as "Raw: 0x00" made an untouched
            # profile look broken. See PROTOCOL.md "An empty slot means
            # factory default, not unbound".
            #
            # Deliberately scoped to these two offsets rather than to
            # decode_keycode(): 0x00 is not a universal "unset" marker. The
            # Sticks direction bindings use 0xFF for that (see sticks.py),
            # and what 0x00 means there is not established.
            result[slot] = None if blob[off] == 0x00 else decode_keycode(blob[off])
    return result


def read_button_bindings(session: VendorSession, profile: int = 1, shift: bool = False,
                          interval: float = 0.05) -> dict:
    """Read a profile/layer's current button bindings directly from the
    device. Returns {slot_name: keycode_name_or_None}, same shape as one
    layer of a state dict's "buttons" section. Sends a heartbeat after
    each chunk (mirroring the heartbeat-per-write pattern writes need --
    not independently confirmed reads need it too, but not worth risking)."""
    category = profile_layer_byte(profile, shift)
    blob = bytearray()
    for offset in _BUTTON_TABLE_CHUNK_OFFSETS:
        blob.extend(session.read_chunk(category, offset, READ_CHUNK_LENGTH))
        session.heartbeat()
        time.sleep(interval)
    return decode_button_table(bytes(blob))
