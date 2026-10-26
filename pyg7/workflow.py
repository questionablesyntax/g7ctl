"""S4: prepare / execute, bound to a job ID, draft revision and
connection generation (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md,
Track S). Built from the feasibility review's own concrete
recommendation (reviews/FEASIBILITY.md's B2/M1), not invented from the
plan's own terser bullet:

    "define two worker commands, prepare and execute, with immutable
    job ID, draft revision, explicit target scopes and connection
    generation. Preparation reads fresh state without replacing the
    draft; three-way comparison distinguishes untouched external
    changes, conflicts and already-satisfied intent... Execution must
    be bound to that revision/target and reject stale preparation
    after editing, release, reconnect or profile change... Materialize
    a complete candidate from fresh state plus approved intents."

This is the fix for B2 ("Today's Sync Now can revert changes made on
the controller"): instead of diffing the WHOLE displayed state against
a fresh baseline (today's `write_state(..., baseline=...)` behaviour,
still used as-is by the CLI and by anything not yet moved onto this),
`execute()` only ever writes the fields the caller explicitly approved
(`ApprovedIntent`), and only once `prepare()` has confirmed each one
against a FRESH re-read, not the stale draft-time baseline.

Reuses S1-S3's `Operation`/`FieldSpec` machinery directly rather than
building a second write planner -- `FEASIBILITY.md`'s own words:
"materialize a complete candidate... or use a newly proven typed
planner. Never derive executable intent by parsing display labels from
closure steps." `FieldSpec.plan_operation()` already does exactly the
per-field "does this need a write" decision this module needs; the only
things prepare()/execute() add are the three-way classification (for
review/reporting) and the job/revision/generation staleness guard.
"""
from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .field_spec import Intent
from .operations import Operation
from .session import VendorSession


class Classification(enum.Enum):
    """What prepare() found for one approved intent, comparing the
    original draft-time baseline against a FRESH re-read."""
    ALREADY_SATISFIED = "already_satisfied"  # fresh already equals desired -- nothing to write
    CLEAN = "clean"                          # fresh matches the original baseline -- safe to write
    CONFLICT = "conflict"                    # fresh differs from BOTH baseline and desired -- something else changed


def _get_path(state: dict | None, path: tuple[str, ...]) -> Any:
    """Walk a state dict (read_state()/load_state() shape) by a path of
    keys, e.g. ("sticks", "left", "trajectory") or ("report_rate_hz",).
    Mirrors field_spec.py's `_nested_get()` for blobs -- this is the
    same idea one level up, over a decoded state dict instead of raw
    bytes."""
    d = state
    for key in path:
        if d is None:
            return None
        d = d.get(key)
    return d


@dataclass(frozen=True)
class ApprovedIntent:
    """One field the user reviewed and approved changing -- the unit
    prepare()/execute() operate on. `path` locates this field in both
    the draft-time baseline and a fresh re-read (both plain state
    dicts); `field` is whatever built this project's S3 FieldSpec/
    CoupledFieldSpec/ButtonFieldSpec for it, used for its `compare()`
    and to build the actual `Operation`. `desired` is a concrete value
    or `Intent.CLEAR` -- never `Intent.PRESERVE`: a field the user
    didn't change was never approved as an intent to begin with, so it
    has no reason to appear here at all."""
    path: tuple[str, ...]
    desired: Any
    field: Any  # FieldSpec | CoupledFieldSpec | ButtonFieldSpec -- all three expose compare (default on the first two) and plan_operation
    profile: int

    def __post_init__(self):
        if self.desired is Intent.PRESERVE:
            raise ValueError("ApprovedIntent.desired must never be Intent.PRESERVE -- "
                              "an unchanged field was never approved, so it shouldn't be one of these")


@dataclass(frozen=True)
class FieldOutcome:
    """One `ApprovedIntent`'s classification result."""
    intent: ApprovedIntent
    classification: Classification
    baseline_value: Any
    fresh_value: Any


@dataclass(frozen=True)
class DraftRevision:
    """Identity for one version of a draft. Bumped by the caller every
    time an approved intent is added, removed or edited -- comparing
    revisions is how a stale preparation is detected, not by re-diffing
    draft contents."""
    draft_id: str
    revision: int


class StaleJobError(Exception):
    """Raised by execute() when the job's draft revision or connection
    generation no longer matches what the caller has now -- the caller
    must re-prepare, per FEASIBILITY.md's own words: "reject stale
    preparation after editing, release, reconnect or profile change".
    """


@dataclass(frozen=True)
class PreparedJob:
    """Immutable result of prepare() -- bound to the exact draft
    revision and connection generation it was prepared against."""
    job_id: str
    draft_revision: DraftRevision
    connection_generation: int
    outcomes: tuple[FieldOutcome, ...]

    @property
    def conflicts(self) -> tuple[FieldOutcome, ...]:
        return tuple(o for o in self.outcomes if o.classification is Classification.CONFLICT)

    @property
    def already_satisfied(self) -> tuple[FieldOutcome, ...]:
        return tuple(o for o in self.outcomes if o.classification is Classification.ALREADY_SATISFIED)

    @property
    def writable(self) -> tuple[FieldOutcome, ...]:
        """Outcomes that need a real write if executed -- excludes
        ALREADY_SATISFIED. Includes CONFLICT outcomes; execute() itself
        is what refuses to write those without an explicit override."""
        return tuple(o for o in self.outcomes if o.classification is not Classification.ALREADY_SATISFIED)

    @property
    def ready_to_execute(self) -> bool:
        """True only with zero conflicts -- the fast path's own test
        (DESIGN-SPEC.md 10.3: "If preparation finds nothing beyond the
        listed rows, it executes... with no sheet. If it finds a
        conflict... it escalates to the full review sheet.")."""
        return not self.conflicts


