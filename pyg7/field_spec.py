"""Declarative per-field protocol registry -- `FieldSpec`.

This is S3 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S),
following the agreed migration order, not the bigger
one-shot version IMPLEMENTATION-PLAN.md's own S3 bullet reads like in
isolation: convert ONE simple category to a declarative field spec first
(report rate, chosen over vibration -- single scalar, no packed bits, no
coupled fields), gate it with unit + capture-replay + hardware
noninterference tests, and only then repeat category by category,
buttons/motion last as the most irregular. This file is that first,
narrow slice -- not a field contract map for every field yet. Each later
category earns its own FieldSpec only after passing its own three gates,
same as this one.

Replaces the inline "is it declared, does it match baseline" logic
`_build_steps()` used to hand-write per field with one declarative
description per field: identity, how to decode its current value off a
profile blob (knownness), how to build the Operation that writes it, and
how to compare two values canonically. `Intent.PRESERVE`/`Intent.CLEAR`
make "not declared" and "declared, clear it" two distinct, explicit
values instead of both collapsing to `None` -- the same conflation S2
just fixed ad hoc for motion's `allow_none` fields; this is the first use
of a real type for it instead of another one-off guard.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable

from . import buttons, dock_settings, dpad_options, motion, report_rate, sticks, triggers, vibration
from .curves import parse_points as _parse_points
from .operations import Operation


class Intent(enum.Enum):
    """A desired value that isn't a concrete setting value.

    PRESERVE: not declared -- leave whatever the device currently has
    alone. CLEAR: declared, and the declaration is "unset this,"
    distinct from any concrete value. A field with no desired Intent at
    all just carries its real value directly (an int, str, bool, ...),
    not a third Intent member -- this is deliberately not a tri-state
    enum covering every case; the conflation this was built to fix is
    "unset vs. preserve," not "set vs. everything else."
    """
    PRESERVE = "preserve"
    CLEAR = "clear"


Desired = Any  # a concrete value, Intent.PRESERVE, or Intent.CLEAR


@dataclass(frozen=True)
class FieldSpec:
    """One field's full protocol contract: identity, how to read its
    current value (knownness), how to write a new one (as an Operation,
    S1's own inspectable-data write), and how to compare two values.

    `decode(blob) -> value | None` mirrors this field's own
    `decode_settings()` convention elsewhere in this codebase: `None`
    means genuinely unknown/unreadable from that blob, not a real value.
    `compare` defaults to plain equality; a field needing a canonical
    form first (e.g. curve points, see `state.py`'s `_points_key()`)
    passes one that normalizes both sides before comparing -- the "one
    comparator used everywhere" the plan asks for is enforced by routing
    every FieldSpec-backed comparison through this, not by every field
    happening to already use `==` correctly.
    """
    name: str
    operation_kind: str
    decode: Callable[[bytes], Any | None]
    build_args: Callable[[Any, int], tuple] = field(default=lambda value, profile: (value,))
    build_kwargs: Callable[[int], dict] = field(default=lambda profile: {"profile": profile})
    compare: Callable[[Any, Any], bool] = field(default=lambda a, b: a == b)
    supports_clear: bool = False

    def plan_operation(self, desired: Desired, baseline: Any | None, profile: int) -> Operation | None:
        """The one place "should this write happen, and with what" gets
        decided for this field -- what `_build_steps()` used to inline
        per field. Returns `None` for "skip, nothing to do."""
        if desired is Intent.PRESERVE:
            return None
        if desired is Intent.CLEAR:
            if not self.supports_clear:
                raise ValueError(f"field {self.name!r} has no clear value to write")
            desired = None  # this field's own clear sentinel on the wire, not "skip"
        if baseline is not None and self.compare(baseline, desired):
            return None
        return Operation(self.operation_kind, self.build_args(desired, profile), self.build_kwargs(profile))


@dataclass(frozen=True)
class CoupledFieldSpec:
    """A write built from more than one sub-field sharing one wire value
    -- the "coupled writes" case (vibration's force/sync flags: one
    byte, two independent booleans). Each sub-field's desired value is
    independently `Intent.PRESERVE` or a real value; an undeclared
    sub-field's own BASELINE value carries forward instead of a fixed
    default -- the same rule `_vibration_steps()` already enforced
    inline before this existed (real bug, found 2026-09-01: the
    undeclared half used to silently write as "off" instead of
    preserving whatever it actually was). `desired`/`baseline` are dicts
    keyed by `sub_fields`, not single values -- the one real difference
    from plain `FieldSpec`.

    The caller decides whether to call `plan_operation()` at all: unlike
    `FieldSpec`, this doesn't special-case "every sub-field is PRESERVE"
    as "skip, don't count" versus "skip, baseline matched" -- a coupled
    field's caller already knows (from the surrounding state dict) which
    case it's in before it has a baseline to compare against, so forcing
    that distinction through this class's return value alone would lose
    it. See `_vibration_steps()`'s flags loop for the shape this is
    meant to be called in.
    """
    name: str
    operation_kind: str
    sub_fields: tuple[str, ...]
    combine: Callable[[dict], Any]
    build_args: Callable[[Any, int], tuple]
    build_kwargs: Callable[[int], dict] = field(default=lambda profile: {"profile": profile})
    compare: Callable[[Any, Any], bool] = field(default=lambda a, b: a == b)

    def plan_operation(self, desired: dict, baseline: dict, profile: int) -> Operation | None:
        resolved = {
            sf: (baseline.get(sf) if desired.get(sf) is Intent.PRESERVE else desired[sf])
            for sf in self.sub_fields
        }
        combined = self.combine(resolved)
        has_baseline = any(baseline.get(sf) is not None for sf in self.sub_fields)
        if has_baseline and self.compare(self.combine(baseline), combined):
            return None
        return Operation(self.operation_kind, self.build_args(combined, profile), self.build_kwargs(profile))


def _vibration_flags_field(side: str) -> CoupledFieldSpec:
    """One side's Force+Sync pair -- bit0=Force, bit1=Sync on one byte
    (vibration.py's own module docstring), written through
    vibration.set_value()'s "on,off"-style string form, same wire shape
    _vibration_steps() already produced inline."""
    def _combine(resolved: dict) -> str:
        return f"{'on' if resolved['force'] else 'off'},{'on' if resolved['sync'] else 'off'}"

    return CoupledFieldSpec(
        name=f"{side}_trigger_flags",
        operation_kind="vibration_setting",
        sub_fields=("force", "sync"),
        combine=_combine,
        build_args=lambda value, profile, _side=side: (f"{_side}_trigger_flags", value),
    )


# The coupled half of vibration's migration, decided rather than left
# open (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md's S3 status note
# tracked this as an open question until now): CoupledFieldSpec above,
# applied to both sides.
VIBRATION_FLAGS_FIELDS = {side: _vibration_flags_field(side) for side in ("left", "right")}


# S3's first FieldSpec migration (the agreed sequencing): report rate chosen over vibration -- simplest
# real category, one scalar, no packed bits, no clear semantics (a report
# rate is always some rate; there's no "unset" to declare, hence
# supports_clear defaults to False). `build_args`/`build_kwargs` are
# FieldSpec's own defaults -- `(value,)` and `{"profile": profile}` --
# already match `report_rate.set_value()`'s signature exactly, so this
# doesn't override either. Lives here, not in report_rate.py itself, so
# that module never has to import this one -- see operations.py's
# docstring for the cycle that would otherwise create.
REPORT_RATE_FIELD = FieldSpec(
    name="report_rate_hz",
    operation_kind="report_rate",
    decode=lambda blob: report_rate.decode_settings(blob)["report_rate_hz"],
)


def _vibration_level_field(name: str) -> FieldSpec:
    """One of vibration's four simple grip/trigger levels -- same shape
    as report rate (a scalar, no clear semantics: 0 is a real, valid
    level, not an unset marker). `vibration.set_value()` takes the
    setting's name as its own argument, unlike report_rate.set_value(),
    so build_args has to supply it -- the one place this differs from
    REPORT_RATE_FIELD."""
    return FieldSpec(
        name=name,
        operation_kind="vibration_setting",
        decode=lambda blob: vibration.decode_settings(blob)[name],
        build_args=lambda value, profile, _name=name: (_name, value),
    )


# Second category migrated, second half still open: vibration's four
# grip/trigger LEVELS (simple scalars) move to FieldSpec here; the two
# packed force/sync flag bytes do not yet -- each one is written from
# TWO separate state-dict fields sharing one wire byte (see vibration.py
# module docstring: bit0=Force, bit1=Sync), which is exactly the "coupled
# writes" case Track S's own plan flags as needing a real design
# decision (does a coupled FieldSpec take a tuple desired value? does it
# need to see its sibling field's own baseline to fill in an undeclared
# half, the way _vibration_steps() already does today?). Migrating the
# four easy fields now and leaving the packed pair on the existing
# inline path is deliberate, not an oversight -- see
# Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md's S3 status note.
VIBRATION_LEVEL_FIELDS = {
    name: _vibration_level_field(name)
    for name in ("left_grip", "right_grip", "left_trigger", "right_trigger")
}


def _nested_get(d: dict | None, path: tuple[str, ...]) -> Any | None:
    """Walk a decode_settings()-shaped nested dict by a path of keys,
    e.g. ("curve", "preset") or ("advanced_mapping", "output_mode") --
    every field below reads its own decoded value this way rather than
    each writing its own one-off lambda."""
    for key in path:
        if d is None:
            return None
        d = d.get(key)
    return d


def _points_key(points: Any) -> str | None:
    """Mirrors state.py's own `_points_key()` exactly (can't import it --
    state.py imports this module, not the other way; see operations.py's
    docstring for the cycle that would create). Curve points arrive in
    different shapes (lists of lists from a device read, tuples or a
    flat list from hand-edited JSON) that compare unequal by `==` even
    when they mean the same curve -- this is the canonical comparator
    `compare=` exists for."""
    if points is None:
        return None
    return ",".join(f"{x},{y}" for x, y in _parse_points(points))


def _side_field(category_module, operation_kind: str, side: str, setting: str,
                 decode_path: tuple[str, ...], compare=lambda a, b: a == b) -> FieldSpec:
    """One side's single setting for Sticks or Triggers -- both category
    modules share the same `set_value(session, side, setting, value,
    profile=profile)` signature and the same nested decode_settings()
    shape, so one factory covers both rather than writing Sticks' and
    Triggers' field tables by hand twice."""
    return FieldSpec(
        name=f"{side}_{setting}",
        operation_kind=operation_kind,
        decode=lambda blob, _side=side, _path=decode_path:
            _nested_get(category_module.decode_settings(blob, _side), _path),
        build_args=lambda value, profile, _side=side, _setting=setting: (_side, _setting, value),
        compare=compare,
    )


# Third category migrated: Sticks and Triggers' simple, non-coupled
# fields (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S).
# `curve_points` and Sticks' `direction_bindings` are migrated too (both
# below) but kept separate from this table: `curve_points` is only ever
# scheduled when its curve's own preset is "custom" (a named preset's
# write already carries its own points -- see `_stick_steps()`'s own
# comment on the real bug this ordering fixes), which is a decision the
# caller makes before calling plan_operation() at all, same shape as
# vibration's "both halves undeclared" guard; `direction_bindings` is
# already a single combined value by the time it would reach a
# FieldSpec (state.py builds the comma-joined string first), so it needs
# its own decode to match that shape rather than fitting this table's
# plain per-setting-name pattern.
_STICK_SIMPLE_SETTINGS = {
    "trajectory": ("trajectory",),
    "curve": ("curve", "preset"),
    "deadzone_initial": ("deadzone", "initial"),
    "deadzone_max": ("deadzone", "max"),
    "anti_deadzone_initial": ("anti_deadzone", "initial"),
    "anti_deadzone_max": ("anti_deadzone", "max"),
    "resolution_bits": ("resolution_bits",),
    "output_mode": ("advanced_mapping", "output_mode"),
    "invert_x": ("advanced_mapping", "invert_x"),
    "invert_y": ("advanced_mapping", "invert_y"),
    "sensitivity": ("advanced_mapping", "sensitivity"),
    "overlap_area": ("advanced_mapping", "overlap_area"),
    "dpi": ("advanced_mapping", "dpi"),
}

STICK_FIELDS: dict[str, dict[str, FieldSpec]] = {
    side: {
        setting: _side_field(sticks, "stick_setting", side, setting, path)
        for setting, path in _STICK_SIMPLE_SETTINGS.items()
    }
    for side in ("left", "right")
}
STICK_FIELDS["left"]["curve_points"] = _side_field(
    sticks, "stick_setting", "left", "curve_points", ("curve", "points"), compare=lambda a, b: _points_key(a) == _points_key(b))
STICK_FIELDS["right"]["curve_points"] = _side_field(
    sticks, "stick_setting", "right", "curve_points", ("curve", "points"), compare=lambda a, b: _points_key(a) == _points_key(b))


def _stick_direction_bindings_field(side: str) -> FieldSpec:
    """`direction_bindings` is already one comma-joined string
    (`up,down,left,right,ring`, "ff" for an unbound zone) by the time
    `_stick_steps()` builds it -- decode reconstructs the same shape from
    `sticks.decode_settings()` so this field's "current value" means the
    same thing on both sides of the comparison."""
    zones = ("up", "down", "left", "right", "ring")

    def _decode(blob: bytes, _side=side) -> str | None:
        db = _nested_get(sticks.decode_settings(blob, _side), ("advanced_mapping", "direction_bindings"))
        if db is None:
            return None
        return ",".join(db.get(z) or "ff" for z in zones)

    return FieldSpec(
        name=f"{side}_direction_bindings",
        operation_kind="stick_setting",
        decode=_decode,
        build_args=lambda value, profile, _side=side: (_side, "direction_bindings", value),
    )


STICK_FIELDS["left"]["direction_bindings"] = _stick_direction_bindings_field("left")
STICK_FIELDS["right"]["direction_bindings"] = _stick_direction_bindings_field("right")

_TRIGGER_SIMPLE_SETTINGS = {
    "hair_trigger_mode": ("hair_trigger_mode",),
    "curve": ("curve", "preset"),
    "deadzone_initial": ("deadzone", "initial"),
    "deadzone_max": ("deadzone", "max"),
    "anti_deadzone_initial": ("anti_deadzone", "initial"),
    "anti_deadzone_max": ("anti_deadzone", "max"),
}

TRIGGER_FIELDS: dict[str, dict[str, FieldSpec]] = {
    side: {
        setting: _side_field(triggers, "trigger_setting", side, setting, path)
        for setting, path in _TRIGGER_SIMPLE_SETTINGS.items()
    }
    for side in ("left", "right")
}
TRIGGER_FIELDS["left"]["curve_points"] = _side_field(
    triggers, "trigger_setting", "left", "curve_points", ("curve", "points"), compare=lambda a, b: _points_key(a) == _points_key(b))
TRIGGER_FIELDS["right"]["curve_points"] = _side_field(
    triggers, "trigger_setting", "right", "curve_points", ("curve", "points"), compare=lambda a, b: _points_key(a) == _points_key(b))


# Fourth category migrated: D-pad options -- two simple per-profile
# booleans (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S).
# `dpad_options.set_value()`'s own `setting` name ("diagonal_lock")
# differs from the state dict's top-level key ("dpad_diagonal_lock") --
# `decode` reads the latter out of `decode_settings()`, `build_args`
# writes the former, same split `_build_steps()` already had.
DPAD_FIELDS = {
    "dpad_diagonal_lock": FieldSpec(
        name="dpad_diagonal_lock",
        operation_kind="dpad_option",
        decode=lambda blob: dpad_options.decode_settings(blob)["dpad_diagonal_lock"],
        build_args=lambda value, profile: ("diagonal_lock", value),
    ),
    "swap_stick_dpad": FieldSpec(
        name="swap_stick_dpad",
        operation_kind="dpad_option",
        decode=lambda blob: dpad_options.decode_settings(blob)["swap_stick_dpad"],
        build_args=lambda value, profile: ("swap_stick_dpad", value),
    ),
}


# Fifth category migrated: Dock settings -- genuinely device-global, no
# `profile=` argument at all (dock_settings.py's own module docstring),
# unlike every other category so far. `build_kwargs` overrides
# FieldSpec's `{"profile": profile}` default with an empty dict for
# exactly this reason.
DOCK_FIELDS = {
    "dock_led_brightness": FieldSpec(
        name="dock_led_brightness",
        operation_kind="dock_setting",
        decode=lambda blob: dock_settings.decode_settings(blob)["dock_led_brightness"],
        build_args=lambda value, profile: ("brightness", value),
        build_kwargs=lambda profile: {},
    ),
    "dock_auto_on_off": FieldSpec(
        name="dock_auto_on_off",
        operation_kind="dock_setting",
        decode=lambda blob: dock_settings.decode_settings(blob)["dock_auto_on_off"],
        build_args=lambda value, profile: ("auto_on_off", value),
        build_kwargs=lambda profile: {},
    ),
}


# Sixth category migrated: Motion -- the first of the two "most
# irregular" categories the agreed ordering saves for last (Projects/g7ctl/
# redesign/IMPLEMENTATION-PLAN.md, Track S). Shares sticks.py/
# triggers.py's `set_value(session, side, setting, value, profile)`
# signature, so the same `_side_field()` factory covers its plain
# fields -- `activate_method`, `x_axis_output_mode`, `curve` (preset),
# `deadzone`/`anti_deadzone` x2, `invert_y`, `invert_yaw`,
# `sensitivity_scale`, `output`, `overlap_area`. Three things don't fit
# that plain pattern:
#
# 1. `activate_button` and the four `direction_up/down/left/right`
#    zones have a REAL clear value (0xFF on the wire, decoded back as
#    Python `None` -- motion.py's own `_resolve_keycode_or_unbound()`),
#    so `supports_clear=True` and `Intent.CLEAR` apply -- the first
#    fields in this migration that actually use that machinery for real
#    instead of just being exercised by a generic unit test.
# 2. Those same fields have a genuine double meaning of `None` FieldSpec's
#    plain two-argument `plan_operation(desired, baseline, profile)`
#    can't disambiguate on its own: `baseline=None` means "no known
#    baseline, write unconditionally" for every other field migrated so
#    far, but for these fields the device's real, legitimate "unbound"
#    state ALSO decodes to `None` -- indistinguishable from "unknown" at
#    the single-value level. `_motion_steps()`'s own `_add()` resolves
#    this the same way it already did before this migration: by keeping
#    `has_baseline` (whether the OUTER baseline dict exists at all, not
#    just this one field's value) as the caller-side signal
#    `plan_operation()` doesn't have, same shape as every other
#    caller-must-decide-first case in this migration (vibration's
#    both-undeclared guard, the absent-key guards from S2).
# 3. `invert_roll` is Aim-only (motion.py's module docstring: Tilt has
#    no equivalent control, and `motion.set_value()` raises if asked) --
#    added only to `MOTION_FIELDS["aim"]`, not built uniformly for both
#    sides the way every other field here is.
_MOTION_SIMPLE_SETTINGS = {
    "activate_method": ("activate_method",),
    "x_axis_output_mode": ("x_axis_output_mode",),
    "curve": ("curve", "preset"),
    "deadzone_initial": ("deadzone", "initial"),
    "deadzone_max": ("deadzone", "max"),
    "anti_deadzone_initial": ("anti_deadzone", "initial"),
    "anti_deadzone_max": ("anti_deadzone", "max"),
    "invert_y": ("invert_y",),
    "invert_yaw": ("invert_yaw",),
    "sensitivity_scale": ("sensitivity_scale",),
    "output": ("output",),
    "overlap_area": ("overlap_area",),
}

MOTION_FIELDS: dict[str, dict[str, FieldSpec]] = {
    side: {
        setting: _side_field(motion, "motion_setting", side, setting, path)
        for setting, path in _MOTION_SIMPLE_SETTINGS.items()
    }
    for side in ("aim", "tilt")
}
for _side in ("aim", "tilt"):
    MOTION_FIELDS[_side]["curve_points"] = _side_field(
        motion, "motion_setting", _side, "curve_points", ("curve", "points"),
        compare=lambda a, b: _points_key(a) == _points_key(b))
    MOTION_FIELDS[_side]["activate_button"] = FieldSpec(
        name=f"{_side}_activate_button",
        operation_kind="motion_setting",
        decode=lambda blob, _s=_side: _nested_get(motion.decode_settings(blob, _s), ("activate_button",)),
        build_args=lambda value, profile, _s=_side: (_s, "activate_button", value),
        supports_clear=True,
    )
    for _zone in ("up", "down", "left", "right"):
        _setting_name = f"direction_{_zone}"
        MOTION_FIELDS[_side][_setting_name] = FieldSpec(
            name=f"{_side}_{_setting_name}",
            operation_kind="motion_setting",
            decode=lambda blob, _s=_side, _z=_zone:
                _nested_get(motion.decode_settings(blob, _s), ("direction_bindings", _z)),
            build_args=lambda value, profile, _s=_side, _sn=_setting_name: (_s, _sn, value),
            supports_clear=True,
        )
MOTION_FIELDS["aim"]["invert_roll"] = _side_field(motion, "motion_setting", "aim", "invert_roll", ("invert_roll",))


@dataclass(frozen=True)
class ButtonFieldSpec:
    """One button's binding on one layer (default or Shift) -- the last
    and most irregular category (the agreed ordering). Deliberately NOT a plain `FieldSpec`:
    `remap()` and `unbind()` are genuinely different wire operations
    (allocate-form marker+keycode vs. a single clear byte -- see
    `buttons.py`'s own module docstring), not the same function called
    with a sentinel value the way every `Intent.CLEAR` field elsewhere
    in this migration works. `decode()` reads the WHOLE button table at
    once (`buttons.decode_button_table()`) and picks this one button out
    -- `buttons.py` has no per-button decode, unlike every other category
    module migrated so far.

    No real use for `baseline`, unlike `FieldSpec`/`CoupledFieldSpec`:
    buttons were ALREADY immune to the "undeclared vs. None" ambiguity
    S2/Motion both had to solve, because an undeclared button never even
    reaches this class -- `state["buttons"][layer]` is a sparse dict
    (buttons.py's own convention: an unmentioned button is never
    touched; a button present with value `None` is a real unbind), so
    the caller's own dict iteration already only ever calls
    `plan_operation()` for a button that's genuinely declared. The
    skip-vs-write decision is made entirely by the caller -- originally
    only `_build_steps()`'s own baseline-diffing loop, now also
    `pyg7.workflow.prepare()`'s classification for the per-field draft
    path (S6) -- before this is ever called; this only ever builds the
    write once that decision is already "yes".

    `plan_operation()` still takes a `baseline` parameter, accepted and
    ignored, purely so `pyg7.workflow.execute()` can call every field
    type (`FieldSpec`/`CoupledFieldSpec`/`ButtonFieldSpec`) through the
    exact same `plan_operation(desired, baseline, profile)` shape
    without special-casing this one -- added when Buttons' own S6 slice
    needed `ButtonFieldSpec` to work through `prepare()`/`execute()` for
    the first time and found the old 2-argument form incompatible with
    `execute()`'s uniform 3-argument call.
    """
    button: str
    shift: bool
    decode: Callable[[bytes], str | None]

    def plan_operation(self, desired: Desired, baseline: Any, profile: int) -> Operation:
        button_id = buttons.resolve_button_id(self.button)
        if desired is Intent.CLEAR:
            return Operation("button_unbind", (button_id,), {"profile": profile, "shift": self.shift})
        keycode = buttons.resolve_keycode(desired)
        return Operation("button_remap", (button_id, keycode), {"profile": profile, "shift": self.shift})


BUTTON_FIELDS: dict[str, dict[str, ButtonFieldSpec]] = {
    layer: {
        btn: ButtonFieldSpec(
            button=btn,
            shift=(layer == "shift"),
            decode=lambda blob, _btn=btn: buttons.decode_button_table(blob).get(_btn),
        )
        for btn in buttons.KNOWN_BUTTON_IDS
    }
    for layer in ("default", "shift")
}


# Continuous Trigger: a plain boolean flag per button, independent of
# the binding itself (buttons.set_continuous_trigger()'s own docstring:
# "does not allocate or free a slot the way remap()/unbind() do") -- a
# genuinely plain FieldSpec, not a ButtonFieldSpec, since there's no
# allocate/unbind dichotomy here. Default layer only, matching the
# existing state-dict schema (`state.get("continuous_trigger")` has no
# per-layer shape) -- untested/unsupported on Shift, not invented here.
CT_FIELDS = {
    btn: FieldSpec(
        name=f"continuous_trigger_{btn}",
        operation_kind="continuous_trigger",
        decode=lambda blob, _btn=btn: buttons.decode_continuous_triggers(blob).get(_btn),
        build_args=lambda value, profile, _btn=btn: (_btn, value),
    )
    for btn in buttons.BUTTON_TABLE_SLOTS
    if btn
}
