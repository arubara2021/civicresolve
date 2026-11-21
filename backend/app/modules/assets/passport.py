"""Asset passport projection.

The passport is the permanent record of a physical location. This module projects
the raw event log into a readable timeline suitable for display. The hash chain
integrity is verified separately; this projection does not trust the cached tip
and recomputes from the events themselves.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Asset
from app.modules.assets.hash_chain import read_events, verify_chain


async def build_passport(session: AsyncSession, asset_id: str) -> dict:
    """Project an asset's event log into a readable passport.

    Returns the asset metadata, the full event timeline, and the chain
    verification result. The chain is recomputed from the events, not trusted
    from the cached tip.
    """
    asset = await session.get(Asset, asset_id)
    if asset is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Asset {asset_id!r} not found.")

    events = await read_events(session, asset_id)
    chain_verification = await verify_chain(session, asset_id)

    timeline = [
        {
            "seq": e.seq,
            "event_type": e.event_type,
            "actor_type": e.actor_type,
            "actor_id": e.actor_id,
            "payload": e.payload,
            "occurred_at": e.occurred_at,
            "event_hash": e.event_hash,
        }
        for e in events
    ]

    return {
        "asset": {
            "id": asset.id,
            "asset_type": asset.asset_type,
            "ward": asset.ward,
            "label": asset.label,
            "lat": asset.lat,
            "lng": asset.lng,
            "radius_m": asset.radius_m,
            "defect_claim": asset.defect_claim,
            "evidence_standard": asset.evidence_standard,
            "min_repair_minutes": asset.min_repair_minutes,
            "created_at": asset.created_at,
            "last_event_seq": asset.last_event_seq,
            "chain_head_hash": asset.chain_head_hash,
        },
        "timeline": timeline,
        "chain_verification": chain_verification.model_dump(mode="json"),
    }
