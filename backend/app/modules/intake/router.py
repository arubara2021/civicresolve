"""Intake HTTP surface.

POST /api/complaints accepts multipart form data: title, description, location
(as lat and lng floats), category hint (optional), reporter_id, ward, and an
optional image file. The image is genuinely optional — the endpoint works without
it, which is important because many reports will be text-only.

The router does minimal work: parse the form, validate the inputs, call the
service, and return the complaint summary. The service owns the transaction.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import ORJSONResponse

from app.core.db import get_session
from app.domain.schemas import ComplaintSummary, GeoPoint
from app.modules.intake.service import submit_complaint

router = APIRouter(prefix="/complaints", tags=["intake"])


def _parse_location(lat: str, lng: str) -> GeoPoint:
    """Parse and validate lat/lng strings. FastAPI's Form does not coerce floats."""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError) as exc:
        raise ValueError("lat and lng must be valid floating-point numbers") from exc
    return GeoPoint(lat=lat_f, lng=lng_f)


async def _read_image(file: UploadFile | None) -> tuple[bytes | None, str | None]:
    """Read the uploaded image if present. Returns (bytes, mime) or (None, None)."""
    if file is None or file.filename is None:
        return None, None

    data = await file.read()
    if not data:
        return None, None

    mime = file.content_type
    if mime is None:
        mime = "image/jpeg"

    return data, mime


@router.post(
    "",
    response_model=ComplaintSummary,
    summary="Submit a civic complaint",
    description=(
        "Accepts multipart form data with title, description, location (lat/lng), "
        "optional category hint, reporter_id, ward, and an optional image. "
        "Returns the triaged complaint with AI-assigned category, urgency, "
        "department, and priority score."
    ),
)
async def create_complaint(
    title: str = Form(..., min_length=5, max_length=140),
    description: str = Form(..., min_length=10, max_length=2000),
    lat: str = Form(..., description="Latitude as a floating-point string"),
    lng: str = Form(..., description="Longitude as a floating-point string"),
    category_hint: str | None = Form(None, description="Optional category hint"),
    reporter_id: str = Form(..., min_length=3, max_length=64),
    ward: str = Form("WARD-DEMO", min_length=2, max_length=32),
    image: UploadFile | None = File(None, description="Optional photo of the issue"),
) -> ORJSONResponse:
    """Submit a complaint. The image is optional; the endpoint works without it."""
    try:
        location = _parse_location(lat, lng)
    except ValueError as exc:
        from app.core.errors import ValidationFailedError

        raise ValidationFailedError(str(exc)) from exc

    image_bytes, image_mime = await _read_image(image)

    async for session in get_session():
        complaint = await submit_complaint(
            session,
            title=title,
            description=description,
            location=location,
            category_hint=category_hint,
            reporter_id=reporter_id,
            ward=ward,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        await session.commit()

        summary = ComplaintSummary(
            complaint_id=complaint.id,
            asset_id=complaint.asset_id,
            title=complaint.title,
            category=complaint.category,
            status=complaint.status,
            sub_status=complaint.sub_status,
            sub_status_label="Triaged by AI",
            urgency=complaint.urgency,
            priority_score=complaint.priority_score,
            department=complaint.department,
            department_label=complaint.department.replace("_", " ").title(),
            ward=complaint.ward,
            created_at=complaint.created_at,
            sla_deadline=complaint.sla_deadline,
            reopen_count=complaint.reopen_count,
        )
        return ORJSONResponse(
            status_code=201,
            content=summary.model_dump(mode="json"),
        )

    raise RuntimeError("Session iterator exhausted without yielding")
