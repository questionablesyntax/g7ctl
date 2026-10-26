"""Unit tests for g7ctlc.workflow_state -- S4's GUI workflow state
machine (Projects/g7ctl/redesign/IMPLEMENTATION-PLAN.md, Track S).
DESIGN-SPEC.md 10.2 item 3 asks for "unit tests for every transition" --
this tests every valid edge explicitly, and for every state, that every
OTHER state not in its allowed set is rejected (not just one example
invalid edge), so a future edit that silently widens a state's allowed
set gets caught here.
"""
import unittest

from g7ctlc.workflow_state import InvalidTransitionError, WorkflowState, WorkflowStateMachine

ALL_STATES = tuple(WorkflowState)

# Mirrors workflow_state.py's own _TRANSITIONS table -- kept as a
# separate literal here rather than imported, so a test accidentally
# "passing" because it reused the same table under test is not possible.
EXPECTED_TRANSITIONS = {
    WorkflowState.IDLE: {WorkflowState.PREPARING, WorkflowState.RELEASING},
    WorkflowState.PREPARING: {WorkflowState.WRITING, WorkflowState.REVIEWING,
                               WorkflowState.FAILED, WorkflowState.IDLE, WorkflowState.RELEASING},
    WorkflowState.REVIEWING: {WorkflowState.WRITING, WorkflowState.PREPARING,
                               WorkflowState.IDLE, WorkflowState.RELEASING},
    WorkflowState.WRITING: {WorkflowState.READING_BACK, WorkflowState.FAILED, WorkflowState.PARTIAL},
    WorkflowState.READING_BACK: {WorkflowState.IDLE, WorkflowState.PARTIAL, WorkflowState.FAILED},
    WorkflowState.FAILED: {WorkflowState.IDLE, WorkflowState.PREPARING},
    WorkflowState.PARTIAL: {WorkflowState.IDLE, WorkflowState.PREPARING},
    WorkflowState.RELEASING: {WorkflowState.IDLE},
}


class WorkflowStateMachineTest(unittest.TestCase):
    def test_initial_state_is_idle_by_default(self):
        self.assertEqual(WorkflowStateMachine().state, WorkflowState.IDLE)

    def test_every_expected_valid_transition_succeeds(self):
        for from_state, to_states in EXPECTED_TRANSITIONS.items():
            for to_state in to_states:
                with self.subTest(from_state=from_state, to_state=to_state):
                    m = WorkflowStateMachine(from_state)
                    self.assertTrue(m.can_transition(to_state))
                    m.transition(to_state)
                    self.assertEqual(m.state, to_state)

    def test_every_other_pair_is_rejected(self):
        for from_state in ALL_STATES:
            allowed = EXPECTED_TRANSITIONS[from_state]
            for to_state in ALL_STATES:
                if to_state in allowed:
                    continue
                with self.subTest(from_state=from_state, to_state=to_state):
                    m = WorkflowStateMachine(from_state)
                    self.assertFalse(m.can_transition(to_state))
                    with self.assertRaises(InvalidTransitionError):
                        m.transition(to_state)
                    # A rejected transition must not mutate state.
                    self.assertEqual(m.state, from_state)

    def test_no_state_can_transition_to_itself(self):
        # Every state in EXPECTED_TRANSITIONS already excludes itself --
        # this pins that down explicitly rather than leaving it implicit
        # in the "every other pair is rejected" sweep above.
        for state, allowed in EXPECTED_TRANSITIONS.items():
            self.assertNotIn(state, allowed, f"{state} should not self-transition")

    def test_every_state_is_reachable_and_every_state_can_leave(self):
        reachable = {to for allowed in EXPECTED_TRANSITIONS.values() for to in allowed}
        self.assertEqual(reachable, set(ALL_STATES))  # every state appears as some edge's target
        for state in ALL_STATES:
            self.assertTrue(EXPECTED_TRANSITIONS[state], f"{state} has no outgoing transition at all")


if __name__ == "__main__":
    unittest.main()
