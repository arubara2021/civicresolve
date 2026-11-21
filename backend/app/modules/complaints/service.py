"""Complaint query and status management.

The list endpoint supports the admin dashboard's priority-sorted queue. The detail
endpoint returns the full timeline for a single complaint. The status update
endpoint is the only place an administrative actor can move a complaint forward,
and it does so by invoking an action on the state machine rather than setting a
target state directly. This means a caller cannot request an illegal state; the
transition simply does not exist.

The service owns the transaction and commits only on success. Notifications are
written in the same transaction as the state change they describe.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidStateTransitionError
from app.domain.state_machine import RuleViolation  # Add this to the existing state_machine import

from app.core.logging import get_logger
from app.domain.enums import Action, EventType, Status, SubStatus
from app.domain.models import ClosureAttempt, Complaint, Decision, Event
from app.domain.schemas import StatusUpdate
from app.domain.state_machine import (
    State,
    TransitionContext,
    next_state,
)
from app.modules.assets.hash_chain import append_event
from app.modules.notify.outbox import write_notification

log = get_logger(__name__)


async def list_complaints(
    session: AsyncSession,
    *,
    ward: str | None = None,
    status: str | None = None,
    department: str | None = None,
    urgency: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Complaint], int]:
    """Return a filtered, priority-sorted list of complaints and the total count.

    Priority sorting ensures the admin sees the most urgent cases first. The queue is
    not FIFO; it is weighted by urgency, impact, and history risk.
    """
    filters = []
    if ward:
        filters.append(Complaint.ward == ward)
    if status:
        filters.append(Complaint.status == status)
    if department:
        filters.append(
            or_(Complaint.department == department, Complaint.assignee_department == department)
        )
    if urgency:
        filters.append(Complaint.urgency == urgency)

    where_clause = and_(*filters) if filters else True

    count_query = select(Complaint).where(where_clause)
    total = len((await session.execute(count_query)).scalars().all())

    statement = (
        select(Complaint)
        .where(where_clause)
        .order_by(Complaint.priority_score.desc(), Complaint.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    records = list((await session.execute(statement)).scalars().all())

    log.debug(
        "complaints.listed",
        ward=ward,
        status=status,
        department=department,
        urgency=urgency,
        returned=len(records),
        total=total,
    )
    return records, total


async def get_complaint(session: AsyncSession, complaint_id: str) -> Complaint:
    """Return a single complaint or raise NotFoundError."""
    record = await session.get(Complaint, complaint_id)
    if record is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Complaint {complaint_id!r} not found.")
    return record


async def get_complaint_timeline(session: AsyncSession, complaint_id: str) -> list[Event]:
    """Return all passport events related to this complaint's asset, in sequence order."""
    complaint = await get_complaint(session, complaint_id)
    statement = select(Event).where(Event.asset_id == complaint.asset_id).order_by(Event.seq)
    return list((await session.execute(statement)).scalars().all())


async def get_complaint_attempts(session: AsyncSession, complaint_id: str) -> list[ClosureAttempt]:
    """Return all closure attempts for this complaint, newest first."""
    statement = (
        select(ClosureAttempt)
        .where(ClosureAttempt.complaint_id == complaint_id)
        .order_by(ClosureAttempt.submitted_at.desc())
    )
    return list((await session.execute(statement)).scalars().all())


async def get_complaint_decisions(session: AsyncSession, complaint_id: str) -> list[Decision]:
    """Return all decisions (citizen or reviewer) for this complaint's attempts."""
    statement = (
        select(Decision)
        .where(Decision.complaint_id == complaint_id)
        .order_by(Decision.created_at.desc())
    )
    return list((await session.execute(statement)).scalars().all())


async def update_status(
    session: AsyncSession,
    *,
    complaint_id: str,
    action: StatusUpdate,
) -> Complaint:
    """Move a complaint forward by invoking an action on the state machine.

    The caller supplies the action (assign, start_work, submit_closure), not the
    target state. The state machine decides whether the transition is legal and
    what the new state is. This is the only place a complaint's status changes
    outside of the closure protocol (Phase 8) and the citizen decision (Phase 8).

    The caller owns the transaction and commits after this returns.
    """
    complaint = await get_complaint(session, complaint_id)

    current_state = State(
        status=Status(complaint.status), sub_status=SubStatus(complaint.sub_status)
    )

    context = TransitionContext()
    try:
        target_state = next_state(current_state, action.action, action.actor_type, context)
    except RuleViolation as exc:
        raise InvalidStateTransitionError(str(exc)) from exc

    complaint.status = target_state.status.value
    complaint.sub_status = target_state.sub_status.value
    complaint.updated_at = datetime.now(UTC)

    if action.action is Action.ASSIGN and action.assignee_department:
        complaint.assignee_department = action.assignee_department.value

    await session.flush()

    event_type = _action_to_event_type(action.action)
    payload = {"complaint_id": complaint_id, "action": action.action.value}
    if action.assignee_department:
        payload["department"] = action.assignee_department.value

    await append_event(
        session,
        asset_id=complaint.asset_id,
        event_type=event_type,
        actor_type=action.actor_type,
        actor_id=action.actor_id,
        payload=payload,
    )

    await write_notification(
        session,
        recipient_id=complaint.reporter_id,
        recipient_type="citizen",
        event_type=event_type.value,
        title=f"Complaint {action.action.value}",
        body=f"Your complaint {complaint_id} has been {action.action.value}.",
        complaint_id=complaint_id,
        asset_id=complaint.asset_id,
        payload={"action": action.action.value},
    )

    log.info(
        "complaint.status_updated",
        complaint_id=complaint_id,
        action=action.action.value,
        actor=action.actor_id,
        from_state=f"{current_state.status.value}/{current_state.sub_status.value}",
        to_state=f"{target_state.status.value}/{target_state.sub_status.value}",
    )

    return complaint


def _action_to_event_type(action: Action) -> EventType:
    """Map a state machine action to the corresponding passport event type."""
    mapping = {
        Action.ASSIGN: EventType.COMPLAINT_ASSIGNED,
        Action.START_WORK: EventType.WORK_STARTED,
        Action.SUBMIT_CLOSURE: EventType.CLOSURE_ATTEMPT_SUBMITTED,
        Action.REOPEN: EventType.REOPENED,
    }
    event_type = mapping.get(action)
    if event_type is None:
        raise ValueError(f"No event type mapping for action {action.value!r}")
    return event_type
