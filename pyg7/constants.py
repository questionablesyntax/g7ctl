"""USB identities and low-level protocol constants. See PROTOCOL.md."""

from typing import Optional

VID = 0x3537
# Renamed 2026-08-29, retiring the "vendor mode" misconception from the
# names themselves, not just the comments (see PROTOCOL.md "Device
# identities" for the full account): both PIDs are, and always were,
# fully working XInput identities -- neither is a "vendor/config mode" a
# gamepad has to leave. The only real difference is whether a second HID
# interface (keyboard+mouse, for remapped key/mouse events) is presented,
# which tracks the *active profile's own trigger-bundle content* -- NOT
# just keyboard/mouse bind content: confirmed 2026-08-29 that 1000Hz
# report rate is a second, independent trigger, with zero keyboard/mouse
# binds involved (500Hz+all-native -> PID_XID, 1000Hz+all-native ->
# PID_HID, `lsusb -v`-verified as a genuine HID-class interface 1 either
# way, not a PID-only coincidence). Motion output set to Mouse is the same
# trigger as a bound key, not a third one. GameSir's own manual already
# describes "1000Hz polling and keyboard/mouse remapping" as one bundle
# unlocked together (at the native-GIP-vs-XInput axis); this is the same
# bundle governing this finer PID_HID/PID_XID split too. **The bundle is
# now confirmed closed, not just a floor** -- owner tested every setting
# category on real hardware (2026-08-29): the only two triggers are (1)
# anything that outputs to a keyboard or mouse (any button bind, Motion
# output set to Mouse) and (2) 1000Hz report rate. Nothing else in the
# settings moves this PID. Not a switchable device "personality"
# either way. Both PIDs equally answer the config/telemetry protocol this
# whole package speaks. Old names, for anyone grepping history:
# PID_XINPUT -> PID_HID, PID_VENDOR -> PID_XID.
PID_HID = 0x100a      # "Xbox 360 Controller for Windows" -- presents the extra
                      # HID keyboard/mouse interface. Reached from PID_XID by
                      # the "gamesirapp" handshake when the active profile needs
                      # that interface (keyboard/mouse binds OR 1000Hz report
                      # rate -- see the trigger-bundle comment above); see
                      # PROTOCOL.md "The handshake" for what is and isn't
                      # established about that transition.
PID_XID = 0x109b      # "GameSir-G7 Pro" -- baseline XInput identity, no extra HID
                      # interface. Presented only when EVERY member of the
                      # trigger bundle above is at its baseline (all-native
                      # binds AND report rate below 1000Hz). Fully playable as a
                      # gamepad, and answers this project's whole config/telemetry
                      # protocol -- there is no gate between the two.
PID_DONGLE = 0x109c   # 2.4GHz wireless dongle counterpart to PID_XID, same
                      # endpoints. Historically documented as reached by the same
                      # "gamesirapp" handshake from an idle PID_HID dongle state,
                      # falling back there once heartbeats stop -- that framing
                      # predates the 2026-08-29 correction above and has not been
                      # re-verified under it (the bind-content trigger has only
                      # been confirmed wired). Twice-corrected before that, both
                      # times because this was only ever observed mid-session:
                      # 2026-07-31, it does not keep working as a pad (xpad is not
                      # bound); 2026-08-01, it is not a handshake-free always-on
                      # identity either -- an idle dongle enumerates as PID_HID.
                      # See PROTOCOL.md "Device identities".
                      #
                      # UNCONFIRMED HYPOTHESIS, raised 2026-08-29 (owner's,
                      # hardware currently broken so untestable): the dongle
                      # itself may only ever present this one PID, not
                      # splitting into its own XID/HID pair the way the wired
                      # connection does -- i.e. the active profile's
                      # bind-content trigger (see PID_HID/PID_XID above)
                      # might apply to the controller behind the RF link,
                      # invisible on the USB side, with the dongle's own USB
                      # identity staying fixed regardless. No PID_DONGLE_HID
                      # has been added on this basis. Read literally, this
                      # conflicts with the paragraph above's own confirmed
                      # observation that an idle dongle enumerates as PID_HID
                      # (100a), only landing here (109c) once handshaked --
                      # a tension caught during a same-day post-rename
                      # read-through, not assumed away.
                      #
                      # RESOLVED, same day, by real firmware evidence (not
                      # hardware, since that's still broken): jieli-re's
                      # extracted-firmware corpus contains the Tri-mode
                      # variant's own dongle firmware (dongle_tool_container.bin),
                      # and its compiled-in USB device descriptor table has
                      # BOTH 0x100a (PID_HID's own shared value, class 0 --
                      # composite) AND 0x1004 (PID_DONGLE_TRIMODE, class 255 --
                      # vendor-specific) as its own two identities. That's the
                      # dongle splitting into an HID-shaped/baseline pair on
                      # its own USB side, the same way the wired connection
                      # does -- not a fixed single identity. That also settles
                      # the tension above: an idle dongle sitting at PID_HID is
                      # just this same split surfacing on the USB side, not
                      # evidence against it. The hypothesis reads as refuted
                      # for the Tri-mode variant specifically; not directly
                      # confirmed for 109c (this project's own dongle firmware
                      # isn't in that corpus), but there's no remaining reason
                      # to expect this variant's firmware architecture to
                      # differ on this point. See ROADMAP.md item 51's tail
                      # for the full firmware-corpus cross-reference.
