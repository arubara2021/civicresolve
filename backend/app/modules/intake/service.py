"""Intake orchestration.

This service owns the full complaint submission flow: validate input, match or
create the asset, call Gemini triage, compute priority from the asset's history,
persist the complaint, append the passport event, and write the notification
outbox row. The entire flow runs in one transaction so a failure at any step
rolls back cleanly.

The service does not own the HTTP boundary; the router handles multipart parsing
and calls submit_complaint with validated inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ports import TriageInput
from app.agents.registry import build_triage_agent
from app.core.config import get_settings
from app.core.ids import IdPrefix
from app.core.logging import get_logger
from app.core.sequences import allocate_id
from app.domain.enums import ActorType, EventType
from app.domain.models import Complaint
from app.domain.priority import (
    EscalationRules,
    PriorityWeights,
    RiskCoefficients,
    compute_priority,
)
from app.domain.schemas import GeoPoint, TriageResult
from app.modules.assets.hash_chain import append_event
from app.modules.assets.service import match_or_create
from app.modules.notify.outbox import write_notification
from app.tools.asset_history import build_snapshot

log = get_logger(__name__)


async def submit_complaint(
    session: AsyncSession,
    *,
    title: str,
    description: str,
    location: GeoPoint,
    category_hint: str | None,
    reporter_id: str,
    ward: str,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> Complaint:
    """Orchestrate the full intake flow in one transaction.

    The caller owns the transaction and commits after this returns. If any step
    fails, the session rolls back and no partial state persists.
    """
    settings = get_settings()

    # Step 1: Call the triage agent. This is the only model call in the flow.
    agent = build_triage_agent()
    triage_input = TriageInput(
        title=title,
        description=description,
        location=location,
        category_hint=category_hint,
        reporter_summary=description[:200],
        ward=ward,
        image_bytes=image_bytes,
        image_mime=image_mime,
    )
    triage_outcome = await agent.triage(triage_input)
    triage: TriageResult = triage_outcome.result

    log.info(
        "intake.triage_complete",
        category=triage.category.value,
        urgency=triage.urgency.value,
        impact_score=triage.public_impact.score,
        department=triage.department.primary.value,
        model_used=triage_outcome.call.model_used,
        latency_s=triage_outcome.call.latency_s,
    )

    # Step 2: Match or create the asset. The evidentiary standard is locked here.
    asset, asset_created = await match_or_create(
        session, location=location, triage=triage, ward=ward
    )

    if asset_created:
        await append_event(
            session,
            asset_id=asset.id,
            event_type=EventType.ASSET_CREATED,
            actor_type=ActorType.SYSTEM,
            payload={"ward": ward, "label": asset.label},
        )

    # Step 3: Build the asset history snapshot for priority computation.
    snapshot = await build_snapshot(session, asset.id)

    # Step 4: Compute priority. The history term makes the passport load-bearing.
    weights = PriorityWeights(
        urgency=settings.w_urgency,
        impact=settings.w_impact,
        history=settings.w_history,
    )
    coefficients = RiskCoefficients()
    escalation = EscalationRules(
        reopen_threshold=settings.escalate_reopens,
        failed_closure_threshold=settings.escalate_failed_closures,
    )
    priority_breakdown = compute_priority(
        urgency=triage.urgency,
        impact_score=triage.public_impact.score,
        snapshot=snapshot,
        weights=weights,
        coefficients=coefficients,
        escalation=escalation,
    )

    if priority_breakdown.escalated:
        log.info(
            "intake.priority_escalated",
            asset_id=asset.id,
            assessed=triage.urgency.value,
            final=priority_breakdown.final_urgency.value,
            score=priority_breakdown.score,
            reasons=priority_breakdown.reasons,
        )

    # Step 5: Persist the complaint.
    complaint_id = await allocate_id(session, IdPrefix.COMPLAINT)
    now = datetime.now(UTC)
    sla_deadline = datetime.fromtimestamp(now.timestamp() + settings.effective_sla_seconds, tz=UTC)

    record = Complaint(
        id=complaint_id,
        asset_id=asset.id,
        reporter_id=reporter_id,
        title=title,
        description=description,
        category=triage.category.value,
        ward=ward,
        lat=location.lat,
        lng=location.lng,
        status="Reported",
        sub_status="triaged",
        assessed_urgency=triage.urgency.value,
        urgency=priority_breakdown.final_urgency.value,
        impact_score=triage.public_impact.score,
        history_risk=priority_breakdown.history_risk,
        priority_score=priority_breakdown.score,
        department=triage.department.primary.value,
        triage=triage.model_dump(mode="json"),
        min_repair_minutes=triage.min_repair_minutes,
        created_at=now,
        updated_at=now,
        sla_deadline=sla_deadline,
    )
    session.add(record)
    await session.flush()

    # Step 6: Append the passport events.
    await append_event(
        session,
        asset_id=asset.id,
        event_type=EventType.COMPLAINT_REPORTED,
        actor_type=ActorType.CITIZEN,
        actor_id=reporter_id,
        payload={"complaint_id": complaint_id, "title": title},
    )
    await append_event(
        session,
        asset_id=asset.id,
        event_type=EventType.TRIAGE_COMPLETED,
        actor_type=ActorType.SYSTEM,
        payload={
            "complaint_id": complaint_id,
            "category": triage.category.value,
            "urgency": triage.urgency.value,
            "impact_score": triage.public_impact.score,
            "department": triage.department.primary.value,
            "priority_score": priority_breakdown.score,
            "escalated": priority_breakdown.escalated,
        },
    )

    if priority_breakdown.escalated:
        await append_event(
            session,
            asset_id=asset.id,
            event_type=EventType.PRIORITY_ESCALATED,
            actor_type=ActorType.SYSTEM,
            payload={
                "complaint_id": complaint_id,
                "assessed_urgency": triage.urgency.value,
                "final_urgency": priority_breakdown.final_urgency.value,
                "reasons": priority_breakdown.reasons,
            },
        )

    # Step 7: Write the notification outbox row in the same transaction.
    await write_notification(
        session,
        recipient_id=reporter_id,
        recipient_type="citizen",
        event_type=EventType.COMPLAINT_REPORTED.value,
        title="Complaint filed",
        body=f"Your report {complaint_id} has been triaged as {triage.category.value}.",
        complaint_id=complaint_id,
        asset_id=asset.id,
        payload={
            "category": triage.category.value,
            "urgency": triage.urgency.value,
            "department": triage.department.primary.value,
        },
    )

    log.info(
        "intake.complete",
        complaint_id=complaint_id,
        asset_id=asset.id,
        priority_score=priority_breakdown.score,
        urgency=priority_breakdown.final_urgency.value,
    )

    return record
