"""The protocol's safety net.

The most important assertions here are negative: no administrative actor can reach
Resolved, and acceptance is impossible without a sufficient evidence chain. If a
future refactor introduces a shortcut, these tests fail before the demo does.
"""

from __future__ import annotations

import pytest

from app.domain.enums import Action, ActorType, Status
from app.domain.state_machine import (
    ASSIGNED,
    AUDITING,
    AWAITING,
    DISPUTED,
    ESCALATED,
    RESOLVED_CITIZEN,
    RESOLVED_REVIEWER,
    TRIAGED,
    WORKING,
    RuleViolation,
    State,
    TransitionContext,
    allowed_actions,
    initial_state,
    is_terminal,
    next_state,
)

JUSTIFICATION = "Physical inspection on site confirmed the patch is complete and compacted."
PASSING = TransitionContext(chain_sufficient=True, quorum_met=True)


def test_happy_path_reaches_resolved_only_through_the_citizen() -> None:
    state = initial_state()
    assert state == TRIAGED

    state = next_state(state, Action.ASSIGN, ActorType.ADMIN)
    assert state == ASSIGNED

    state = next_state(state, Action.START_WORK, ActorType.OFFICER)
    assert state == WORKING

    state = next_state(state, Action.SUBMIT_CLOSURE, ActorType.OFFICER)
    assert state == AUDITING

    state = next_state(state, Action.AUDIT_PASS, ActorType.SYSTEM, PASSING)
    assert state == AWAITING
    assert state.status is Status.IN_PROGRESS

    state = next_state(state, Action.ACCEPT, ActorType.CITIZEN, PASSING)
    assert state == RESOLVED_CITIZEN
    assert is_terminal(state)


@pytest.mark.parametrize("actor", [ActorType.ADMIN, ActorType.OFFICER, ActorType.SYSTEM])
def test_no_administrative_actor_can_accept(actor: ActorType) -> None:
    with pytest.raises(RuleViolation) as excinfo:
        next_state(AWAITING, Action.ACCEPT, actor, PASSING)
    assert excinfo.value.code == "FORBIDDEN"


@pytest.mark.parametrize(
    "action",
    [Action.ASSIGN, Action.START_WORK, Action.SUBMIT_CLOSURE, Action.AUDIT_PASS],
)
def test_department_actions_never_produce_resolved(action: Action) -> None:
    for source in (TRIAGED, ASSIGNED, WORKING, DISPUTED, AUDITING, AWAITING, ESCALATED):
        try:
            target = next_state(source, action, ActorType.ADMIN, PASSING)
        except RuleViolation:
            continue
        assert target.status is not Status.RESOLVED


def test_acceptance_requires_a_sufficient_chain() -> None:
    with pytest.raises(RuleViolation, match="sufficient evidence chain"):
        next_state(
            AWAITING,
            Action.ACCEPT,
            ActorType.CITIZEN,
            TransitionContext(chain_sufficient=False, quorum_met=True),
        )


def test_acceptance_requires_quorum() -> None:
    with pytest.raises(RuleViolation, match="quorum"):
        next_state(
            AWAITING,
            Action.ACCEPT,
            ActorType.CITIZEN,
            TransitionContext(chain_sufficient=True, quorum_met=False),
        )


def test_failed_audit_lands_in_disputed_not_resolved() -> None:
    target = next_state(AUDITING, Action.AUDIT_FAIL, ActorType.SYSTEM)
    assert target == DISPUTED
    assert target.status is Status.IN_PROGRESS


def test_citizen_rejection_returns_to_the_department() -> None:
    target = next_state(AWAITING, Action.REJECT, ActorType.CITIZEN)
    assert target == DISPUTED


def test_disputed_case_can_be_resubmitted() -> None:
    assert next_state(DISPUTED, Action.SUBMIT_CLOSURE, ActorType.OFFICER) == AUDITING


def test_silence_escalates_rather_than_closing() -> None:
    for source in (AWAITING, DISPUTED):
        target = next_state(source, Action.SLA_EXPIRE, ActorType.SYSTEM)
        assert target == ESCALATED
        assert target.status is Status.IN_PROGRESS


