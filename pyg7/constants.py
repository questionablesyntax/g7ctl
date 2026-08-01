"""USB identities and low-level protocol constants. See PROTOCOL.md."""

VID = 0x3537
PID_XINPUT = 0x100a   # default runtime identity ("Xbox 360 Controller for Windows")
PID_VENDOR = 0x109b   # vendor/config identity ("GameSir-G7 Pro")
PID_DONGLE = 0x109c   # 2.4GHz wireless dongle -- same vendor-protocol endpoints as
                      # PID_VENDOR, but reachable directly with NO handshake: the
                      # dongle has no separate XInput identity to switch from in the
                      # first place, so 0x0f writes need no local re-enumeration.
                      # That is a USB-side difference only: the dongle is a bridge,
                      # and the controller behind it is captured and held in config
                      # mode exactly as it is over the cable, so it is NOT usable as
                      # a gamepad while a session is open (corrected 2026-07-31 --
                      # the earlier note here claimed xpad stayed bound and the pad
                      # kept working). See PROTOCOL.md "Device identities".
PID_NATIVE = 0x1022   # the controller's own "default GameSir identity" -- reached by
                      # holding Menu+Share on the controller (documented in GameSir's
                      # manual as an XInput/native-identity toggle; also the same
                      # combo that clears a rare CMD_READ wedge). Two plain HID-class
                      # interfaces (no vendor-specific class 255 interface at all),
                      # neither one answers the standard CMD_HEARTBEAT payload or
                      # streams anything unprompted -- found 2026-07-30, not the same
                      # protocol as PID_VENDOR/PID_DONGLE and not reverse-engineered.
                      # Recognized here only so a user in this identity gets a clear
                      # "press Menu+Share to switch back" message instead of "no
                      # device found". See PROTOCOL.md "Device identities".
EP_OUT = 0x02
EP_IN = 0x82
IFACE = 0

# Handshake: send ASCII "gamesirapp" as 5 chunks of 2 chars to flip the
# device from PID_XINPUT to PID_VENDOR, no windows app involved.
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
