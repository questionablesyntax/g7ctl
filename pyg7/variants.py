"""Every USB identity a G7 Pro (or a known variant of one) can present,
and which GameSir Nexus-family devices are confirmed NOT to be a G7 Pro
at all.

Split out of constants.py 2026-09-01 -- all of it, including
PID_HID/PID_XID/PID_DONGLE/PID_NATIVE, which briefly stayed behind in
constants.py on the reasoning that they were "identity-class, used
regardless of which specific variant is attached" rather than per-SKU
data. Overruled directly: they're real PID values belonging to specific
hardware identities the same way every other variant's PIDs are (this
project's own reference hardware's "Shadow Ember" identity, specifically,
for PID_XID/PID_DONGLE) -- this module is where PID data lives, full
stop, not split by how many variants currently happen to share a value.
PID_HID and PID_NATIVE currently have exactly one known value across
every variant checked so far; that's a fact about the hardware, not a
reason to keep them somewhere else.

This module covers: a cosmetic name for a *known* baseline PID
(identify_variant()), and a way to recognize a PID confirmed to belong to
a *different* GameSir product sharing the same VID (identify_unsupported())
so device.py's finders can skip it before ever claiming an interface.

None of this is a detection mechanism. Real detection (find_hid_device()/
find_writable_device()/find_native_identity() in device.py) is fully
structural since the 2026-08-29 redesign and needs no PID at all -- a
brand-new, never-hardcoded G7 Pro variant still works. Everything in this
module is either a display label for a PID already confirmed to work, or
an explicit reject for a PID already confirmed NOT to.
"""
from typing import NamedTuple, Optional

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
                      # established about that transition. Currently the same
                      # value across every variant this project has confirmed
                      # (see KNOWN_VARIANTS below) -- shared, not per-SKU, as
                      # far as the evidence goes so far.
PID_XID = 0x109b      # "GameSir-G7 Pro" -- baseline XInput identity, no extra HID
                      # interface, for the "Shadow Ember" colourway specifically
                      # (this project's own reference hardware -- see
                      # KNOWN_VARIANTS below; every other confirmed variant has
                      # its own distinct baseline PID). Presented only when
                      # EVERY member of the trigger bundle above is at its
                      # baseline (all-native binds AND report rate below
                      # 1000Hz). Fully playable as a gamepad, and answers this
                      # project's whole config/telemetry protocol -- there is
                      # no gate between the two.
PID_DONGLE = 0x109c   # 2.4GHz wireless dongle counterpart to PID_XID (Shadow
                      # Ember's own dongle PID), same
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
                      # RESOLVED, same day (see FINDINGS.md's dongle-detection
                      # entry for the full account -- kept private-notes-only,
                      # not here): the dongle does split into an HID-shaped/
                      # baseline pair on its own USB side, the same way the
                      # wired connection does -- not a fixed single identity.
                      # That also settles the tension above: an idle dongle
                      # sitting at PID_HID is just this same split surfacing
                      # on the USB side, not evidence against it. Confirmed
                      # for the Tri-mode variant specifically; not directly
                      # reconfirmed for 109c, but there's no reason to expect
                      # this variant's firmware architecture to differ on
                      # this point.
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
                      # switch back" message instead of "no device found". Confirmed
                      # stable across the two variants independently checked so far
                      # (this project's own reference hardware and a G7 Pro ZZZ
                      # edition) -- shared, not per-SKU, as far as confirmed. See
                      # PROTOCOL.md "Device identities".

PID_XID_TRIMODE = 0x1003   # baseline (no-HID-interface) identity on at least
                           # one other G7 Pro variant -- reported 2026-08-19 from a
                           # community bug report, not this project's own hardware. Same
                           # interface-1 descriptor shape as PID_XID (isochronous
                           # alt-setting pair, no HID keyboard/mouse), just under a
                           # different PID. CONFIRMED 2026-08-19: the reporter read real
                           # config back over it (manually, before this constant existed) --
                           # a genuine round trip, not just a descriptor-shape match. The
                           # bind-content trigger (see PID_HID/PID_XID's own comment
                           # above) is not independently reconfirmed on this variant.
                           # See PROTOCOL.md "Device identities".
PID_XID_ZZZ = 0x105d       # baseline (no-HID-interface) identity on a G7 Pro
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