def test_reviewer_override_requires_justification() -> None:
    with pytest.raises(RuleViolation, match="justification"):
        next_state(ESCALATED, Action.REVIEWER_RESOLVE, ActorType.REVIEWER)

    with pytest.raises(RuleViolation, match="justification"):
        next_state(
            ESCALATED,
            Action.REVIEWER_RESOLVE,
            ActorType.REVIEWER,
            TransitionContext(justification="too short"),
        )


def test_reviewer_can_resolve_a_bad_faith_rejection() -> None:
    target = next_state(
        DISPUTED,
        Action.REVIEWER_RESOLVE,
        ActorType.REVIEWER,
        TransitionContext(chain_sufficient=True, justification=JUSTIFICATION),
    )
    assert target == RESOLVED_REVIEWER


def test_reviewer_can_return_an_escalated_case() -> None:
    target = next_state(
        ESCALATED,
        Action.REVIEWER_RETURN,
        ActorType.REVIEWER,
        TransitionContext(justification=JUSTIFICATION),
    )
    assert target == DISPUTED


def test_only_a_reviewer_may_override() -> None:
    with pytest.raises(RuleViolation) as excinfo:
        next_state(
            ESCALATED,
            Action.REVIEWER_RESOLVE,
            ActorType.ADMIN,
            TransitionContext(justification=JUSTIFICATION),
        )
    assert excinfo.value.code == "FORBIDDEN"


def test_reopen_is_limited_to_the_configured_window() -> None:
    inside = TransitionContext(within_reopen_window=True)
    outside = TransitionContext(within_reopen_window=False)

    reopened = next_state(RESOLVED_CITIZEN, Action.REOPEN, ActorType.CITIZEN, inside)
    assert reopened.status is Status.IN_PROGRESS
    assert reopened.sub_status.value == "reopened"

    with pytest.raises(RuleViolation, match="reopen window"):
        next_state(RESOLVED_CITIZEN, Action.REOPEN, ActorType.CITIZEN, outside)


def test_unknown_transition_is_rejected() -> None:
    with pytest.raises(RuleViolation, match="not permitted"):
        next_state(TRIAGED, Action.ACCEPT, ActorType.CITIZEN, PASSING)


def test_auditing_cannot_be_short_circuited_by_the_citizen() -> None:
    with pytest.raises(RuleViolation):
        next_state(AUDITING, Action.ACCEPT, ActorType.CITIZEN, PASSING)


def test_allowed_actions_reflect_authority() -> None:
    assert Action.ACCEPT not in allowed_actions(AWAITING, ActorType.ADMIN)
    assert Action.ACCEPT in allowed_actions(AWAITING, ActorType.CITIZEN)
    assert Action.SUBMIT_CLOSURE in allowed_actions(WORKING, ActorType.OFFICER)
    assert allowed_actions(RESOLVED_CITIZEN, ActorType.ADMIN) == []


def test_terminal_states_offer_no_administrative_escape() -> None:
    for state in (RESOLVED_CITIZEN, RESOLVED_REVIEWER):
        for actor in (ActorType.ADMIN, ActorType.OFFICER, ActorType.SYSTEM):
            assert allowed_actions(state, actor) == []


def test_state_is_hashable_and_immutable() -> None:
    registry = {TRIAGED: "start"}
    assert registry[State(Status.REPORTED, TRIAGED.sub_status)] == "start"


def test_citizen_can_contest_a_failed_audit() -> None:
    """A failed audit must not silence the citizen. The refusal is recorded."""
    target = next_state(DISPUTED, Action.REJECT, ActorType.CITIZEN)
    assert target == DISPUTED
    assert target.status is Status.IN_PROGRESS


@pytest.mark.parametrize("actor", [ActorType.ADMIN, ActorType.OFFICER, ActorType.SYSTEM])
def test_only_the_citizen_may_contest_a_disputed_closure(actor: ActorType) -> None:
    with pytest.raises(RuleViolation) as excinfo:
        next_state(DISPUTED, Action.REJECT, actor)
    assert excinfo.value.code == "FORBIDDEN"