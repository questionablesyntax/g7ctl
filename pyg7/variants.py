"""Which G7 Pro colourway/edition a PID belongs to, and which GameSir
Nexus-family devices are confirmed NOT to be a G7 Pro at all.

Split out of constants.py 2026-09-01. constants.py keeps the protocol's own
identity-class PIDs (PID_HID/PID_XID/PID_DONGLE/PID_NATIVE) -- used
throughout pyg7 regardless of which specific SKU is attached. Everything
here is per-SKU data: a cosmetic name for a *known* baseline PID
(identify_variant()), and now, a way to recognize a PID confirmed to
belong to a *different* GameSir product sharing the same VID
(identify_unsupported()) so device.py's finders can skip it before ever
claiming an interface.

Neither list is a detection mechanism. Real detection (find_hid_device()/
find_writable_device()/find_native_identity() in device.py) is fully
structural since the 2026-08-29 redesign and needs no PID at all -- a
brand-new, never-hardcoded G7 Pro variant still works. Everything in this
module is either a display label for a PID already confirmed to work, or
an explicit reject for a PID already confirmed NOT to.
"""
from typing import NamedTuple, Optional

from .constants import PID_DONGLE, PID_XID

PID_XID_TRIMODE = 0x1003   # baseline (no-HID-interface) identity on at least
                           # one other G7 Pro variant -- reported 2026-08-19 from a
                           # community bug report, not this project's own hardware. Same
                           # interface-1 descriptor shape as PID_XID (isochronous
                           # alt-setting pair, no HID keyboard/mouse), just under a
                           # different PID. CONFIRMED 2026-08-19: the reporter read real
                           # config back over it (manually, before this constant existed) --
                           # a genuine round trip, not just a descriptor-shape match. The
                           # bind-content trigger (see pyg7.constants's PID_HID/PID_XID
                           # comment) is not independently reconfirmed on this variant.
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
# (neither PID is a "vendor" identity, see pyg7.constants's correction).
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
