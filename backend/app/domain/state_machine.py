"""The closure protocol, expressed as an explicit transition table.

The invariant this module exists to enforce: Resolved is reachable only through
citizen acceptance or a reviewer override carrying a logged justification. No
administrative actor has any transition that produces Resolved. This is not a
permission check bolted onto a CRUD update; the transition simply does not exist.

Domain exceptions are raised here rather than HTTP-shaped errors, so this module
carries no dependency on the web layer. The service layer translates
RuleViolation into InvalidStateTransitionError.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.enums import Action, ActorType, Status, SubStatus


class RuleViolation(ValueError):
    """A requested transition is not permitted by the protocol."""

    def __init__(self, message: str, *, code: str = "INVALID_STATE_TRANSITION") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class State:
    """A primary status paired with its verification detail."""

    status: Status
    sub_status: SubStatus


@dataclass(frozen=True, slots=True)
class TransitionContext:
    """Facts the guards evaluate. Supplied by the service, never by the client."""

    chain_sufficient: bool = False
    quorum_met: bool = True
    justification: str | None = None
    within_reopen_window: bool = True


@dataclass(frozen=True, slots=True)
class Rule:
    """One legal transition: its target, permitted actors, and optional guard."""

    target: State
    actors: frozenset[ActorType]
    guard: Callable[[TransitionContext], bool] | None = None
    guard_message: str = ""


TRIAGED = State(Status.REPORTED, SubStatus.TRIAGED)
ASSIGNED = State(Status.IN_PROGRESS, SubStatus.ASSIGNED)
WORKING = State(Status.IN_PROGRESS, SubStatus.WORK_IN_PROGRESS)
AUDITING = State(Status.IN_PROGRESS, SubStatus.PENDING_VERIFICATION)
AWAITING = State(Status.IN_PROGRESS, SubStatus.AWAITING_CITIZEN)
DISPUTED = State(Status.IN_PROGRESS, SubStatus.DISPUTED)
ESCALATED = State(Status.IN_PROGRESS, SubStatus.ESCALATED)
REOPENED = State(Status.IN_PROGRESS, SubStatus.REOPENED)
RESOLVED_CITIZEN = State(Status.RESOLVED, SubStatus.CITIZEN_ACCEPTED)
RESOLVED_REVIEWER = State(Status.RESOLVED, SubStatus.REVIEWER_OVERRIDE)

_DEPARTMENT_ACTORS = frozenset({ActorType.OFFICER, ActorType.ADMIN})
_SYSTEM_ONLY = frozenset({ActorType.SYSTEM})
_CITIZEN_ONLY = frozenset({ActorType.CITIZEN})
_REVIEWER_ONLY = frozenset({ActorType.REVIEWER})

MIN_JUSTIFICATION_LENGTH = 20


def _evidence_and_quorum(ctx: TransitionContext) -> bool:
    return ctx.chain_sufficient and ctx.quorum_met


def _has_justification(ctx: TransitionContext) -> bool:
    return bool(ctx.justification and len(ctx.justification.strip()) >= MIN_JUSTIFICATION_LENGTH)


def _within_window(ctx: TransitionContext) -> bool:
    return ctx.within_reopen_window


_TRANSITIONS: dict[tuple[State, Action], Rule] = {
    (TRIAGED, Action.ASSIGN): Rule(
        target=ASSIGNED,
        actors=_DEPARTMENT_ACTORS | _SYSTEM_ONLY,
    ),
    (ASSIGNED, Action.START_WORK): Rule(target=WORKING, actors=_DEPARTMENT_ACTORS),
    (ASSIGNED, Action.SUBMIT_CLOSURE): Rule(target=AUDITING, actors=_DEPARTMENT_ACTORS),
    (WORKING, Action.SUBMIT_CLOSURE): Rule(target=AUDITING, actors=_DEPARTMENT_ACTORS),
    (DISPUTED, Action.SUBMIT_CLOSURE): Rule(target=AUDITING, actors=_DEPARTMENT_ACTORS),
    (REOPENED, Action.START_WORK): Rule(target=WORKING, actors=_DEPARTMENT_ACTORS),
    (REOPENED, Action.SUBMIT_CLOSURE): Rule(target=AUDITING, actors=_DEPARTMENT_ACTORS),
    (ESCALATED, Action.SUBMIT_CLOSURE): Rule(target=AUDITING, actors=_DEPARTMENT_ACTORS),
    (AUDITING, Action.AUDIT_PASS): Rule(target=AWAITING, actors=_SYSTEM_ONLY),
    (AUDITING, Action.AUDIT_FAIL): Rule(target=DISPUTED, actors=_SYSTEM_ONLY),
    (AWAITING, Action.ACCEPT): Rule(
        target=RESOLVED_CITIZEN,
        actors=_CITIZEN_ONLY,
        guard=_evidence_and_quorum,
        guard_message=("acceptance requires a sufficient evidence chain and the configured quorum"),
    ),
    (AWAITING, Action.REJECT): Rule(target=DISPUTED, actors=_CITIZEN_ONLY),
    # A failed audit already moved the case to disputed, but the citizen must
    # still be able to contest the claim and have that refusal recorded on the
    # passport. This self-loop grants no new authority and opens no path to
    # Resolved: the case stays with the department.
    (DISPUTED, Action.REJECT): Rule(target=DISPUTED, actors=_CITIZEN_ONLY),
    (AWAITING, Action.SLA_EXPIRE): Rule(target=ESCALATED, actors=_SYSTEM_ONLY),
    (DISPUTED, Action.SLA_EXPIRE): Rule(target=ESCALATED, actors=_SYSTEM_ONLY),
    # A reviewer may resolve even when the chain is deficient, because metadata can
    # be lost by an honest upload pipeline. The justification is mandatory and the
    # chain state is recorded on the event, so the override is never silent.
    (ESCALATED, Action.REVIEWER_RESOLVE): Rule(
        target=RESOLVED_REVIEWER,
        actors=_REVIEWER_ONLY,
        guard=_has_justification,
        guard_message="a reviewer override requires a justification of at least 20 characters",
    ),
    (DISPUTED, Action.REVIEWER_RESOLVE): Rule(
        target=RESOLVED_REVIEWER,
        actors=_REVIEWER_ONLY,
        guard=_has_justification,
        guard_message="a reviewer override requires a justification of at least 20 characters",
    ),
    (ESCALATED, Action.REVIEWER_RETURN): Rule(
        target=DISPUTED,
        actors=_REVIEWER_ONLY,
        guard=_has_justification,
        guard_message="returning a case requires a justification of at least 20 characters",
    ),
    (RESOLVED_CITIZEN, Action.REOPEN): Rule(
        target=REOPENED,
        actors=_CITIZEN_ONLY,
        guard=_within_window,
        guard_message="the reopen window for this resolution has elapsed",
    ),
    (RESOLVED_REVIEWER, Action.REOPEN): Rule(
        target=REOPENED,
        actors=_CITIZEN_ONLY,
        guard=_within_window,
        guard_message="the reopen window for this resolution has elapsed",
    ),
}


def next_state(
    current: State,
    action: Action,
    actor: ActorType,
    context: TransitionContext | None = None,
) -> State:
    """Resolve a transition or raise RuleViolation.

    Order of checks is deliberate: existence, then authority, then guard. A caller
    learns that an action is impossible before learning that they lack authority,
    which avoids leaking the shape of privileged transitions.
    """
    ctx = context or TransitionContext()
    rule = _TRANSITIONS.get((current, action))

    if rule is None:
        raise RuleViolation(
            f"action {action.value!r} is not permitted from "
            f"{current.status.value}/{current.sub_status.value}"
        )

    if actor not in rule.actors:
        raise RuleViolation(
            f"actor {actor.value!r} may not perform {action.value!r}",
            code="FORBIDDEN",
        )

    if rule.guard is not None and not rule.guard(ctx):
        raise RuleViolation(rule.guard_message)

    return rule.target


def allowed_actions(current: State, actor: ActorType) -> list[Action]:
    """Actions structurally available to an actor, ignoring contextual guards.

    Used to render only legal controls in the interface. Guards are still evaluated
    server-side, so a hidden button is never the security boundary.
    """
    return sorted(
        (
            action
            for (state, action), rule in _TRANSITIONS.items()
            if state == current and actor in rule.actors
        ),
        key=lambda item: item.value,
    )


def is_terminal(state: State) -> bool:
    """True when no further action exists except a time-limited reopen."""
    return state.status is Status.RESOLVED


def initial_state() -> State:
    """State assigned immediately after intake triage completes."""
    return TRIAGED


def all_states() -> tuple[State, ...]:
    """Every state referenced by the table, for coverage assertions in tests."""
    seen: dict[State, None] = {}
    for (state, _action), rule in _TRANSITIONS.items():
        seen.setdefault(state, None)
        seen.setdefault(rule.target, None)
    return tuple(seen)
