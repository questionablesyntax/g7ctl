"""S4's GUI workflow state machine (Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md, Track S) -- the explicit states DESIGN-SPEC.md
10.2 item 3 names (idle, preparing, reviewing, writing, reading back,
failed, partial, releasing), replacing the `_syncing` flag for the new
prepare/review/write flow `pyg7.workflow` backs.

Deliberately "a narrow GUI workflow controller, not the final shared
coordinator" (FEASIBILITY.md M3's own words) -- the agreed renovation
sequence has "one coordinator state machine shared by CLI and GUI" as its
own later step, after the field registry migration is further along; this
is scoped to exactly the states this one flow needs, not a general
lifecycle replacement for `watcher.py`'s existing connect/heartbeat
machinery.

Every transition below is traceable to something the actual review
documents said, not invented -- see each one's own comment.
"""
from __future__ import annotations

import enum


class WorkflowState(enum.Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    REVIEWING = "reviewing"
    WRITING = "writing"
    READING_BACK = "reading_back"
    FAILED = "failed"
    PARTIAL = "partial"
    RELEASING = "releasing"


# Each entry: the states a given state may transition TO. Every edge
# traces to something reviews/FEASIBILITY.md or DESIGN-SPEC.md actually
# said -- see the inline comment on each.
_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.IDLE: frozenset({
        WorkflowState.PREPARING,   # user triggers the fast path or opens the review sheet (DESIGN-SPEC.md 10.3)
        WorkflowState.RELEASING,   # user releases the device, or quits, while idle
    }),
    WorkflowState.PREPARING: frozenset({
        WorkflowState.WRITING,     # fast path: prepare found nothing beyond the listed rows, executes with no sheet (DESIGN-SPEC.md 10.3)
        WorkflowState.REVIEWING,   # anything else (conflict, external change, >3 rows, shared scope) escalates to the full sheet (DESIGN-SPEC.md 10.3)
        WorkflowState.FAILED,      # the fresh re-read itself failed (S2's fail-closed rule, generalized to prepare())
        WorkflowState.IDLE,        # user cancels, or leaves the app mid-prepare -- invalidates the in-flight preparation (FEASIBILITY.md M3)
        WorkflowState.RELEASING,   # app closes mid-prepare
    }),
    WorkflowState.REVIEWING: frozenset({
        WorkflowState.WRITING,     # user approves the sheet and writes
        WorkflowState.PREPARING,   # reverting any row invalidates and recomputes the prepared plan/count (FEASIBILITY.md B2 recommendation)
        WorkflowState.IDLE,        # user cancels/closes the sheet, or leaves the app -- invalidates the prepared plan (FEASIBILITY.md M3)
        WorkflowState.RELEASING,   # app closes while reviewing
    }),
    WorkflowState.WRITING: frozenset({
        WorkflowState.READING_BACK,  # all approved writes sent, now verifying
        WorkflowState.FAILED,        # lost the connection before any write landed (same shape as existing USBError handling)
        WorkflowState.PARTIAL,       # some writes landed, then a failure stopped the rest
    }),
    WorkflowState.READING_BACK: frozenset({
        WorkflowState.IDLE,        # read-back confirms every write -- clean, done
        WorkflowState.PARTIAL,     # read-back mismatch => draft retained, not silently accepted (FEASIBILITY.md M1)
        WorkflowState.FAILED,      # the read-back itself failed (e.g. disconnected mid-read)
    }),
    WorkflowState.FAILED: frozenset({
        WorkflowState.IDLE,        # user dismisses the error
        WorkflowState.PREPARING,   # user retries -- re-prepare rather than resume the stale job
    }),
    WorkflowState.PARTIAL: frozenset({
        WorkflowState.IDLE,        # user accepts the partial result and abandons the rest
        WorkflowState.PREPARING,   # user retries the remaining fields -- re-prepare, same reasoning as FAILED
    }),
    WorkflowState.RELEASING: frozenset({
        WorkflowState.IDLE,        # release completes
    }),
}


class InvalidTransitionError(Exception):
    """Raised by WorkflowStateMachine.transition() on an edge not in
    _TRANSITIONS -- the whole point of this module is that these are
    caught here, not discovered later as a UI stuck in the wrong state."""


class WorkflowStateMachine:
    """Tracks one flow's current WorkflowState and enforces
    `_TRANSITIONS`. Not thread-safe by itself -- same expectation as
    every other piece of GUI-thread state in this codebase (widgets,
    `MainWindow`'s own flags); callers already serialize access to
    those on the GUI thread, and this is meant to replace one of them
    (`_syncing`), not introduce new synchronization requirements.
    """

    def __init__(self, initial: WorkflowState = WorkflowState.IDLE):
        self._state = initial

    @property
    def state(self) -> WorkflowState:
        return self._state

    def can_transition(self, to: WorkflowState) -> bool:
        return to in _TRANSITIONS[self._state]

    def transition(self, to: WorkflowState) -> None:
        if not self.can_transition(to):
            raise InvalidTransitionError(f"{self._state.value} -> {to.value} is not a valid transition")
        self._state = to