@dataclass(frozen=True)
class ExecutionResult:
    job_id: str
    executed: tuple[FieldOutcome, ...]


def prepare(job_id: str, draft_revision: DraftRevision, connection_generation: int,
            approved_intents: Sequence[ApprovedIntent], baseline_state: dict, fresh_state: dict) -> PreparedJob:
    """Classify every approved intent against a FRESH re-read, not the
    draft-time baseline -- "Preparation reads fresh state without
    replacing the draft" (FEASIBILITY.md). Never writes anything;
    purely a classification step. `baseline_state`/`fresh_state` are
    both plain state dicts (read_state()/load_state() shape)."""
    outcomes = []
    for intent in approved_intents:
        baseline_value = _get_path(baseline_state, intent.path)
        fresh_value = _get_path(fresh_state, intent.path)
        compare = getattr(intent.field, "compare", lambda a, b: a == b)
        desired_for_compare = None if intent.desired is Intent.CLEAR else intent.desired
        if compare(fresh_value, desired_for_compare):
            classification = Classification.ALREADY_SATISFIED
        elif compare(fresh_value, baseline_value):
            classification = Classification.CLEAN
        else:
            classification = Classification.CONFLICT
        outcomes.append(FieldOutcome(intent, classification, baseline_value, fresh_value))
    return PreparedJob(job_id, draft_revision, connection_generation, tuple(outcomes))


def execute(session: VendorSession, job: PreparedJob, current_draft_revision: DraftRevision,
            current_connection_generation: int, *, force_conflicts: bool = False) -> ExecutionResult:
    """Write every outcome that needs one, bound to `job`'s exact
    identity -- raises StaleJobError if the draft was edited or the
    connection changed since prepare(), matching FEASIBILITY.md's own
    words exactly ("reject stale preparation after editing, release,
    reconnect or profile change" -- a profile change or reconnect is
    what bumps `connection_generation` in this design; the caller owns
    that counter, this module only ever compares it).

    Builds each write via `intent.field.plan_operation(desired,
    baseline=fresh_value, profile)` -- using the FRESH value prepare()
    just re-read as the comparison baseline, not the stale draft-time
    one, is the actual fix for B2 ("materialize a complete candidate
    from fresh state plus approved intents"). `plan_operation()`'s own
    skip-if-matches logic becomes redundant here (CLEAN/CONFLICT
    outcomes are already known to differ) but is harmless, not
    bypassed -- one code path, not two. `ButtonFieldSpec.plan_operation()`
    has no such logic at all (its own docstring: the skip-vs-write call
    is made by `prepare()`'s classification instead) and simply ignores
    the `baseline` argument -- accepted only so this call site can stay
    one uniform shape across all three field types, not three.
    """
    if job.draft_revision != current_draft_revision:
        raise StaleJobError(
            f"draft revision changed since prepare: {job.draft_revision} -> {current_draft_revision}")
    if job.connection_generation != current_connection_generation:
        raise StaleJobError(
            f"connection generation changed since prepare: "
            f"{job.connection_generation} -> {current_connection_generation}")
    if job.conflicts and not force_conflicts:
        raise ValueError(
            f"{len(job.conflicts)} unresolved conflict(s); re-prepare or pass force_conflicts=True")

    executed = []
    for outcome in job.writable:
        if outcome.classification is Classification.CONFLICT and not force_conflicts:
            continue  # defensive; the guard above already should have raised first
        intent = outcome.intent
        op = intent.field.plan_operation(intent.desired, outcome.fresh_value, intent.profile)
        if op is not None:
            op.execute(session)
        executed.append(outcome)
    return ExecutionResult(job_id=job.job_id, executed=tuple(executed))


@dataclass(frozen=True)
class ReadBackResult:
    """What a post-write re-read actually found, per executed field --
    the explicit "read back" step S5's vertical slice asks for
    (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S), mapped to
    the GUI workflow's READING_BACK state (g7ctlc/workflow_state.py):
    `ok` -> READING_BACK -> IDLE, `mismatched` non-empty -> PARTIAL
    ("read-back mismatch => draft retained," FEASIBILITY.md M1 -- not
    silently accepted as success)."""
    job_id: str
    ok: tuple[FieldOutcome, ...]
    mismatched: tuple[FieldOutcome, ...]

    @property
    def all_confirmed(self) -> bool:
        return not self.mismatched


def read_back(result: ExecutionResult, post_write_state: dict) -> ReadBackResult:
    """Re-check every field execute() just wrote against a FRESH read
    taken after the writes -- this is additional traffic, not part of
    phase-one wire parity (FEASIBILITY.md M1: "A post-write read is
    additional traffic, not phase-one behavior parity"), which is why
    this is its own function rather than folded into execute() itself.
    Uses the same per-field `compare()`/CLEAR resolution prepare() does,
    so a curve-points shape difference or a real clear don't look like
    a mismatch they aren't."""
    ok = []
    mismatched = []
    for outcome in result.executed:
        intent = outcome.intent
        actual = _get_path(post_write_state, intent.path)
        compare = getattr(intent.field, "compare", lambda a, b: a == b)
        desired_for_compare = None if intent.desired is Intent.CLEAR else intent.desired
        if compare(actual, desired_for_compare):
            ok.append(outcome)
        else:
            mismatched.append(outcome)
    return ReadBackResult(job_id=result.job_id, ok=tuple(ok), mismatched=tuple(mismatched))
