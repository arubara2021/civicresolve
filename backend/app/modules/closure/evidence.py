"""Validate and store the evidence bundle, then measure it deterministically."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EvidenceUnreadableError
from app.core.ids import IdPrefix
from app.core.logging import get_logger
from app.core.sequences import allocate_id
from app.domain.enums import EvidenceKind
from app.domain.models import ClosureAttempt, Complaint, EvidenceFile
from app.storage.base import StoragePort
from app.tools.exif_tool import extract_exif
from app.tools.phash_tool import compute_dhash, compute_phash

log = get_logger(__name__)


async def store_evidence(
    session: AsyncSession,
    *,
    storage: StoragePort,
    complaint: Complaint,
    attempt: ClosureAttempt,
    data: bytes,
    kind: EvidenceKind,
    mime_type: str | None = None,
    require_exif: bool = False,
) -> EvidenceFile:
    """Store the original untouched and record every deterministic measurement.

    require_exif is opt-in. A browser-reencoded upload that lost its EXIF is a
    DEFICIENCY the audit reports, not a hard rejection — rejecting it outright
    would block honest officers whose phone app strips metadata.
    """
    stored = await storage.save_original(data, mime_type=mime_type)
    exif = extract_exif(data)

    if require_exif and not exif.exif_present:
        raise EvidenceUnreadableError(
            "This file has no EXIF metadata. It was re-saved by a browser or messaging app. "
            "Upload the original camera file, or capture in-app.",
            extra={"warnings": exif.warnings},
        )

    try:
        phash = compute_phash(data)
        dhash = compute_dhash(data)
    except EvidenceUnreadableError:
        phash = dhash = None

    thumbnail_key: str | None = None
    try:
        thumbnail_key = (await storage.make_thumbnail(data)).key
    except EvidenceUnreadableError:
        log.warning("evidence.thumbnail_failed", complaint_id=complaint.id)

    record = EvidenceFile(
        id=await allocate_id(session, IdPrefix.EVIDENCE),
        asset_id=complaint.asset_id,
        complaint_id=complaint.id,
        attempt_id=attempt.id,
        kind=kind.value,
        storage_key=stored.key,
        thumbnail_key=thumbnail_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        phash=phash,
        dhash=dhash,
        exif=exif.model_dump(mode="json"),
        captured_at=exif.captured_at,
        gps_lat=exif.gps.lat if exif.gps else None,
        gps_lng=exif.gps.lng if exif.gps else None,
        camera_make=exif.camera_make,
        camera_model=exif.camera_model,
        software_tag=exif.software,
        c2pa_status="absent",
    )
    session.add(record)
    await session.flush()

    log.info(
        "evidence.stored",
        evidence_id=record.id,
        kind=kind.value,
        exif=exif.exif_present,
        gps=exif.gps is not None,
    )
    return record