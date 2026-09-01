"""Low-level protocol constants -- wire format only. See PROTOCOL.md.

USB identity data (PIDs, per-variant or shared) lives in variants.py
instead, not here -- moved out entirely 2026-09-01 (initially only the
per-SKU PIDs moved; the reference hardware's own PID_HID/PID_XID/
PID_DONGLE/PID_NATIVE were kept here at first on the reasoning that they
were "identity-class, used regardless of variant" -- overruled directly:
they're real PID values tied to specific hardware identities the same way
every other variant's PIDs are, and variants.py is where PID data lives,
full stop, not split by how many variants currently happen to share a
value). This module has zero USB product IDs in it now.
"""

VID = 0x3537

EP_OUT = 0x02
EP_IN = 0x82
IFACE = 0

# Handshake: send ASCII "gamesirapp" as 5 chunks of 2 chars to flip the
# device from PID_HID to PID_XID, no windows app involved.
HANDSHAKE_CHUNKS = ["ga", "me", "si", "ra", "pp"]
EMPTY_FLUSH = bytes([0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

# Command byte (position 3 of the 64-byte 0x0f-report packet).
CMD_HEARTBEAT = 0x02
CMD_WRITE = 0x3c   # general "config write" command, shared by every settings category
CMD_READ = 0x05    # chunked config-read command -- see PROTOCOL.md "Reading current config"

# CMD_READ request payload: 04 [CATEGORY] [OFFSET_HI] [OFFSET_LO] [LENGTH].
# CATEGORY uses the same profile_layer_byte() scheme as Buttons writes
# (profile + 4 if shift) -- see session.py. `0x04` is a fixed sub-byte
# present in every observed request but NOT echoed back in the response.
READ_SUBCOMMAND = 0x04

# Response report ID (IN, device->host) -- distinct from the 0x0f OUT
# channel. Shares its physical endpoint/pipe with a continuous, unrelated
# analog-telemetry stream, so a reader must match responses by content
# (the echoed request fields), not just "next report on this ID."
REPORT_ID_READ_RESPONSE = 0x10
# Fixed marker byte in the 0x10 response's own framing (position 3, same
# byte value as CMD_WRITE but a coincidence -- this is not a write ack).
READ_RESPONSE_MARKER = 0x3c

# Report 0x10 carries two different things, told apart by byte 4: read
# responses (READ_SUBCOMMAND) and the device's own unprompted input stream
# (INPUT_FRAME_MARKER). See PROTOCOL.md "The input stream on report 0x10".
INPUT_FRAME_MARKER = 0xE0

# Battery lives in the input stream, not behind any query -- the device
# pushes it for as long as a vendor session is open. See PROTOCOL.md
# "Battery level".
BATTERY_OFFSET = 33          # percentage, 0-100
BATTERY_CHARGING_OFFSET = 32  # 1 while charging, 0 otherwise
BATTERY_MAX = 100

# Device-info query. Byte 4 of the command selects which field comes back.
# The answer arrives on REPORT_ID_READ_RESPONSE, and its own byte 4 is an
# ECHO of `selector + 1` -- not a length, despite sitting where a length
# sits in other framing on this report ID. Reading it as one truncates the
# payload: it reads 0x0a for both an 8-byte and a 16-byte firmware string.
# See VendorSession.read_device_info(). Only these two selectors appear
# anywhere in the capture corpus, because they are the only two Nexus asks
# for.
#
# WARNING: unknown selectors cause an unprompted re-enumeration within
# seconds (landing on PID_HID, not the CMD_READ wedge). A control
# of 32 commands using only these two, at the same rate, survives fine. Do
# not sweep the selector space casually -- see PROTOCOL.md "Device info".
CMD_DEVICE_INFO = 0x01
INFO_FIRMWARE = 0x09
# The ACTIVE profile -- which one the controller is physically using, as a
# plain 1-4. Confirmed 2026-08-12: reads 0x01 on Profile 1 (six separate
# readings, including three from July captures) and 0x03 immediately after
# an M+A switch to Profile 3.
#
# This is why it was never found in storage. Ruled out of all six config
# blobs, the 0x10 input stream and report 0x20 before anyone looked here --
# it is device *state*, and CMD_DEVICE_INFO is the channel for that.
INFO_ACTIVE_PROFILE = 0x0b
PROFILE_MIN, PROFILE_MAX = 1, 4

# Chunk size used by every observed real request except a region's final
# (shorter) chunk. Confirmed via live capture: a profile's full config blob
# is exactly 480 bytes (8 chunks of 0x37 + one 0x28 remainder), and the
# button-binding table specifically lives in the first 4 chunks (bytes
# 0-219) -- see buttons.py's BUTTON_TABLE_* constants.
READ_CHUNK_LENGTH = 0x37

# Total size of one profile's config blob (Buttons + Sticks/Triggers/
# Vibration all live in this same per-profile blob -- see state.py's
# read_state(), which reads this many bytes via VendorSession.read_blob()).
FULL_BLOB_LENGTH = 480

# Category prefixes for CMD_WRITE payloads (first 3 bytes after the command
# byte). The middle byte is a plain PROFILE number (1-4), same targeting
# model as Buttons' PROFILE+LAYER byte (buttons.py) -- confirmed 2026-07-28
# via live GameSir Nexus capture (an Invert X write made while Profile 2 was
# selected sent `03 02 01`, not the `03 01 01` every earlier test happened to
# use) plus a direct hardware test (writing report rate with the middle byte
# set to 2, no physical profile switch at all, landed cleanly in Profile 2
# only). Previously hardcoded to Profile 1 as `PREFIX_STICKS_LEFT`/
# `PREFIX_TRIGGERS_VIBRATION` constants -- every prior test (including our
# own) always used Profile 1, which is why this went unnoticed. See
# PROTOCOL.md "Profile scoping" for the confirmed targeting model.
def prefix_sticks(profile: int = 1) -> bytes:
    if not 1 <= profile <= 4:
        raise ValueError("profile must be 1-4")
    return bytes([0x03, profile, 0x01])


def prefix_triggers_vibration(profile: int = 1) -> bytes:
    if not 1 <= profile <= 4:
        raise ValueError("profile must be 1-4")
    return bytes([0x03, profile, 0x00])


# Dock settings (LED brightness, Auto On/Off) -- a genuinely different
# category from everything above: confirmed 2026-07-28 that the middle
# byte stays a FIXED `0x20` across every write regardless of which
# profile is active, unlike every other category's profile-scoped middle
# byte. Global/device-wide, not per-profile -- see PROTOCOL.md "Dock
# Settings". CMD_READ's category byte for this same area is also `0x20`
# directly (not a profile+shift value at all).
PREFIX_DOCK = bytes([0x03, 0x20, 0x01])
DOCK_READ_CATEGORY = 0x20
# Same STORAGE_BASE convention as Sticks' `03 [profile] 01` prefix (the
# third prefix byte `0x01` matching is probably not a coincidence) --
# confirmed via live read-diff: SETTING_ID 0xF9 (brightness) read back
# correctly at absolute offset 0x1F9, not 0xF9.
DOCK_STORAGE_BASE = 0x100

# Right Stick / Right Trigger reuse the Left side's SETTING_IDs shifted by a
# fixed per-category offset -- NOT a universal constant, confirmed different
# per category. See PROTOCOL.md "Sticks" / "Triggers".
RIGHT_STICK_OFFSET = 0x20
RIGHT_TRIGGER_OFFSET = 0x1C
