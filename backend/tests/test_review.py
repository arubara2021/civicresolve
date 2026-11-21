"""Checkpoint 9. Silence escalates, never closes. A passing chain rejected by the
citizen reaches a reviewer, and the override is justified and permanent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.ids import IdPrefix
from app.core.sequences import allocate_id

from app.core.errors import InvalidStateTransitionError
from app.domain.enums import (
    ActorType,
    Category,
    DecisionType,
    EventType,
    Status,
    SubStatus,
    Urgency,
)
from app.domain.models import Asset, ClosureAttempt, Complaint, Decision, Event
from app.domain.schemas import ReviewDecisionIn
from app.modules.review.service import (
    get_escalation,
    list_escalations,
    quorum_status,
    review_decision,
)
from app.modules.review.sla import run_sla_sweep

JUSTIFICATION = "Site inspection on 21 Nov confirmed the patch is complete and compacted."
REMARKS = "Left wheel path pothole cut and filled with bitumen mix, compacted, edge sealed."


def _now() -> datetime:
    return datetime.now(UTC)


async def _seed(
    session: AsyncSession,
    *,
    asset_id: str,
    complaint_id: str,
    attempt_id: str,
    sub_status: SubStatus,
    chain_sufficient: bool,
    sla_offset_s: int,
    reporter_id: str = "CIT-201",
    status: Status = Status.IN_PROGRESS,
) -> Complaint:
    if await session.get(Asset, asset_id) is None:
        session.add(
            Asset(
                id=asset_id,
                ward="WARD-12",
                label="MG Road service lane",
                lat=28.45950,
                lng=77.02660,
                defect_claim="unfilled pothole in left wheel path",
                evidence_standard=[],
                min_repair_minutes=120,
            )
        )
        await session.flush()

    complaint = Complaint(
        id=complaint_id,
        asset_id=asset_id,
        reporter_id=reporter_id,
        title="Pothole near school gate",
        description="Two scooter riders almost fell.",
        category=Category.POTHOLE.value,
        ward="WARD-12",
        lat=28.45952,
        lng=77.02663,
        status=status.value,
        sub_status=sub_status.value,
        urgency=Urgency.P1.value,
        priority_score=79.9,
        department="roads_maintenance",
        attempt_count=1,
        created_at=_now() - timedelta(hours=4),
        sla_deadline=_now() + timedelta(seconds=sla_offset_s),
    )
    session.add(complaint)
    await session.flush()

    session.add(
        ClosureAttempt(
            id=attempt_id,
            complaint_id=complaint_id,
            asset_id=asset_id,
            attempt_number=1,
            officer_id="OFF-117",
            remarks=REMARKS,
            work_order_reference="WO/4471",
            chain_sufficient=chain_sufficient,
            audited_at=_now() - timedelta(seconds=90),
            forensic_report={"decision": {"sufficient": chain_sufficient}},
        )
    )
    await session.commit()
    return complaint


@pytest.fixture
async def awaiting(session: AsyncSession) -> Complaint:
    """Chain passed, citizen has gone silent, window already elapsed."""
    return await _seed(
        session,
        asset_id="AST-0042",
        complaint_id="WRD-1071",
        attempt_id="ATT-0001",
        sub_status=SubStatus.AWAITING_CITIZEN,
        chain_sufficient=True,
        sla_offset_s=-5,
    )


@pytest.fixture
async def rejected_pass(session: AsyncSession) -> Complaint:
    """Chain passed but the citizen rejected. Already routed to a reviewer."""
    complaint = await _seed(
        session,
        asset_id="AST-0043",
        complaint_id="WRD-1072",
        attempt_id="ATT-0002",
        sub_status=SubStatus.ESCALATED,
        chain_sufficient=True,
        sla_offset_s=3600,
    )
    session.add(
        Decision(
            id=await allocate_id(session, IdPrefix.DECISION),
            attempt_id="ATT-0002",
            complaint_id=complaint.id,
            actor_type=ActorType.CITIZEN.value,
            actor_id="CIT-201",
            decision=DecisionType.REJECT.value,
            reason="I do not believe anyone came to the site.",
            chain_sufficient_at_decision=True,
        )
    )
    await session.commit()
    return complaint


async def test_silent_citizen_escalates_and_is_never_auto_closed(
    session: AsyncSession, awaiting: Complaint
) -> None:
    escalated = await run_sla_sweep(session)
    await session.commit()

    assert escalated == ["WRD-1071"]
    refreshed = await session.get(Complaint, "WRD-1071")
    assert refreshed.status == Status.IN_PROGRESS.value
    assert refreshed.sub_status == SubStatus.ESCALATED.value
    assert refreshed.resolved_at is None

    types = [
        row.event_type
        for row in (await session.execute(select(Event).order_by(Event.seq))).scalars()
    ]
    assert EventType.SLA_EXPIRED.value in types
    assert EventType.ESCALATED.value in types


async def test_sweep_is_idempotent(session: AsyncSession, awaiting: Complaint) -> None:
    first = await run_sla_sweep(session)
    await session.commit()
    second = await run_sla_sweep(session)
    assert first == ["WRD-1071"]
    assert second == []


async def test_sweep_never_touches_a_resolved_complaint(session: AsyncSession) -> None:
    await _seed(
        session,
        asset_id="AST-0044",
        complaint_id="WRD-1073",
        attempt_id="ATT-0003",
        sub_status=SubStatus.CITIZEN_ACCEPTED,
        chain_sufficient=True,
        sla_offset_s=-500,
        status=Status.RESOLVED,
    )
    assert await run_sla_sweep(session) == []


async def test_sweep_ignores_a_case_still_inside_its_window(session: AsyncSession) -> None:
    await _seed(
        session,
        asset_id="AST-0045",
        complaint_id="WRD-1074",
        attempt_id="ATT-0004",
        sub_status=SubStatus.AWAITING_CITIZEN,
        chain_sufficient=True,
        sla_offset_s=60,
    )
    assert await run_sla_sweep(session) == []


async def test_chain_pass_rejection_appears_in_the_reviewer_queue(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    items, total = await list_escalations(session)
    assert total == 1
    assert items[0]["complaint_id"] == "WRD-1072"
    assert items[0]["reason"] == "chain_pass_citizen_rejected"
    assert items[0]["officer_protection_flag"] is True


async def test_escalation_detail_carries_the_report_and_allowed_actions(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    detail = await get_escalation(session, "WRD-1072")
    assert detail["forensic_report"] is not None
    assert detail["officer_protection"]["flag"] is True
    assert "reviewer_resolve" in detail["allowed_actions"]
    assert "reviewer_return" in detail["allowed_actions"]
    assert detail["quorum"]["met"] is True


async def test_reviewer_override_resolves_and_logs_the_justification(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    decision, complaint, created = await review_decision(
        session,
        complaint_id="WRD-1072",
        payload=ReviewDecisionIn(
            reviewer_id="REV-01",
            decision=DecisionType.ACCEPT,
            justification=JUSTIFICATION,
        ),
    )
    await session.commit()

    assert created is True
    assert complaint.status == Status.RESOLVED.value
    assert complaint.sub_status == SubStatus.REVIEWER_OVERRIDE.value
    assert complaint.resolved_at is not None

    event = (
        await session.execute(
            select(Event).where(Event.event_type == EventType.REVIEWER_OVERRIDE.value)
        )
    ).scalars().one()
    assert event.payload["justification"] == JUSTIFICATION
    assert event.payload["chain_sufficient_at_decision"] is True
    assert event.actor_id == "REV-01"
    assert decision.chain_sufficient_at_decision is True


async def test_reviewer_return_sends_it_back_to_the_department(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    _, complaint, _ = await review_decision(
        session,
        complaint_id="WRD-1072",
        payload=ReviewDecisionIn(
            reviewer_id="REV-01",
            decision=DecisionType.REJECT,
            justification=JUSTIFICATION,
        ),
    )
    await session.commit()
    assert complaint.status == Status.IN_PROGRESS.value
    assert complaint.sub_status == SubStatus.DISPUTED.value
    assert complaint.failed_attempt_count == 1


async def test_review_is_idempotent(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    payload = ReviewDecisionIn(
        reviewer_id="REV-01", decision=DecisionType.ACCEPT, justification=JUSTIFICATION
    )
    first, _, created_first = await review_decision(
        session, complaint_id="WRD-1072", payload=payload
    )
    await session.commit()
    second, _, created_second = await review_decision(
        session, complaint_id="WRD-1072", payload=payload
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


async def test_a_resolved_case_cannot_be_overridden_again(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    await review_decision(
        session,
        complaint_id="WRD-1072",
        payload=ReviewDecisionIn(
            reviewer_id="REV-01", decision=DecisionType.ACCEPT, justification=JUSTIFICATION
        ),
    )
    await session.commit()
    with pytest.raises(InvalidStateTransitionError):
        await review_decision(
            session,
            complaint_id="WRD-1072",
            payload=ReviewDecisionIn(
                reviewer_id="REV-02",
                decision=DecisionType.ACCEPT,
                justification=JUSTIFICATION,
            ),
        )


def test_short_justification_is_rejected_at_the_boundary() -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionIn(
            reviewer_id="REV-01", decision=DecisionType.ACCEPT, justification="looks fine"
        )


async def test_quorum_requires_two_acceptances_on_a_multi_reporter_asset(
    session: AsyncSession, rejected_pass: Complaint
) -> None:
    await _seed(
        session,
        asset_id="AST-0043",
        complaint_id="WRD-1080",
        attempt_id="ATT-0080",
        sub_status=SubStatus.AWAITING_CITIZEN,
        chain_sufficient=True,
        sla_offset_s=3600,
        reporter_id="CIT-999",
    )
    status = await quorum_status(session, rejected_pass)
    assert status["reporters"] == 2
    assert status["required"] == 2
    assert status["accepts"] == 0
    assert status["met"] is False