"""Closure HTTP surface. Both mutating endpoints are idempotent."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFoundError, ValidationFailedError
from app.domain.models import ClosureAttempt
from app.domain.schemas import DecisionIn
from app.modules.closure.service import record_decision, reopen_complaint, submit_attempt

router = APIRouter(tags=["closure"])


def _parseMoment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailedError("work_completed_at must be ISO-8601.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@router.post("/complaints/{complaint_id}/closure-attempts", summary="Submit closure evidence")
async def create_closure_attempt(
    complaint_id: str,
    officer_id: str = Form(..., min_length=3, max_length=64),
    remarks: str = Form(..., min_length=10, max_length=1000),
    work_order_reference: str | None = Form(None),
    work_completed_at: str | None = Form(None),
    after_image: UploadFile = File(..., description="Photo of the repaired zone"),
    before_image: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> ORJSONResponse:
    after_bytes = await after_image.read()
    before_bytes = await before_image.read() if before_image else None

    attempt, report, created = await submit_attempt(
        session,
        complaint_id=complaint_id,
        officer_id=officer_id,
        remarks=remarks,
        after_image=after_bytes,
        after_mime=after_image.content_type,
        before_image=before_bytes,
        before_mime=before_image.content_type if before_image else None,
        work_order_reference=work_order_reference,
        work_completed_at=_parseMoment(work_completed_at),
    )
    await session.commit()
    return ORJSONResponse(
        status_code=201 if created else 200,
        content={
            "attempt_id": attempt.id,
            "attempt_number": attempt.attempt_number,
            "complaint_id": complaint_id,
            "chain_sufficient": report.decision.sufficient,
            "report": report.model_dump(mode="json"),
        },
    )


@router.get("/closure-attempts/{attempt_id}", summary="Get the forensics report")
async def get_attempt(
    attempt_id: str, session: AsyncSession = Depends(get_session)
) -> ORJSONResponse:
    attempt = await session.get(ClosureAttempt, attempt_id)
    if attempt is None:
        raise NotFoundError(f"Closure attempt {attempt_id!r} not found.")
    return ORJSONResponse(
        content={
            "attempt_id": attempt.id,
            "complaint_id": attempt.complaint_id,
            "attempt_number": attempt.attempt_number,
            "chain_sufficient": attempt.chain_sufficient,
            "reuse_detected": attempt.reuse_detected,
            "degraded": attempt.degraded,
            "deficiencies": attempt.deficiencies,
            "report": attempt.forensic_report,
        }
    )


@router.post("/closure-attempts/{attempt_id}/decision", summary="Citizen accept / reject")
async def decide(
    attempt_id: str,
    payload: DecisionIn,
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    decision, complaint, created = await record_decision(
        session, attempt_id=attempt_id, payload=payload
    )
    await session.commit()
    return ORJSONResponse(
        status_code=201 if created else 200,
        content={
            "decision_id": decision.id,
            "attempt_id": attempt_id,
            "decision": decision.decision,
            "status": complaint.status,
            "sub_status": complaint.sub_status,
            "replayed": not created,
        },
    )


@router.post("/complaints/{complaint_id}/reopen", summary="Reopen a resolved complaint")
async def reopen(
    complaint_id: str,
    actor_id: str = Form(..., min_length=3, max_length=64),
    reason: str = Form(..., min_length=5, max_length=1000),
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    complaint = await reopen_complaint(
        session, complaint_id=complaint_id, actor_id=actor_id, reason=reason
    )
    await session.commit()
    return ORJSONResponse(
        content={
            "complaint_id": complaint.id,
            "status": complaint.status,
            "sub_status": complaint.sub_status,
            "reopen_count": complaint.reopen_count,
        }
    )