"""Demo affordances. All routes are disabled when environment is production.

The evidence endpoint stamps a fresh capture time on demand. A photograph
generated before the complaint was filed would fail the temporal link, so the
honest capture must be minted at the moment the operator needs it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Path
from fastapi.responses import ORJSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.domain.models import Complaint
from scripts.inject_exif import KINDS, build_scene
from scripts.seed import demo_state, load_fixture, reset_demo

router = APIRouter(prefix="/demo", tags=["demo"])


def _guard() -> None:
    if not get_settings().demo_reset_enabled:
        raise ForbiddenError("Demo endpoints are disabled in this environment.")


@router.post("/reset", summary="Restore the seeded demo ward")
async def reset(session: AsyncSession = Depends(get_session)) -> ORJSONResponse:
    _guard()
    summary = await reset_demo(session)
    await session.commit()
    return ORJSONResponse(content={"reset": True, **summary})


@router.get("/state", summary="Row counts and the fixture narrative")
async def state(session: AsyncSession = Depends(get_session)) -> ORJSONResponse:
    _guard()
    fixture = load_fixture()
    return ORJSONResponse(
        content={
            "counts": await demo_state(session),
            "asset_id": fixture["asset"]["id"],
            "live_complaint_id": fixture["live_complaint"]["id"],
            "reused_remarks": fixture["closure_remarks"]["reused"],
            "honest_remarks": fixture["closure_remarks"]["honest"],
            "fake_submission": fixture["fake_submission"],
            "honest_submission": fixture["honest_submission"],
        }
    )


@router.get("/evidence/{kind}", summary="Download a demo photograph with fresh EXIF")
async def evidence(
    kind: str = Path(..., description=f"One of {KINDS}"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _guard()
    if kind not in KINDS:
        raise NotFoundError(f"Unknown evidence kind {kind!r}; expected one of {list(KINDS)}.")

    fixture = load_fixture()
    moment = datetime.now(UTC)
    if kind == "before":
        live = await session.get(Complaint, fixture["live_complaint"]["id"])
        if live is not None:
            moment = live.created_at

    data = build_scene(kind, captured_at=moment)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{kind}.jpg"',
            "Cache-Control": "no-store",
        },
    )