"""GUI-side observed/draft adapter -- DESIGN-SPEC.md section 7's
`ObservedSnapshot`/`DesiredDraft`, now built directly on the real
`FieldSpec` registry (`pyg7.field_spec`) rather than section 7's own
"hand-written map until step 3's FieldSpec registry exists" fallback --
that registry is exactly what Track S's S3 shipped.

S6 (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md): per-field marks and
"was" values, a touched-intent ledger independent of widgets, and the
rail edit count all read off this module, rather than each page
reinventing its own ad hoc touched-set the way VibrationView's
`_sliders_touched`/SettingsView's equivalent do today -- this is the
generalization of that same pattern, one page at a time, not a second
unrelated mechanism living alongside it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyg7.field_spec import Intent


def _get_path(state: dict | None, path: tuple[str, ...]) -> Any:
    """Mirrors `pyg7.workflow._get_path` exactly, duplicated rather than
    imported: this module has no need for `pyg7.workflow`'s own
    hardware-facing prepare/execute machinery, only `FieldSpec`'s own
    `compare()`, so importing it would be a dependency with no real use
    for it. `pyg7.workflow`'s own docstring on `_get_path` notes the
    same shape, one level up over a decoded state dict."""
    d = state
    for key in path:
        if d is None:
            return None
        d = d.get(key)
    return d


class ObservedSnapshot:
    """The state last confirmed against real hardware (a successful
    Read from Device) or an explicit Import -- DESIGN-SPEC.md section 7.
    Never mutated by an edit; only replaced wholesale by whichever
    MainWindow method just confirmed a new one (`set_read_finished`,
    `_on_import`).

    `confirmed=False` (nothing read or imported yet, the
    `default_state_dict()` scaffold) makes every `get()` return `None`
    -- unknown, never a fabricated "was" value against placeholder data.
    """

    def __init__(self, state: dict | None, confirmed: bool, imported: bool = False):
        self.state = state
        self.confirmed = confirmed
        # DESIGN-SPEC.md section 4 item 2: "Imported, not read from this
        # controller" -- an import confirms the state for editing, but
        # must never be shown as if it were agreement with hardware.
        self.imported = imported

    def get(self, path: tuple[str, ...]) -> Any:
        if not self.confirmed:
            return None
        return _get_path(self.state, path)


@dataclass(frozen=True)
class FieldMark:
    """One touched field -- the unit every per-field "was" mark, the
    rail edit count, and the draft bar's row list all read off.

    `observed` is the value `ObservedSnapshot.get(path)` returned at the
    moment this field was touched -- `None` if genuinely unknown (an
    unconfirmed snapshot, or a path it never read), shown as "Unknown"
    per DESIGN-SPEC.md section 4 item 5, never a fabricated prior value.
    """
    path: tuple[str, ...]
    field: Any  # FieldSpec | ButtonFieldSpec -- exposes compare()/plan_operation()
    desired: Any  # a concrete value or Intent.CLEAR -- never Intent.PRESERVE (that's not a touch)
    profile: int
    observed: Any


class DesiredDraft:
    """The touched-intent ledger -- independent of which widget touched
    it (DESIGN-SPEC.md section 10.2 item 2's "touched-intent ledger
    independent of widgets"). Scoped to one `ObservedSnapshot`: a
    profile switch with scoped intents (section 10.1 #5) hands a
    per-profile `DesiredDraft` a fresh snapshot and discards it, while a
    shared-scope draft (Shift, Dock) survives -- that scoping is owned
    by whoever constructs these, not by this class.
    """

    def __init__(self, observed: ObservedSnapshot):
        self._observed = observed
        self._marks: dict[tuple[str, ...], FieldMark] = {}

    @property
    def observed(self) -> ObservedSnapshot:
        return self._observed

    def touch(self, path: tuple[str, ...], field: Any, desired: Any, profile: int) -> None:
        """Record (or replace) an edit. `desired` must never be
        `Intent.PRESERVE` -- an untouched field was never approved to
        begin with, so it has no reason to be recorded here at all (the
        same rule `pyg7.workflow.ApprovedIntent` enforces at the
        prepare/execute boundary; enforced here too, at the point of
        touch, so a bad call fails where it's made)."""
        if desired is Intent.PRESERVE:
            raise ValueError(f"touch({path!r}): desired must not be Intent.PRESERVE")
        self._marks[path] = FieldMark(path, field, desired, profile, self._observed.get(path))

    def untouch(self, path: tuple[str, ...]) -> None:
        """Revert one field -- drops the touch. Does not itself move any
        widget; the caller re-reads `self.observed` and restores its own
        control's displayed value."""
        self._marks.pop(path, None)

    def is_touched(self, path: tuple[str, ...]) -> bool:
        return path in self._marks

    def mark_for(self, path: tuple[str, ...]) -> FieldMark | None:
        return self._marks.get(path)

    def discard(self) -> None:
        """Drop every touch -- a page- or scope-level "Discard changes."""
        self._marks.clear()

    @property
    def marks(self) -> tuple[FieldMark, ...]:
        return tuple(self._marks.values())

    @property
    def edit_count(self) -> int:
        return len(self._marks)

    def to_approved_intents(self) -> list:
        """Materialize every touch as a `pyg7.workflow.ApprovedIntent`,
        ready for `prepare()`/`execute()`. Imported here, not at module
        level -- keeps this module's own unit tests (pure data, no
        hardware) independent of `pyg7.workflow`'s import of
        `pyg7.session`."""
        from pyg7.workflow import ApprovedIntent
        return [
            ApprovedIntent(path=m.path, desired=m.desired, field=m.field, profile=m.profile)
            for m in self._marks.values()
        ]
