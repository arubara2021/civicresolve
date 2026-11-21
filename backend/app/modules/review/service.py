"""Independent reviewer adjudication.

Three jobs. Drain the escalation queue so no ticket is ever stuck. Adjudicate a
closure the citizen rejected even though the evidence chain passed, which is the
bad-faith-rejection case that would otherwise punish an honest officer. And
record every override with a mandatory justification, permanently, on the
passport.

A reviewer may resolve a deficient chain because metadata is lost by honest
upload pipelines all the time. That is exactly why the justification is
compulsory and the chain state at the moment of override is written to the event.
The override is never silent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidStateTransitionError, NotFoundError
from app.core.ids import IdPrefix
from app.core.logging import get_logger
from app.core.sequences import allocate_id
from app.domain.enums import (
    Action,
    ActorType,
    DecisionType,
    EventType,
    Status,
    SubStatus,
    escalate_urgency,
)
from app.domain.models import ClosureAttempt, Complaint, Decision
from app.domain.schemas import ReviewDecisionIn
from app.domain.state_machine import (
    RuleViolation,
    State,
    TransitionContext,
    allowed_actions,
    next_state,
)
from app.modules.assets.hash_chain import append_event
from app.modules.notify.outbox import write_notification

log = get_logger(__name__)

REVIEWABLE_SUB_STATUSES = (SubStatus.ESCALATED.value, SubStatus.DISPUTED.value)
REVIEWER_POOL = "REVIEWER-POOL"


def _state(complaint: Complaint) -> State:
    return State(status=Status(complaint.status), sub_status=SubStatus(complaint.sub_status))


async def _latest_attempt(session: AsyncSession, complaint_id: str) -> ClosureAttempt | None:
    stmt = (
        select(ClosureAttempt)
        .where(ClosureAttempt.complaint_id == complaint_id)
        .order_by(ClosureAttempt.attempt_number.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _latest_citizen_decision(
    session: AsyncSession, attempt_id: str
) -> Decision | None:
    stmt = (
        select(Decision)
        .where(
            Decision.attempt_id == attempt_id,
            Decision.actor_type == ActorType.CITIZEN.value,
        )
        .order_by(Decision.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def quorum_status(session: AsyncSession, complaint: Complaint) -> dict:
    """Acceptance quorum for an asset reported by more than one citizen.

    Forty people reporting one pothole cannot all hold a veto. The configured
    quorum decides, and a single-reporter asset always satisfies it.
    """
    settings = get_settings()
    reporters = int(
        (
            await session.execute(
                select(func.count(func.distinct(Complaint.reporter_id))).where(
                    Complaint.asset_id == complaint.asset_id
                )
            )
        ).scalar_one()
    )
    accepts = int(
        (
            await session.execute(
                select(func.count(func.distinct(Decision.actor_id)))
                .join(ClosureAttempt, ClosureAttempt.id == Decision.attempt_id)
                .where(
                    ClosureAttempt.asset_id == complaint.asset_id,
                    Decision.decision == DecisionType.ACCEPT.value,
                    Decision.actor_type == ActorType.CITIZEN.value,
                )
            )
        ).scalar_one()
    )
    required = 1 if reporters <= 1 else settings.quorum_size
    # A single-reporter asset needs no prior acceptance: that reporter's own
    # pending decision satisfies the quorum. Counting only stored acceptances
    # would report "not met" on every fresh case and mislead the reviewer UI.
    met = reporters <= 1 or accepts >= required
    return {
        "reporters": reporters,
        "accepts": accepts,
        "required": required,
        "met": met,
    }


def escalation_reason(
    complaint: Complaint,
    attempt: ClosureAttempt | None,
    citizen_decision: Decision | None,
) -> str:
    """Why this case reached a reviewer. Shown on the queue, logged on the event."""
    if (
        attempt is not None
        and attempt.chain_sufficient
        and citizen_decision is not None
        and citizen_decision.decision == DecisionType.REJECT.value
    ):
        return "chain_pass_citizen_rejected"
    if complaint.sub_status == SubStatus.ESCALATED.value:
        return "sla_expired"
    if complaint.failed_attempt_count >= get_settings().escalate_failed_closures:
        return "repeated_failed_closures"
    return "disputed_closure"


async def list_escalations(
    session: AsyncSession,
    *,
    ward: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """The reviewer queue, priority-sorted. Never includes a resolved complaint."""
    filters = [
        Complaint.status != Status.RESOLVED.value,
        Complaint.sub_status.in_(REVIEWABLE_SUB_STATUSES),
    ]
    if ward:
        filters.append(Complaint.ward == ward)

    total = int(
        (
            await session.execute(select(func.count(Complaint.id)).where(*filters))
        ).scalar_one()
    )
    stmt = (
        select(Complaint)
        .where(*filters)
        .order_by(Complaint.priority_score.desc(), Complaint.sla_deadline.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    items: list[dict] = []
    for complaint in rows:
        attempt = await _latest_attempt(session, complaint.id)
        citizen_decision = (
            await _latest_citizen_decision(session, attempt.id) if attempt else None
        )
        reason = escalation_reason(complaint, attempt, citizen_decision)
        items.append(
            {
                "complaint_id": complaint.id,
                "asset_id": complaint.asset_id,
                "title": complaint.title,
                "ward": complaint.ward,
                "status": complaint.status,
                "sub_status": complaint.sub_status,
                "urgency": complaint.urgency,
                "priority_score": complaint.priority_score,
                "department": complaint.department,
                "reporter_id": complaint.reporter_id,
                "created_at": complaint.created_at.isoformat(),
                "sla_deadline": (
                    complaint.sla_deadline.isoformat() if complaint.sla_deadline else None
                ),
                "attempt_id": attempt.id if attempt else None,
                "attempt_number": attempt.attempt_number if attempt else None,
                "chain_sufficient": attempt.chain_sufficient if attempt else None,
                "failed_attempt_count": complaint.failed_attempt_count,
                "reason": reason,
                "officer_protection_flag": reason == "chain_pass_citizen_rejected",
            }
        )
    return items, total


async def get_escalation(session: AsyncSession, complaint_id: str) -> dict:
    """Everything a reviewer needs to adjudicate, in one call."""
    complaint = await session.get(Complaint, complaint_id)
    if complaint is None:
        raise NotFoundError(f"Complaint {complaint_id!r} not found.")

    attempt = await _latest_attempt(session, complaint_id)
    citizen_decision = await _latest_citizen_decision(session, attempt.id) if attempt else None
    reason = escalation_reason(complaint, attempt, citizen_decision)

    decisions = list(
        (
            await session.execute(
                select(Decision)
                .where(Decision.complaint_id == complaint_id)
                .order_by(Decision.created_at.desc())
            )
        ).scalars().all()
    )

    return {
        "complaint": {
            "id": complaint.id,
            "asset_id": complaint.asset_id,
            "title": complaint.title,
            "description": complaint.description,
            "category": complaint.category,
            "ward": complaint.ward,
            "status": complaint.status,
            "sub_status": complaint.sub_status,
            "urgency": complaint.urgency,
            "priority_score": complaint.priority_score,
            "department": complaint.department,
            "reporter_id": complaint.reporter_id,
            "attempt_count": complaint.attempt_count,
            "failed_attempt_count": complaint.failed_attempt_count,
            "reopen_count": complaint.reopen_count,
            "created_at": complaint.created_at.isoformat(),
            "sla_deadline": (
                complaint.sla_deadline.isoformat() if complaint.sla_deadline else None
            ),
        },
        "reason": reason,
        "latest_attempt": (
            {
                "id": attempt.id,
                "attempt_number": attempt.attempt_number,
                "officer_id": attempt.officer_id,
                "remarks": attempt.remarks,
                "work_order_reference": attempt.work_order_reference,
                "chain_sufficient": attempt.chain_sufficient,
                "reuse_detected": attempt.reuse_detected,
                "degraded": attempt.degraded,
                "deficiencies": attempt.deficiencies,
            }
            if attempt
            else None
        ),
        "forensic_report": attempt.forensic_report if attempt else None,
        "decisions": [
            {
                "id": d.id,
                "attempt_id": d.attempt_id,
                "actor_type": d.actor_type,
                "actor_id": d.actor_id,
                "decision": d.decision,
                "reason": d.reason,
                "chain_sufficient_at_decision": d.chain_sufficient_at_decision,
                "created_at": d.created_at.isoformat(),
            }
            for d in decisions
        ],
        "quorum": await quorum_status(session, complaint),
        "officer_protection": {
            "chain_passed": bool(attempt and attempt.chain_sufficient),
            "citizen_rejected": bool(
                citizen_decision and citizen_decision.decision == DecisionType.REJECT.value
            ),
            "flag": reason == "chain_pass_citizen_rejected",
        },
        "allowed_actions": [
            action.value for action in allowed_actions(_state(complaint), ActorType.REVIEWER)
        ],
    }


async def review_decision(
    session: AsyncSession,
    *,
    complaint_id: str,
    payload: ReviewDecisionIn,
) -> tuple[Decision, Complaint, bool]:
    """Adjudicate. Idempotent on (attempt_id, reviewer_id).

    ACCEPT means the reviewer overrides in the officer's favour and resolves the
    complaint. REJECT means the case is returned to the department as disputed.
    Either way the justification is written to the passport permanently.
    """
    settings = get_settings()
    complaint = await session.get(Complaint, complaint_id)
    if complaint is None:
        raise NotFoundError(f"Complaint {complaint_id!r} not found.")

    attempt = await _latest_attempt(session, complaint_id)
    if attempt is None:
        raise ConflictError("There is no closure attempt to adjudicate on this complaint.")

    prior = (
        await session.execute(
            select(Decision).where(
                Decision.attempt_id == attempt.id,
                Decision.actor_id == payload.reviewer_id,
                Decision.actor_type == ActorType.REVIEWER.value,
            )
        )
    ).scalars().first()
    if prior is not None:
        return prior, complaint, False

    action = (
        Action.REVIEWER_RESOLVE
        if payload.decision is DecisionType.ACCEPT
        else Action.REVIEWER_RETURN
    )
    context = TransitionContext(
        chain_sufficient=bool(attempt.chain_sufficient),
        justification=payload.justification,
    )
    try:
        target = next_state(_state(complaint), action, ActorType.REVIEWER, context)
    except RuleViolation as exc:
        raise InvalidStateTransitionError(str(exc)) from exc

    now = datetime.now(UTC)
    complaint.status = target.status.value
    complaint.sub_status = target.sub_status.value
    complaint.updated_at = now

    if payload.decision is DecisionType.ACCEPT:
        complaint.resolved_at = now
        event_type = EventType.REVIEWER_OVERRIDE
    else:
        complaint.resolved_at = None
        complaint.failed_attempt_count += 1
        event_type = EventType.REVIEWER_RETURNED

    decision = Decision(
        id=await allocate_id(session, IdPrefix.DECISION),
        attempt_id=attempt.id,
        complaint_id=complaint.id,
        actor_type=ActorType.REVIEWER.value,
        actor_id=payload.reviewer_id,
        decision=payload.decision.value,
        reason=payload.justification,
        chain_sufficient_at_decision=attempt.chain_sufficient,
    )
    session.add(decision)
    await session.flush()

    await append_event(
        session,
        asset_id=complaint.asset_id,
        event_type=event_type,
        actor_type=ActorType.REVIEWER,
        actor_id=payload.reviewer_id,
        payload={
            "complaint_id": complaint.id,
            "attempt_id": attempt.id,
            "decision": payload.decision.value,
            "justification": payload.justification,
            "chain_sufficient_at_decision": attempt.chain_sufficient,
            "officer_id": attempt.officer_id,
        },
    )

    if (
        payload.decision is DecisionType.REJECT
        and complaint.failed_attempt_count >= settings.escalate_failed_closures
    ):
        before_band = complaint.urgency
        complaint.urgency = escalate_urgency(complaint.urgency).value
        await append_event(
            session,
            asset_id=complaint.asset_id,
            event_type=EventType.PRIORITY_ESCALATED,
            actor_type=ActorType.SYSTEM,
            payload={
                "complaint_id": complaint.id,
                "assessed_urgency": before_band,
                "final_urgency": complaint.urgency,
                "reasons": [f"failed_closure_attempts {complaint.failed_attempt_count}"],
            },
        )

    await write_notification(
        session,
        recipient_id=complaint.reporter_id,
        recipient_type="citizen",
        event_type=event_type.value,
        title="An independent reviewer decided your case",
        body=payload.justification,
        complaint_id=complaint.id,
        asset_id=complaint.asset_id,
        payload={"decision": payload.decision.value, "attempt_id": attempt.id},
    )
    await write_notification(
        session,
        recipient_id=attempt.officer_id,
        recipient_type="officer",
        event_type=event_type.value,
        title=(
            "Reviewer upheld your closure"
            if payload.decision is DecisionType.ACCEPT
            else "Reviewer returned your closure"
        ),
        body=payload.justification,
        complaint_id=complaint.id,
        asset_id=complaint.asset_id,
        payload={"decision": payload.decision.value, "attempt_id": attempt.id},
    )

    await session.flush()
    log.info(
        "review.decided",
        complaint_id=complaint.id,
        reviewer_id=payload.reviewer_id,
        decision=payload.decision.value,
        chain_sufficient=attempt.chain_sufficient,
        to_state=f"{complaint.status}/{complaint.sub_status}",
    )
    return decision, complaint, True