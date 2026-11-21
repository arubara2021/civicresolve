"""Closure protocol orchestration.

Resolved is unreachable from here. A passing chain moves the complaint to
awaiting_citizen; only the citizen's acceptance (or a logged reviewer override)
produces Resolved. Every attempt, pass or fail, is appended to the passport.
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
    EvidenceKind,
    Status,
    SubStatus,
    escalate_urgency,
)
from app.domain.models import ClosureAttempt, Complaint, Decision, EvidenceFile
from app.domain.schemas import DecisionIn, ForensicReport
from app.domain.state_machine import RuleViolation, State, TransitionContext, next_state
from app.forensics.duplication import remember_remarks
from app.forensics.pipeline import run_pipeline
from app.modules.assets.hash_chain import append_event
from app.modules.notify.outbox import write_notification
from app.storage.base import StoragePort
from app.storage.local import get_storage

from .evidence import store_evidence

log = get_logger(__name__)


def _state(complaint: Complaint) -> State:
    return State(status=Status(complaint.status), sub_status=SubStatus(complaint.sub_status))


def _apply(complaint: Complaint, state: State) -> None:
    complaint.status = state.status.value
    complaint.sub_status = state.sub_status.value
    complaint.updated_at = datetime.now(UTC)


def _transition(complaint: Complaint, action: Action, actor: ActorType, ctx=None) -> State:
    try:
        return next_state(_state(complaint), action, actor, ctx or TransitionContext())
    except RuleViolation as exc:
        raise InvalidStateTransitionError(str(exc)) from exc


async def _load_complaint(session: AsyncSession, complaint_id: str) -> Complaint:
    record = await session.get(Complaint, complaint_id)
    if record is None:
        raise NotFoundError(f"Complaint {complaint_id!r} not found.")
    return record


async def submit_attempt(
    session: AsyncSession,
    *,
    complaint_id: str,
    officer_id: str,
    remarks: str,
    after_image: bytes,
    after_mime: str | None = None,
    before_image: bytes | None = None,
    before_mime: str | None = None,
    work_order_reference: str | None = None,
    work_completed_at: datetime | None = None,
    storage: StoragePort | None = None,
) -> tuple[ClosureAttempt, ForensicReport, bool]:
    """Returns (attempt, report, created). created=False means an idempotent replay."""
    settings = get_settings()
    storage = storage or get_storage()
    complaint = await _load_complaint(session, complaint_id)

    _transition(complaint, Action.SUBMIT_CLOSURE, ActorType.OFFICER)

    # Idempotency: the same photograph on the same complaint is the same attempt.
    import hashlib

    digest = hashlib.sha256(after_image).hexdigest()
    existing = (
        await session.execute(
            select(ClosureAttempt)
            .join(EvidenceFile, EvidenceFile.attempt_id == ClosureAttempt.id)
            .where(
                ClosureAttempt.complaint_id == complaint_id,
                EvidenceFile.content_hash == digest,
                EvidenceFile.kind == EvidenceKind.AFTER.value,
            )
        )
    ).scalars().first()
    if existing is not None and existing.forensic_report:
        return existing, ForensicReport.model_validate(existing.forensic_report), False

    attempt = ClosureAttempt(
        id=await allocate_id(session, IdPrefix.ATTEMPT),
        complaint_id=complaint.id,
        asset_id=complaint.asset_id,
        attempt_number=complaint.attempt_count + 1,
        officer_id=officer_id,
        remarks=remarks,
        work_order_reference=work_order_reference,
        work_completed_at=work_completed_at,
    )
    session.add(attempt)
    await session.flush()

    after_ev = await store_evidence(
        session, storage=storage, complaint=complaint, attempt=attempt,
        data=after_image, kind=EvidenceKind.AFTER, mime_type=after_mime,
    )
    before_ev = None
    if before_image:
        before_ev = await store_evidence(
            session, storage=storage, complaint=complaint, attempt=attempt,
            data=before_image, kind=EvidenceKind.BEFORE, mime_type=before_mime,
        )

    complaint.attempt_count += 1
    _apply(complaint, _transition(complaint, Action.SUBMIT_CLOSURE, ActorType.OFFICER))
    await append_event(
        session, asset_id=complaint.asset_id,
        event_type=EventType.CLOSURE_ATTEMPT_SUBMITTED,
        actor_type=ActorType.OFFICER, actor_id=officer_id,
        payload={
            "complaint_id": complaint.id, "attempt_id": attempt.id,
            "attempt_number": attempt.attempt_number, "remarks": remarks,
            "work_order_reference": work_order_reference,
            "after_evidence_id": after_ev.id,
        },
    )

    report = await run_pipeline(session, storage, complaint, attempt, after_ev, before_ev)

    attempt.audited_at = datetime.now(UTC)
    attempt.chain_sufficient = report.decision.sufficient
    attempt.reuse_detected = report.reuse_detected
    attempt.degraded = report.degraded
    attempt.model_used = report.model_used
    attempt.forensic_report = report.model_dump(mode="json")
    attempt.deficiencies = [d.model_dump(mode="json") for d in report.deficiencies]

    if report.decision.sufficient:
        _apply(complaint, _transition(complaint, Action.AUDIT_PASS, ActorType.SYSTEM))
        complaint.sla_deadline = datetime.fromtimestamp(
            datetime.now(UTC).timestamp() + settings.effective_sla_seconds, tz=UTC
        )
    else:
        _apply(complaint, _transition(complaint, Action.AUDIT_FAIL, ActorType.SYSTEM))
        complaint.failed_attempt_count += 1

    await append_event(
        session, asset_id=complaint.asset_id,
        event_type=EventType.FORENSIC_REPORT_ISSUED,
        actor_type=ActorType.SYSTEM,
        payload={
            "complaint_id": complaint.id, "attempt_id": attempt.id,
            "chain_sufficient": report.decision.sufficient,
            "reuse_detected": report.reuse_detected,
            "degraded": report.degraded,
            "links": {i.link.value: i.verdict.value for i in report.links},
            "blocking_reasons": report.decision.blocking_reasons,
            "deficiencies": [d.code.value for d in report.deficiencies],
        },
    )

    if complaint.failed_attempt_count >= settings.escalate_failed_closures:
        before_band = complaint.urgency
        complaint.urgency = escalate_urgency(complaint.urgency).value
        await append_event(
            session, asset_id=complaint.asset_id,
            event_type=EventType.PRIORITY_ESCALATED, actor_type=ActorType.SYSTEM,
            payload={
                "complaint_id": complaint.id, "assessed_urgency": before_band,
                "final_urgency": complaint.urgency,
                "reasons": [f"failed_closure_attempts {complaint.failed_attempt_count}"],
            },
        )

    remember_remarks(complaint.ward, complaint.id, remarks)

    await write_notification(
        session, recipient_id=complaint.reporter_id, recipient_type="citizen",
        event_type=EventType.FORENSIC_REPORT_ISSUED.value,
        title="Closure evidence submitted",
        body=(
            f"A repair was claimed on {complaint.id}. Review the forensics report and accept or reject."
            if report.decision.sufficient
            else f"A closure claim on {complaint.id} failed the evidence audit."
        ),
        complaint_id=complaint.id, asset_id=complaint.asset_id,
        payload={"attempt_id": attempt.id, "chain_sufficient": report.decision.sufficient},
    )
    await session.flush()
    return attempt, report, True


async def _quorum_met(session: AsyncSession, complaint: Complaint) -> bool:
    settings = get_settings()
    reporters = (
        await session.execute(
            select(func.count(func.distinct(Complaint.reporter_id))).where(
                Complaint.asset_id == complaint.asset_id
            )
        )
    ).scalar_one()
    if reporters <= 1:
        return True
    accepts = (
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
    return accepts + 1 >= settings.quorum_size


async def record_decision(
    session: AsyncSession, *, attempt_id: str, payload: DecisionIn
) -> tuple[Decision, Complaint, bool]:
    """Idempotent on (attempt_id, actor_id). Replaying returns the first decision."""
    attempt = await session.get(ClosureAttempt, attempt_id)
    if attempt is None:
        raise NotFoundError(f"Closure attempt {attempt_id!r} not found.")
    complaint = await _load_complaint(session, attempt.complaint_id)

    prior = (
        await session.execute(
            select(Decision).where(
                Decision.attempt_id == attempt_id, Decision.actor_id == payload.actor_id
            )
        )
    ).scalars().first()
    if prior is not None:
        return prior, complaint, False

    if payload.decision is DecisionType.ACCEPT:
        ctx = TransitionContext(
            chain_sufficient=bool(attempt.chain_sufficient),
            quorum_met=await _quorum_met(session, complaint),
        )
        target = _transition(complaint, Action.ACCEPT, ActorType.CITIZEN, ctx)
        complaint.resolved_at = datetime.now(UTC)
        event_type = EventType.CITIZEN_ACCEPTED
    else:
        target = _transition(complaint, Action.REJECT, ActorType.CITIZEN)
        # A failed audit was already counted at submission. Only a rejection that
        # overturns a PASSING chain is a new failure, otherwise one attempt is
        # counted twice and escalation fires early.
        if attempt.chain_sufficient:
            complaint.failed_attempt_count += 1
        event_type = EventType.CITIZEN_REJECTED

    _apply(complaint, target)

    decision = Decision(
        id=await allocate_id(session, IdPrefix.DECISION),
        attempt_id=attempt.id, complaint_id=complaint.id,
        actor_type=ActorType.CITIZEN.value, actor_id=payload.actor_id,
        decision=payload.decision.value, reason=payload.reason,
        chain_sufficient_at_decision=attempt.chain_sufficient,
    )
    session.add(decision)
    await session.flush()

    await append_event(
        session, asset_id=complaint.asset_id, event_type=event_type,
        actor_type=ActorType.CITIZEN, actor_id=payload.actor_id,
        payload={
            "complaint_id": complaint.id, "attempt_id": attempt.id,
            "decision": payload.decision.value, "reason": payload.reason,
            "chain_sufficient": attempt.chain_sufficient,
        },
    )

    # A passing chain rejected by the citizen must reach a reviewer, not a dead end.
    # Phase 9 adds a dedicated action; SLA_EXPIRE is the legal SYSTEM route today.
    if payload.decision is DecisionType.REJECT and attempt.chain_sufficient:
        _apply(complaint, _transition(complaint, Action.SLA_EXPIRE, ActorType.SYSTEM))
        await append_event(
            session, asset_id=complaint.asset_id, event_type=EventType.ESCALATED,
            actor_type=ActorType.SYSTEM,
            payload={
                "complaint_id": complaint.id, "attempt_id": attempt.id,
                "reason": "chain_pass_citizen_rejected",
            },
        )

    await write_notification(
        session, recipient_id=attempt.officer_id, recipient_type="officer",
        event_type=event_type.value,
        title=f"Citizen {payload.decision.value}ed your closure",
        body=payload.reason or f"Attempt {attempt.id} was {payload.decision.value}ed.",
        complaint_id=complaint.id, asset_id=complaint.asset_id,
        payload={"attempt_id": attempt.id},
    )
    await session.flush()
    return decision, complaint, True


async def reopen_complaint(
    session: AsyncSession, *, complaint_id: str, actor_id: str, reason: str
) -> Complaint:
    settings = get_settings()
    complaint = await _load_complaint(session, complaint_id)
    if complaint.resolved_at is None:
        raise ConflictError("Only a resolved complaint can be reopened.")
    age_days = (datetime.now(UTC) - complaint.resolved_at).total_seconds() / 86_400.0
    ctx = TransitionContext(within_reopen_window=age_days <= settings.reopen_window_days)
    _apply(complaint, _transition(complaint, Action.REOPEN, ActorType.CITIZEN, ctx))
    complaint.reopen_count += 1
    complaint.resolved_at = None
    await append_event(
        session, asset_id=complaint.asset_id, event_type=EventType.REOPENED,
        actor_type=ActorType.CITIZEN, actor_id=actor_id,
        payload={"complaint_id": complaint.id, "reason": reason, "reopen_count": complaint.reopen_count},
    )
    await write_notification(
        session, recipient_id=complaint.reporter_id, recipient_type="citizen",
        event_type=EventType.REOPENED.value, title="Complaint reopened",
        body=f"{complaint.id} was reopened and re-queued.",
        complaint_id=complaint.id, asset_id=complaint.asset_id,
    )
    await session.flush()
    return complaint