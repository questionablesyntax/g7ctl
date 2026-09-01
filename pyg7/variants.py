"""Every USB identity a G7 Pro (or a known variant of one) can present,
and which GameSir Nexus-family devices are confirmed NOT to be a G7 Pro
at all.

Every USB PID this project knows about lives here, not in constants.py --
a PID is a fact about one specific piece of hardware, not something to
split across modules by how many variants happen to share a value. This
project's own reference unit ("Shadow Ember") is one variant among
several, not a more fundamental case than any other, even though its
`0x100a`/`0x1022` values are currently confirmed shared with at least one
other variant (NOT with every variant this project has data on -- see
KNOWN_VARIANTS' own comment for exactly which values are confirmed for
which SKU and which are real, flagged gaps). No separate module-level
PID_* constants either -- each variant's identities are inlined directly
into its own KNOWN_VARIANTS entry, not declared once and referenced
from there.

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
    xid_pid: int                  # baseline (no-HID) identity, wired -- always confirmed,
                                   # this is what a variant is keyed on below
    dongle_pid: Optional[int]     # 2.4GHz dongle counterpart, only if confirmed
    hid_pid: Optional[int] = None      # HID-keyboard/mouse-presenting identity, only if confirmed
    native_pid: Optional[int] = None   # native/GIP identity, only if confirmed


# Every confirmed G7 Pro colourway/edition. Keyed for lookup on xid_pid
# specifically -- real answer to roadmap item 36's original question
# ("how does software know which G7 Pro colourway is attached"), not via
# the CMD=0x01 selector sweep that item spent six sessions mapping (all
# 256 selectors now behaviorally known; none carries a colourway value
# anywhere in the space, see ROADMAP.md). xid_pid is the one confirmed to
# vary per-variant with a real round trip on each, and the only field
# guaranteed present -- hid_pid/dongle_pid/native_pid are each None where
# genuinely unconfirmed, per VARIANT_PIDS.md's own "Gaps" section, never
# guessed from a pattern (dongle PID = wired PID + 1 is a real, confirmed
# pattern on two SKUs, but still not assumed for an unconfirmed one).
#
# hid_pid and native_pid currently collide across variants where they ARE
# confirmed (0x100a: Shadow Ember + White Trimode; 0x1022: Shadow Ember +
# Zenless Zone Zero) -- identify_variant() treats that honestly, see its
# own docstring. Both identities are real and well-understood regardless:
# 0x100a presents the extra HID keyboard/mouse interface, reached from the
# baseline PID by the "gamesirapp" handshake whenever the active profile
# needs it (any keyboard/mouse bind, or 1000Hz report rate -- confirmed
# 2026-08-29 as two independent members of one trigger bundle). 0x1022 is
# the controller's own "default GameSir identity" ("GIP", not XInput), a
# genuinely different third identity reached by holding Menu+Share. See
# PROTOCOL.md "Device identities" for the full account of both.
KNOWN_VARIANTS = (
    # Shadow Ember -- this project's own reference hardware, every field
    # confirmed. 0x109c (dongle) was twice-corrected in 2026-07/2026-08
    # (see FINDINGS.md): not a live pad on its own, and not handshake-free
    # either -- an idle dongle sits at 0x100a until handshaked, same as
    # the wired baseline does. A hypothesis that the dongle might present
    # one PID fixed regardless of the active profile's own trigger-bundle
    # content was raised and refuted the same day -- see FINDINGS.md's
    # dongle-detection entry for the full account.
    Variant("Shadow Ember", xid_pid=0x109b, dongle_pid=0x109c, hid_pid=0x100a, native_pid=0x1022),
    #
    # White Trimode -- reported 2026-08-19, not this project's own
    # hardware, xid/dongle/hid all confirmed via real round trips. Dongle
    # PID is wired PID + 1, the same relationship Shadow Ember's own pair
    # has -- confirmed as a real pattern on two SKUs now, not assumed for
    # a future one. Native PID never observed for this unit -- see
    # VARIANT_PIDS.md "Gaps", not assumed to match Shadow Ember's.
    #
    Variant("White Trimode", xid_pid=0x1003, dongle_pid=0x1004, hid_pid=0x100a),
    #
    # Zenless Zone Zero -- reported 2026-08-19, xid/native confirmed via a
    # real round trip. Dongle PID unconfirmed: the "+1" pattern would
    # predict 0x105e, but that's never been tested and isn't assumed
    # here. HID PID also never observed for this unit -- see
    # VARIANT_PIDS.md "Gaps", not assumed to match Shadow Ember's.
    Variant("Zenless Zone Zero", xid_pid=0x105d, dongle_pid=None, native_pid=0x1022),
)


def identify_variant(pid: int) -> Optional[str]:
    """Human-readable colourway/edition name for a known PID, or None for
    one this project hasn't seen a confirmed report on yet (e.g. Dragon's
    Dogma 2 and WUCHANG editions -- see README.md "Hardware support").
    None is a real, expected answer here, not a bug: this is a lookup
    against confirmed reports, not a formula that covers every PID GameSir
    might ever assign.

    Tries the baseline (xid) PID first -- always unambiguous, since that's
    what a variant is keyed on. Falls back to hid_pid/native_pid (added
    2026-09-01, so a controller caught sitting at its HID or native
    identity -- not yet handshaked to baseline -- still resolves), but
    ONLY when exactly one known variant shares that value. Both currently
    collide across multiple variants where confirmed at all (see
    KNOWN_VARIANTS' own comment) -- returning one name out of a real
    collision would be actively wrong, worse than the honest "don't know
    yet" this returns instead. Not dead code even though today's data
    never resolves through this path: it exists so a future variant whose
    hid_pid or native_pid turns out to be uniquely its own resolves
    immediately, with no code change needed.
    """
    for variant in KNOWN_VARIANTS:
        if variant.xid_pid == pid:
            return variant.name
    matches = {v.name for v in KNOWN_VARIANTS if pid in (v.hid_pid, v.native_pid)}
    return matches.pop() if len(matches) == 1 else None


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
# permissive for anything not listed here, by design: a genuinely new,
# unreported G7 Pro variant must keep working out of the box, the whole
# point of the 2026-08-29 detection redesign.
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
