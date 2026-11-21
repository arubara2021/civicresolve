"""Citizen-response and department-response SLA sweep.

The rule this exists to enforce: a ticket is never auto-closed and never left
stuck. When the window elapses the case escalates to an independent reviewer.
Production is 72 hours; demo mode compresses it to 60 seconds so escalation can
be shown live.

The sweep is a pure database operation. It calls no model and it never writes a
Resolved status, because no SLA timeout is evidence that a repair happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.domain.enums import Action, ActorType, EventType, Status, SubStatus
from app.domain.models import Complaint
from app.domain.state_machine import RuleViolation, State, next_state
from app.modules.assets.hash_chain import append_event
from app.modules.notify.outbox import write_notification
from app.modules.review.service import REVIEWER_POOL

log = get_logger(__name__)

WATCHED_SUB_STATUSES = (
    SubStatus.AWAITING_CITIZEN.value,
    SubStatus.DISPUTED.value,
)

JOB_ID = "sla_sweep"


async def run_sla_sweep(session: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """Escalate every overdue case. Returns the complaint IDs escalated.

    Idempotent: an escalated complaint leaves the watched set, so a second sweep
    in the same second escalates nothing. The caller owns the transaction.
    """
    moment = now or datetime.now(UTC)
    stmt = select(Complaint).where(
        Complaint.status != Status.RESOLVED.value,
        Complaint.sub_status.in_(WATCHED_SUB_STATUSES),
        Complaint.sla_deadline.is_not(None),
        Complaint.sla_deadline <= moment,
    )
    overdue = list((await session.execute(stmt)).scalars().all())

    escalated: list[str] = []
    for complaint in overdue:
        current = State(
            status=Status(complaint.status), sub_status=SubStatus(complaint.sub_status)
        )
        try:
            target = next_state(current, Action.SLA_EXPIRE, ActorType.SYSTEM)
        except RuleViolation:
            continue

        was_awaiting = complaint.sub_status == SubStatus.AWAITING_CITIZEN.value
        reason = "citizen_sla_expired" if was_awaiting else "department_sla_expired"
        overdue_s = round((moment - complaint.sla_deadline).total_seconds(), 1)

        complaint.status = target.status.value
        complaint.sub_status = target.sub_status.value
        complaint.updated_at = moment

        await append_event(
            session,
            asset_id=complaint.asset_id,
            event_type=EventType.SLA_EXPIRED,
            actor_type=ActorType.SYSTEM,
            payload={
                "complaint_id": complaint.id,
                "reason": reason,
                "sla_deadline": complaint.sla_deadline.isoformat(),
                "overdue_seconds": overdue_s,
            },
        )
        await append_event(
            session,
            asset_id=complaint.asset_id,
            event_type=EventType.ESCALATED,
            actor_type=ActorType.SYSTEM,
            payload={"complaint_id": complaint.id, "reason": reason},
        )

        await write_notification(
            session,
            recipient_id=REVIEWER_POOL,
            recipient_type="reviewer",
            event_type=EventType.ESCALATED.value,
            title="Case escalated for review",
            body=f"{complaint.id} exceeded its response window ({reason}).",
            complaint_id=complaint.id,
            asset_id=complaint.asset_id,
            payload={"reason": reason, "overdue_seconds": overdue_s},
        )
        await write_notification(
            session,
            recipient_id=complaint.reporter_id,
            recipient_type="citizen",
            event_type=EventType.ESCALATED.value,
            title="Your case went to an independent reviewer",
            body=(
                f"The response window on {complaint.id} elapsed. An independent reviewer "
                "will decide. It has not been closed."
            ),
            complaint_id=complaint.id,
            asset_id=complaint.asset_id,
            payload={"reason": reason},
        )
        escalated.append(complaint.id)

    await session.flush()
    if escalated:
        log.info("sla.escalated", count=len(escalated), complaints=escalated)
    return escalated


async def _tick() -> None:
    """One scheduler tick. Never raises, so a bad row cannot kill the job."""
    try:
        async with session_scope() as session:
            await run_sla_sweep(session)
    except Exception:
        log.exception("sla.sweep_failed")


def register_sla_job(scheduler: AsyncIOScheduler, settings: Settings | None = None) -> None:
    """Attach the sweep to the running scheduler. Called once from lifespan."""
    resolved = settings or get_settings()
    interval = max(1.0, resolved.scheduler_tick_s)
    scheduler.add_job(
        _tick,
        trigger="interval",
        seconds=interval,
        id=JOB_ID,
        replace_existing=True,
        next_run_time=datetime.now(UTC) + timedelta(seconds=1),
    )
    log.info(
        "sla.job_registered",
        interval_s=interval,
        sla_seconds=resolved.effective_sla_seconds,
        demo_mode=resolved.use_demo_sla,
    )