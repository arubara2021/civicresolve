"""L5b. Perceptual-hash reuse detection. The highest-yield signal in the system.

Corpus scope is prior closure AFTER photographs on this asset or in this ward.
Two exclusions, both deliberate:

The current attempt is excluded, so a photo is never compared with itself or
with the before image submitted alongside it.

Before images are excluded entirely. A genuine repair photographed at the same
spot shares low-frequency layout with the defect photo, so including them would
manufacture false accusations against honest officers.

Prior attempts on the SAME complaint are included. Resubmitting an identical
repair photograph after a rejection is reuse, and it is the cheapest fraud to
commit, so it must be caught.

Reuse requires corroboration: byte-identical content, or a Hamming distance tight
enough that the images are effectively the same photograph. A merely similar
image is advisory context and never blocks closure on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import EvidenceKind
from app.domain.models import Asset, EvidenceFile
from app.domain.schemas import ReuseMatch
from app.tools.phash_tool import build_index, reuse_verdict

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReuseOutcome:
    detected: bool
    reason: str
    matches: list[ReuseMatch] = field(default_factory=list)
    advisory: list[ReuseMatch] = field(default_factory=list)
    closest_distance: int | None = None
    compared: int = 0


async def detect_reuse(
    session: AsyncSession,
    after_evidence: EvidenceFile,
    *,
    ward: str,
    threshold: int | None = None,
) -> ReuseOutcome:
    settings = get_settings()
    limit = threshold if threshold is not None else settings.phash_threshold

    if not after_evidence.phash:
        return ReuseOutcome(False, "Perceptual hash unavailable; reuse could not be assessed.")

    stmt = (
        select(EvidenceFile)
        .join(Asset, Asset.id == EvidenceFile.asset_id)
        .where(
            EvidenceFile.phash.is_not(None),
            EvidenceFile.id != after_evidence.id,
            EvidenceFile.attempt_id.is_not(None),
            EvidenceFile.kind == EvidenceKind.AFTER.value,
            or_(EvidenceFile.asset_id == after_evidence.asset_id, Asset.ward == ward),
        )
    )
    if after_evidence.attempt_id:
        stmt = stmt.where(EvidenceFile.attempt_id != after_evidence.attempt_id)

    prior = list((await session.execute(stmt)).scalars().all())
    if not prior:
        return ReuseOutcome(False, "No prior closure photographs exist to compare against.")

    by_id = {row.id: row for row in prior}
    tree = build_index((row.id, row.phash) for row in prior)
    hits = tree.search(after_evidence.phash, limit)

    confirmed: list[ReuseMatch] = []
    advisory: list[ReuseMatch] = []
    for hit in hits:
        row = by_id[hit.identifier]
        identical = row.content_hash == after_evidence.content_hash
        verdict = reuse_verdict(hit.distance, identical_content=identical, threshold=limit)
        match = ReuseMatch(
            evidence_id=row.id,
            complaint_id=row.complaint_id,
            asset_id=row.asset_id,
            hamming_distance=hit.distance,
        )
        if verdict == "reuse":
            confirmed.append(match)
        elif verdict == "similar":
            advisory.append(match)

    closest = hits[0].distance if hits else None

    if confirmed:
        top = confirmed[0]
        reason = (
            f"Closure photograph reuses prior evidence {top.evidence_id} "
            f"(Hamming {top.hamming_distance}) already submitted for "
            f"{top.complaint_id or 'another ticket'}."
        )
        log.warning(
            "forensics.reuse_detected",
            evidence_id=after_evidence.id,
            matches=len(confirmed),
            compared=len(prior),
        )
        return ReuseOutcome(True, reason, confirmed, advisory, closest, len(prior))

    if advisory:
        return ReuseOutcome(
            False,
            f"A similar prior photograph exists (Hamming {closest}) but is not corroborated "
            "as reuse. Reported as context only.",
            [],
            advisory,
            closest,
            len(prior),
        )

    return ReuseOutcome(
        False,
        "No near-duplicate of this photograph exists in prior closure evidence.",
        closest_distance=closest,
        compared=len(prior),
    )