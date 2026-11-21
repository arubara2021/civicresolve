"""Asset matching and creation.

The unit of record is the physical location, not the complaint. This service owns
the decision of whether an incoming report belongs to an existing asset or opens a
new one. The threshold is configurable but the logic is deterministic: if a report
falls within the asset's radius, it attaches; otherwise a new asset opens.

The evidentiary standard is locked at intake time. defect_claim and
evidence_required_for_closure are written to the asset before the repairing party
is known, so they cannot be quietly lowered at closure time by the party being
audited. That ordering is the load-bearing design decision of the whole system.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import IdPrefix
from app.core.logging import get_logger
from app.core.sequences import allocate_id
from app.domain.models import Asset
from app.domain.schemas import GeoPoint, TriageResult
from app.tools.geo_tool import haversine_m

log = get_logger(__name__)


async def find_matching_asset(
    session: AsyncSession,
    location: GeoPoint,
    *,
    tolerance_m: float | None = None,
) -> Asset | None:
    """Return the closest asset within tolerance, or None if no asset is close enough.

    This is a simple brute-force scan. At prototype scale it is fast enough and
    avoids the complexity of a spatial index. A production deployment with thousands
    of assets would swap this for a PostGIS query or an in-memory R-tree.
    """
    settings = get_settings()
    radius = tolerance_m if tolerance_m is not None else settings.geo_tolerance_m

    statement = select(Asset).order_by(Asset.created_at.desc())
    assets = (await session.execute(statement)).scalars().all()

    best_match: Asset | None = None
    best_distance = float("inf")

    for asset in assets:
        distance = haversine_m(location, GeoPoint(lat=asset.lat, lng=asset.lng))
        if distance <= radius and distance < best_distance:
            best_match = asset
            best_distance = distance

    if best_match is not None:
        log.debug(
            "asset.matched",
            asset_id=best_match.id,
            distance_m=round(best_distance, 1),
            radius_m=radius,
        )
    else:
        log.debug("asset.no_match", radius_m=radius, candidates=len(assets))

    return best_match


async def create_asset(
    session: AsyncSession,
    *,
    location: GeoPoint,
    triage: TriageResult,
    ward: str,
    label: str | None = None,
) -> Asset:
    """Open a new asset and lock the evidentiary standard from the triage result.

    The label defaults to a short summary of the defect claim. The evidentiary
    standard is persisted as a JSON list of EvidenceRequirement enum values so it
    can be queried and displayed without re-running the model.
    """
    asset_id = await allocate_id(session, IdPrefix.ASSET)
    record = Asset(
        id=asset_id,
        asset_type="civic_asset",
        ward=ward,
        label=label or triage.defect_claim[:140],
        lat=location.lat,
        lng=location.lng,
        radius_m=get_settings().geo_tolerance_m,
        defect_claim=triage.defect_claim,
        evidence_standard=[req.value for req in triage.evidence_required_for_closure],
        min_repair_minutes=triage.min_repair_minutes,
    )
    session.add(record)
    await session.flush()

    log.info("asset.created", asset_id=asset_id, ward=ward, defect_claim=triage.defect_claim)
    return record


async def match_or_create(
    session: AsyncSession,
    *,
    location: GeoPoint,
    triage: TriageResult,
    ward: str,
) -> tuple[Asset, bool]:
    """Match an existing asset or create a new one. Returns (asset, was_created)."""
    matched = await find_matching_asset(session, location)
    if matched is not None:
        return matched, False

    created = await create_asset(session, location=location, triage=triage, ward=ward)
    return created, True