PID_XID_TRIMODE = 0x1003   # baseline (no-HID-interface) identity on at least
                      # one other G7 Pro variant -- reported 2026-08-19 from a
                      # community bug report, not this project's own hardware. Same
                      # interface-1 descriptor shape as PID_XID (isochronous
                      # alt-setting pair, no HID keyboard/mouse), just under a
                      # different PID. CONFIRMED 2026-08-19: the reporter read real
                      # config back over it (manually, before this constant existed) --
                      # a genuine round trip, not just a descriptor-shape match. The
                      # bind-content trigger (see PID_HID/PID_XID above) is not
                      # independently reconfirmed on this variant. See PROTOCOL.md
                      # "Device identities".
PID_XID_ZZZ = 0x105d  # baseline (no-HID-interface) identity on a G7 Pro
                      # "Zenless Zone Zero" edition, reported 2026-08-19 -- another
                      # community report, not this project's own hardware. Same
                      # story as PID_XID_TRIMODE: interface 1's descriptor shape
                      # matches PID_XID's exactly. CONFIRMED 2026-08-19: the
                      # reporter tested this branch directly and read real config
                      # back over it end to end -- a genuine round trip, not just a
                      # descriptor-shape match. The reporter initially took `xpad`
                      # binding and a working Steam pad here as evidence this PID was
                      # the "XInput identity" -- reasonably, under the pre-2026-08-29
                      # model, but not actually surprising at all once you know both
                      # PIDs are always-XInput (see has_hid_interface() -- it isn't
                      # evidence of a "personality" either way). See PROTOCOL.md
                      # "Device identities".
PID_DONGLE_TRIMODE = 0x1004   # the Tri-mode variant's 2.4GHz dongle counterpart --
                      # PID_XID_TRIMODE's counterpart, exactly one PID higher,
                      # same relationship PID_XID (109b) has to PID_DONGLE (109c).
                      # Reported and CONFIRMED 2026-08-19 by the same reporter as
                      # PID_XID_TRIMODE: found by hand ("vendor ID for white Tri-mode
                      # is 1004"), receiver connection worked after a brute constants.py
                      # edit -- a genuine round trip. The "+1" relationship held on two
                      # separate SKUs now (this project's own 109b/109c, and this one) --
                      # worth testing as a real pattern before more variants get their
                      # own hardcoded pair, but not assumed here yet. See PROTOCOL.md
                      # "Device identities".
PID_NATIVE = 0x1022   # the controller's own "default GameSir identity" -- a genuinely
                      # different, third identity, not affected by the PID_HID/
                      # PID_XID correction above. Reached by holding Menu+Share
                      # (GameSir's own manual calls this "Xbox button + Share",
                      # switching between "GIP (Xbox Gaming Device)" -- this PID --
                      # and "XInput"; also the same combo that clears a rare CMD_READ
                      # wedge). Two plain HID-class interfaces (no vendor-specific
                      # class 255 interface at all), confirmed via Steam's own
                      # controller test to lack vibration, unlike PID_HID/
                      # PID_XID which both have it. Neither interface answers the
                      # standard CMD_HEARTBEAT payload or streams anything unprompted
                      # -- found 2026-07-30, not the same protocol as PID_XID/
                      # PID_DONGLE and not reverse-engineered. Recognized here only so
                      # a user in this identity gets a clear "press Menu+Share to
                      # switch back" message instead of "no device found". See
                      # PROTOCOL.md "Device identities".
# PID_XID (and its per-variant equivalents) -> human-readable variant
# name. Real answer to roadmap item 36's original question ("how does
# software know which G7 Pro colourway is attached") -- not via the
# CMD=0x01 selector sweep that item spent six sessions mapping (all 256
# selectors now behaviorally known; none carries a colourway value anywhere
# in the space, see ROADMAP.md), but via this specific PID itself: three
# SKUs, three distinct PIDs, zero counterexamples (n=3, 2026-08-19 -- see
# VARIANT_PIDS.md). The original "it cannot be coming from USB descriptors"
# framing that started the sweep checked product string/bcdDevice/serial on
# this project's own single unit; it never had a second PID to compare
# against, because at the time there was only one. Deliberately keyed on
# PID_XID specifically (not PID_HID/PID_NATIVE/PID_DONGLE) purely because
# *that* PID is the one confirmed to vary per-variant with a real round trip
# on each -- not because it's any more special than PID_HID is (neither PID
# is a "vendor" identity, see the correction at the top of this file). The
# other PIDs aren't independently confirmed to vary per-variant the same
# way (see VARIANT_PIDS.md's "Gaps" section), and a dongle's own per-variant
# PID is its wired counterpart + 1 wherever confirmed, not looked up here
# separately.
VARIANT_NAMES = {
    PID_XID: "Shadow Ember",
    PID_XID_TRIMODE: "White Trimode",
    PID_XID_ZZZ: "Zenless Zone Zero",
}


def identify_variant(xid_pid: int) -> Optional[str]:
    """Human-readable colourway/edition name for a known PID_XID-style
    (baseline, no-HID-interface) PID, or None for one this project hasn't
    seen a confirmed report on yet
    (e.g. Dragon's Dogma 2 and WUCHANG editions -- see README.md "Hardware
    support"). None is a real, expected answer here, not a bug: this is a
    lookup against confirmed reports, not a formula that covers every PID
    GameSir might ever assign.
    """
    return VARIANT_NAMES.get(xid_pid)


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
