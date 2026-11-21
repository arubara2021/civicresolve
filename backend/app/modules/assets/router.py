"""Asset passport and chain verification.

GET /api/assets/{id}/passport — full passport with timeline and chain verification
GET /api/assets/{id}/verify-chain — recompute chain integrity

The passport is the permanent record. The verify-chain endpoint is a diagnostic
that recomputes the hash chain and reports any tampering.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.assets.hash_chain import verify_chain
from app.modules.assets.passport import build_passport

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get(
    "/{asset_id}/passport",
    summary="Get asset passport with timeline and chain verification",
    description="Return the full asset passport: metadata, event timeline, and chain integrity.",
)
async def get_passport(
    asset_id: str,
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    """Return the asset passport."""
    passport = await build_passport(session, asset_id)
    return ORJSONResponse(content=passport)


@router.get(
    "/{asset_id}/verify-chain",
    summary="Recompute and verify the asset's hash chain",
    description="Recompute the hash chain from the events and report any tampering.",
)
async def verify_asset_chain(
    asset_id: str,
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    """Verify the hash chain integrity for an asset."""
    verification = await verify_chain(session, asset_id)
    return ORJSONResponse(content=verification.model_dump(mode="json"))