class Variant(NamedTuple):
    name: str
    xid_pid: int                  # baseline (no-HID) identity, wired
    dongle_pid: Optional[int]     # its 2.4GHz dongle counterpart, only if confirmed


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
# the baseline (XID-style) PID specifically (not PID_HID/PID_NATIVE) purely
# because *that* PID is the one confirmed to vary per-variant with a real
# round trip on each -- not because it's any more special than PID_HID is
# (neither PID is a "vendor" identity, see PID_HID's own correction above).
# The other PIDs aren't independently confirmed to vary per-variant the
# same way (see VARIANT_PIDS.md's "Gaps" section), which is also why a
# dongle_pid below is only filled in where confirmed, never derived from
# the "+1" pattern alone.
KNOWN_VARIANTS = (
    Variant("Shadow Ember", PID_XID, PID_DONGLE),
    Variant("White Trimode", PID_XID_TRIMODE, PID_DONGLE_TRIMODE),
    Variant("Zenless Zone Zero", PID_XID_ZZZ, None),
)


def identify_variant(xid_pid: int) -> Optional[str]:
    """Human-readable colourway/edition name for a known PID_XID-style
    (baseline, no-HID-interface) PID, or None for one this project hasn't
    seen a confirmed report on yet
    (e.g. Dragon's Dogma 2 and WUCHANG editions -- see README.md "Hardware
    support"). None is a real, expected answer here, not a bug: this is a
    lookup against confirmed reports, not a formula that covers every PID
    GameSir might ever assign.
    """
    for variant in KNOWN_VARIANTS:
        if variant.xid_pid == xid_pid:
            return variant.name
    return None


def is_known_dongle_pid(pid: int) -> bool:
    """Best-effort, display-only "does this look like a dongle" label for a
    *known* PID -- never gates behavior, and callers must not treat False
    here as "confirmed wired." Real wired-vs-dongle detection isn't
    possible at all (GameSir's own compiled firmware gives a wired baseline
    and its dongle counterpart the identical descriptor shape, confirmed
    2026-08-29 -- see FINDINGS.md for the full account). Defaults to False
    for any PID not on this list, including every future/unrecognized
    variant -- that's "no confident label," not "confirmed wired."

    Replaces the old XID_PID_CANDIDATES lookup (retired 2026-09-01) -- same
    data, minus the redundant wired-PID half (a wired PID can never satisfy
    this check anyway, since only dongle_pid fields are compared).
    """
    return any(variant.dongle_pid == pid for variant in KNOWN_VARIANTS)


# Other GameSir Nexus-family devices confirmed NOT to be a G7 Pro variant,
# keyed by PID. Empty today -- starts empty and grows only as a PID gets
# confirmed via a community report, same discipline as KNOWN_VARIANTS
# above: never guessed, never assumed from a naming/numbering pattern.
#
# README's "Hardware support" already names the products this project
# knows share VID 0x3537 (GameSir's own registered vendor ID, covering
# every device its Nexus app drives) but are explicitly out of scope: G7
# SE, G7 Pro 8K, T7 Pro Floral, T7 Pro Sugar Whirl, Tarantula Pro for Xbox,
# T7, Kaleid, Kaleid Flux. None of their PIDs are confirmed yet, so none
# are listed below.
#
# Absence from this dict is NOT confirmation of G7 Pro compatibility --
# see identify_unsupported()'s own docstring. Real detection stays fully
# permissive for anything not listed here, by design (owner's call,
# 2026-09-01): a genuinely new, unreported G7 Pro variant must keep working
# out of the box, the whole point of the 2026-08-29 detection redesign.
# This dict exists to intercept only PIDs already confirmed to be
# something else entirely.
UNSUPPORTED_PIDS: dict[int, str] = {
    # 0x____: "GameSir <product name>",
}


def identify_unsupported(pid: int) -> Optional[str]:
    """Product name for a PID confirmed to belong to a different GameSir
    Nexus-family device (not a G7 Pro), or None otherwise.

    None does NOT mean "confirmed G7 Pro" -- it also covers every
    genuinely unknown PID this project has no report on at all. Callers
    (device.py's finders) treat this as a reject list, not an allowlist:
    a None result lets a device through to the normal structural checks,
    same as it always has.
    """
    return UNSUPPORTED_PIDS.get(pid)
