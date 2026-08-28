"""USB identities and low-level protocol constants. See PROTOCOL.md."""

from typing import Optional

VID = 0x3537
PID_XINPUT = 0x100a   # default runtime identity ("Xbox 360 Controller for Windows").
                      # Where the hardware idles on BOTH transports -- the dongle
                      # sits here too once nothing is heartbeating it.
PID_VENDOR = 0x109b   # vendor/config identity ("GameSir-G7 Pro")
PID_DONGLE = 0x109c   # 2.4GHz wireless dongle in vendor/config mode -- the dongle's
                      # counterpart to PID_VENDOR, with the same endpoints. Reached
                      # by the same "gamesirapp" handshake from PID_XINPUT, and
                      # reverts there when heartbeats stop. Not usable as a gamepad
                      # while a session is open, exactly like PID_VENDOR.
                      # Twice-corrected, both times because this was only ever
                      # observed mid-session: 2026-07-31, it does not keep working
                      # as a pad (xpad is not bound); 2026-08-01, it is not a
                      # handshake-free always-on identity either -- an idle dongle
                      # enumerates as PID_XINPUT. See PROTOCOL.md "Device
                      # identities".
PID_VENDOR_TRIMODE = 0x1003   # vendor/config identity on at least one other G7 Pro
                      # variant -- reported 2026-08-19 from a community bug report, not
                      # this project's own hardware. Same interface-1 signature
                      # is_xinput_personality() already uses for PID_VENDOR (an
                      # isochronous alt-setting pair, no HID keyboard/mouse), just under
                      # a different PID. CONFIRMED 2026-08-19: the reporter read real
                      # config back over it (manually, before this constant existed) --
                      # a genuine round trip, not just a descriptor-shape match. See
                      # PROTOCOL.md "Device identities".
PID_VENDOR_ZZZ = 0x105d   # vendor/config identity on a G7 Pro "Zenless Zone Zero"
                      # edition, reported 2026-08-19 -- another community report, not
                      # this project's own hardware. Same story as PID_VENDOR_TRIMODE:
                      # interface 1's descriptor shape (isochronous alt-setting pair, no
                      # HID keyboard/mouse) matches PID_VENDOR's exactly. CONFIRMED
                      # 2026-08-19: the reporter tested this branch directly and read
                      # real config back over it end to end -- a genuine round trip, not
                      # just a descriptor-shape match. The reporter had originally
                      # assumed this PID *was* the XInput identity (xpad binds to
                      # interface 0 and Steam shows a working pad regardless of which
                      # personality is present, which is not evidence either way -- see
                      # is_xinput_personality()). See PROTOCOL.md "Device identities".
PID_DONGLE_TRIMODE = 0x1004   # the Tri-mode variant's 2.4GHz dongle in vendor/config
                      # mode -- PID_VENDOR_TRIMODE's counterpart, exactly one PID higher,
                      # same relationship PID_VENDOR (109b) has to PID_DONGLE (109c).
                      # Reported and CONFIRMED 2026-08-19 by the same reporter as
                      # PID_VENDOR_TRIMODE: found by hand ("vendor ID for white Tri-mode
                      # is 1004"), receiver connection worked after a brute constants.py
                      # edit -- a genuine round trip. The "+1" relationship held on two
                      # separate SKUs now (this project's own 109b/109c, and this one) --
                      # worth testing as a real pattern before more variants get their
                      # own hardcoded pair, but not assumed here yet. See PROTOCOL.md
                      # "Device identities".
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
# Vendor-mode PID -> human-readable variant name. Real answer to roadmap
# item 36's original question ("how does software know which G7 Pro
# colourway is attached") -- not via the CMD=0x01 selector sweep that item
# spent six sessions mapping (all 256 selectors now behaviorally known;
# none carries a colourway value anywhere in the space, see ROADMAP.md),
# but via the vendor-mode PID itself: three SKUs, three distinct PIDs,
# zero counterexamples (n=3, 2026-08-19 -- see VARIANT_PIDS.md). The
# original "it cannot be coming from USB descriptors" framing that started
# the sweep checked product string/bcdDevice/serial on this project's own
# single unit; it never had a second PID to compare against, because at
# the time there was only one. Deliberately keyed on the *vendor* PID, not
# XInput/native/dongle -- those aren't independently confirmed to vary
# per-variant the same way (see VARIANT_PIDS.md's "Gaps" section), and a
# dongle's vendor PID is its own wired counterpart + 1 wherever confirmed,
# not looked up here separately.
VARIANT_NAMES = {
    PID_VENDOR: "Shadow Ember",
    PID_VENDOR_TRIMODE: "White Trimode",
    PID_VENDOR_ZZZ: "Zenless Zone Zero",
}


def identify_variant(vendor_pid: int) -> Optional[str]:
    """Human-readable colourway/edition name for a known vendor-mode PID,
    or None for one this project hasn't seen a confirmed report on yet
    (e.g. Dragon's Dogma 2 and WUCHANG editions -- see README.md "Hardware
    support"). None is a real, expected answer here, not a bug: this is a
    lookup against confirmed reports, not a formula that covers every PID
    GameSir might ever assign.
    """
    return VARIANT_NAMES.get(vendor_pid)


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
# WARNING: unknown selectors drop the device out of vendor mode within
# seconds (a clean revert to PID_XINPUT, not the CMD_READ wedge). A control
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
