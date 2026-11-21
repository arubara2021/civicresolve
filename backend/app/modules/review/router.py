"""Reviewer HTTP surface.

GET  /api/escalations                  the queue, priority-sorted
GET  /api/escalations/{complaint_id}   everything needed to adjudicate
POST /api/escalations/{complaint_id}/review   override or return, idempotent

Justification is mandatory at the schema boundary, so a request without it fails
validation before any state is touched.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.domain.schemas import ReviewDecisionIn
from app.modules.review.service import get_escalation, list_escalations, review_decision

router = APIRouter(prefix="/escalations", tags=["review"])


@router.get("", summary="List the reviewer escalation queue")
async def list_queue(
    ward: str | None = Query(None, description="Filter by ward"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    items, total = await list_escalations(session, ward=ward, limit=limit, offset=offset)
    return ORJSONResponse(content={"total": total, "returned": len(items), "items": items})


@router.get("/{complaint_id}", summary="Get one escalation with full context")
async def get_one(
    complaint_id: str, session: AsyncSession = Depends(get_session)
) -> ORJSONResponse:
    return ORJSONResponse(content=await get_escalation(session, complaint_id))


@router.post("/{complaint_id}/review", summary="Reviewer override or return")
async def review(
    complaint_id: str,
    payload: ReviewDecisionIn,
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    decision, complaint, created = await review_decision(
        session, complaint_id=complaint_id, payload=payload
    )
    await session.commit()
    return ORJSONResponse(
        status_code=201 if created else 200,
        content={
            "decision_id": decision.id,
            "complaint_id": complaint.id,
            "attempt_id": decision.attempt_id,
            "decision": decision.decision,
            "status": complaint.status,
            "sub_status": complaint.sub_status,
            "justification": decision.reason,
            "replayed": not created,
        },
    )