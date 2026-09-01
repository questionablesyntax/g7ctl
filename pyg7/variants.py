"""Every USB identity a G7 Pro (or a known variant of one) can present,
and which GameSir Nexus-family devices are confirmed NOT to be a G7 Pro
at all.

Split out of constants.py 2026-09-01 -- all PID data, no exceptions.
Every earlier attempt to carve out some PIDs as a separate "identity-class"
category (used regardless of variant, therefore belonging somewhere else)
was overruled directly: there is no such category. A PID is a fact about
one specific piece of hardware -- this project's own reference unit
("Shadow Ember") included -- not a more fundamental thing than a per-SKU
PID just because it currently happens to be confirmed shared across every
variant checked so far (true of 0x100a and 0x1022, see KNOWN_VARIANTS'
own comment below). No separate module-level PID_* constants either --
each variant's identities are inlined directly into its own KNOWN_VARIANTS
entry, not duplicated as a name-then-reference pair.

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


class Variant(NamedTuple):
    name: str
    xid_pid: int                  # baseline (no-HID) identity, wired
    dongle_pid: Optional[int]     # its 2.4GHz dongle counterpart, only if confirmed


# Every confirmed G7 Pro colourway/edition, keyed by its own baseline
# (no-HID-interface) PID -- real answer to roadmap item 36's original
# question ("how does software know which G7 Pro colourway is attached"),
# not via the CMD=0x01 selector sweep that item spent six sessions mapping
# (all 256 selectors now behaviorally known; none carries a colourway
# value anywhere in the space, see ROADMAP.md). Deliberately keyed on the
# baseline PID specifically -- that's the one confirmed to vary per-variant
# with a real round trip on each. See VARIANT_PIDS.md for the full report
# history and its "Gaps" section for what's still unconfirmed.
#
# Two more identities every variant below also answers, not tracked
# per-entry here because neither is confirmed to vary by SKU (both are
# 0x100a and 0x1022 on every variant checked so far -- a fact about the
# hardware, not assumed to hold for one this project hasn't seen yet):
#
# - 0x100a: presents the extra HID keyboard/mouse interface. Reached from
#   the baseline PID by the "gamesirapp" handshake whenever the active
#   profile needs it -- any keyboard/mouse bind (including Motion-as-Mouse)
#   or 1000Hz report rate, confirmed 2026-08-29 as two independent members
#   of one trigger bundle, not separate mechanisms. Neither PID is a
#   "vendor mode" a gamepad has to leave -- both are fully working XInput
#   identities, and the config/telemetry protocol answers identically on
#   either. See PROTOCOL.md "Device identities" for the full account of
#   this correction, and "The handshake" for what is and isn't established
#   about the transition itself.
# - 0x1022: the controller's own "default GameSir identity" ("GIP", not
#   XInput) -- a genuinely different, third identity. Reached by holding
#   Menu+Share (also the same combo that clears a rare CMD_READ wedge).
#   Two plain HID-class interfaces, no vendor-specific interface at all --
#   not the same protocol as anything else here, not reverse-engineered.
#   Recognized only so a user stuck there gets a clear "press Menu+Share"
#   message instead of "no device found". See PROTOCOL.md "Device
#   identities".
KNOWN_VARIANTS = (
    # Shadow Ember -- this project's own reference hardware. 0x109c
    # (dongle) was twice-corrected in 2026-07/2026-08 (see FINDINGS.md):
    # not a live pad on its own, and not handshake-free either -- an idle
    # dongle sits at 0x100a until handshaked, same as the wired baseline
    # does. A hypothesis that the dongle might present one PID fixed
    # regardless of the active profile's own trigger-bundle content was
    # raised and refuted the same day -- see FINDINGS.md's
    # dongle-detection entry for the full account.
    Variant("Shadow Ember", 0x109b, 0x109c),
    # White Trimode -- reported 2026-08-19, not this project's own
    # hardware, confirmed via a real read/write round trip. Dongle PID is
    # wired PID + 1, the same relationship Shadow Ember's own pair has --
    # confirmed as a real pattern on two SKUs now, not assumed for a
    # future one.
    Variant("White Trimode", 0x1003, 0x1004),
    # Zenless Zone Zero -- reported 2026-08-19, confirmed via a real round
    # trip. Dongle PID unconfirmed: the "+1" pattern would predict 0x105e,
    # but that's never been tested and isn't assumed here. See
    # VARIANT_PIDS.md "Gaps".
    Variant("Zenless Zone Zero", 0x105d, None),
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
