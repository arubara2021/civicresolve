"""Complaint query and admin status management.

GET /api/complaints — list with filters, priority-sorted
GET /api/complaints/{id} — detail with timeline and attempts
PATCH /api/complaints/{id}/status — admin action via state machine

The status endpoint does not accept a target state. It accepts an action and lets
the state machine decide the legal transition. This is what prevents an admin from
setting status to Resolved without going through the closure protocol.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.domain.schemas import (
    ComplaintSummary,
    PassportEvent,
    StatusUpdate,
)
from app.modules.complaints.service import (
    get_complaint,
    get_complaint_attempts,
    get_complaint_decisions,
    get_complaint_timeline,
    list_complaints,
    update_status,
)

router = APIRouter(prefix="/complaints", tags=["complaints"])


@router.get(
    "",
    summary="List complaints with filters",
    description=(
        "Return a priority-sorted list of complaints. Filters: ward, status, "
        "department, urgency. Defaults: limit 50, offset 0."
    ),
)
async def list_complaints_endpoint(
    ward: str | None = Query(None, description="Filter by ward"),
    status: str | None = Query(None, description="Filter by status"),
    department: str | None = Query(None, description="Filter by department"),
    urgency: str | None = Query(None, description="Filter by urgency"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    """List complaints with optional filters."""
    records, total = await list_complaints(
        session,
        ward=ward,
        status=status,
        department=department,
        urgency=urgency,
        limit=limit,
        offset=offset,
    )

    summaries = [
        ComplaintSummary(
            complaint_id=r.id,
            asset_id=r.asset_id,
            title=r.title,
            category=r.category,
            status=r.status,
            sub_status=r.sub_status,
            sub_status_label=r.sub_status.replace("_", " ").title(),
            urgency=r.urgency,
            priority_score=r.priority_score,
            department=r.department,
            department_label=r.department.replace("_", " ").title(),
            ward=r.ward,
            created_at=r.created_at,
            sla_deadline=r.sla_deadline,
            reopen_count=r.reopen_count,
        )
        for r in records
    ]

    return ORJSONResponse(
        content={
            "total": total,
            "returned": len(summaries),
            "items": [s.model_dump(mode="json") for s in summaries],
        }
    )


@router.get(
    "/{complaint_id}",
    summary="Get complaint detail with timeline",
    description="Return full complaint detail, timeline events, closure attempts, and decisions.",
)
async def get_complaint_detail(
    complaint_id: str,
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    """Return full complaint detail with timeline and attempts."""
    complaint = await get_complaint(session, complaint_id)
    timeline = await get_complaint_timeline(session, complaint_id)
    attempts = await get_complaint_attempts(session, complaint_id)
    decisions = await get_complaint_decisions(session, complaint_id)

    detail = {
        "complaint": {
            "id": complaint.id,
            "asset_id": complaint.asset_id,
            "reporter_id": complaint.reporter_id,
            "title": complaint.title,
            "description": complaint.description,
            "category": complaint.category,
            "status": complaint.status,
            "sub_status": complaint.sub_status,
            "urgency": complaint.urgency,
            "priority_score": complaint.priority_score,
            "department": complaint.department,
            "assignee_department": complaint.assignee_department,
            "ward": complaint.ward,
            "lat": complaint.lat,
            "lng": complaint.lng,
            "triage": complaint.triage,
            "created_at": complaint.created_at,
            "updated_at": complaint.updated_at,
            "sla_deadline": complaint.sla_deadline,
            "reopen_count": complaint.reopen_count,
            "attempt_count": complaint.attempt_count,
            "failed_attempt_count": complaint.failed_attempt_count,
        },
        "timeline": [
            PassportEvent(
                event_id=e.id,
                asset_id=e.asset_id,
                seq=e.seq,
                event_type=e.event_type,
                actor_type=e.actor_type,
                actor_id=e.actor_id,
                payload=e.payload,
                occurred_at=e.occurred_at,
                prev_hash=e.prev_hash,
                event_hash=e.event_hash,
            ).model_dump(mode="json")
            for e in timeline
        ],
        "attempts": [
            {
                "id": a.id,
                "attempt_number": a.attempt_number,
                "officer_id": a.officer_id,
                "remarks": a.remarks,
                "work_order_reference": a.work_order_reference,
                "submitted_at": a.submitted_at,
                "chain_sufficient": a.chain_sufficient,
                "reuse_detected": a.reuse_detected,
                "deficiencies": a.deficiencies,
            }
            for a in attempts
        ],
        "decisions": [
            {
                "id": d.id,
                "attempt_id": d.attempt_id,
                "actor_type": d.actor_type,
                "actor_id": d.actor_id,
                "decision": d.decision,
                "reason": d.reason,
                "created_at": d.created_at,
            }
            for d in decisions
        ],
    }

    return ORJSONResponse(content=detail)


@router.patch(
    "/{complaint_id}/status",
    summary="Update complaint status via state machine action",
    description=(
        "Move the complaint forward by invoking an action. The state machine "
        "decides the legal transition. Admin cannot set status to Resolved directly."
    ),
)
async def update_complaint_status(
    complaint_id: str,
    action: StatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    """Update complaint status via an action on the state machine."""
    complaint = await update_status(session, complaint_id=complaint_id, action=action)
    await session.commit()

    summary = ComplaintSummary(
        complaint_id=complaint.id,
        asset_id=complaint.asset_id,
        title=complaint.title,
        category=complaint.category,
        status=complaint.status,
        sub_status=complaint.sub_status,
        sub_status_label=complaint.sub_status.replace("_", " ").title(),
        urgency=complaint.urgency,
        priority_score=complaint.priority_score,
        department=complaint.department,
        department_label=complaint.department.replace("_", " ").title(),
        ward=complaint.ward,
        created_at=complaint.created_at,
        sla_deadline=complaint.sla_deadline,
        reopen_count=complaint.reopen_count,
    )
    return ORJSONResponse(content=summary.model_dump(mode="json"))
