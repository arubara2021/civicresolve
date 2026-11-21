"""Forensics orchestrator.

Deterministic links run first, then exactly one visual call. The report is
assembled here; the verdict is computed by app.domain.policy.evaluate_chain.
No model output ever sets chain_sufficient.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import get_auditor_agent
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.domain.enums import DeficiencyCode, EvidenceRequirement, LinkName, LinkVerdict
from app.domain.models import Asset, ClosureAttempt, Complaint, EvidenceFile
from app.domain.policy import PolicyParameters, evaluate_chain
from app.domain.schemas import Deficiency, ForensicReport, LinkResult
from app.storage.base import StoragePort
from app.tools.asset_history import build_snapshot

from .duplication import ensure_corpus, evaluate_duplication
from .geospatial import evaluate_geospatial
from .provenance import evaluate_provenance
from .reuse import detect_reuse
from .temporal import evaluate_temporal
from .visual import evaluate_visual

log = get_logger(__name__)

_REMEDIES: dict[DeficiencyCode, str] = {
    DeficiencyCode.MISSING_GEOTAG: "Capture in-app with location enabled, or upload the original camera file.",
    DeficiencyCode.LOCATION_MISMATCH: "Photograph the repaired zone at the reported asset location.",
    DeficiencyCode.WIDE_FRAMING: "Submit a close-up of the repaired zone, not a street view.",
    DeficiencyCode.DEFECT_ZONE_NOT_VISIBLE: "Frame the exact zone named in the intake defect claim.",
    DeficiencyCode.STALE_CAPTURE: "Submit a photograph taken after the complaint was filed.",
    DeficiencyCode.IMPLAUSIBLE_DURATION: "Submit evidence captured after the minimum plausible repair window.",
    DeficiencyCode.CAPTURE_TIME_UNKNOWN: "Upload the original file with EXIF DateTimeOriginal intact.",
    DeficiencyCode.MISSING_WORK_ORDER: "Provide the work-order reference for this repair.",
    DeficiencyCode.GENERIC_REMARKS: "Write site-specific remarks describing the work done here.",
    DeficiencyCode.REUSED_PHOTO: "Submit a new photograph of this repair, not a previously used image.",
    DeficiencyCode.CLAIM_UNSUPPORTED: "Photograph the specific work your remarks claim was performed.",
    DeficiencyCode.METADATA_STRIPPED: "Upload the unedited original from the camera, not a re-saved copy.",
    DeficiencyCode.EDIT_SOFTWARE_DETECTED: "Submit the original capture, not a file exported by an editor.",
}


async def run_pipeline(
    session: AsyncSession,
    storage: StoragePort,
    complaint: Complaint,
    attempt: ClosureAttempt,
    after_evidence: EvidenceFile,
    before_evidence: EvidenceFile | None = None,
) -> ForensicReport:
    settings = get_settings()
    asset = await session.get(Asset, complaint.asset_id)
    if asset is None:
        raise NotFoundError(f"Asset {complaint.asset_id!r} not found.")

    snapshot = await build_snapshot(
        session, complaint.asset_id, exclude_complaint_id=complaint.id
    )

    # Deterministic links. No model, no network.
    temporal = evaluate_temporal(complaint, attempt, after_evidence)
    geospatial = evaluate_geospatial(asset, after_evidence)
    provenance = evaluate_provenance(after_evidence)

    reuse = await detect_reuse(session, after_evidence, ward=complaint.ward)
    if reuse.detected:
        provenance = LinkResult(
            link=LinkName.PROVENANCE,
            verdict=LinkVerdict.FAIL,
            reason=reuse.reason,
            measured_value=float(reuse.closest_distance or 0),
            threshold=float(settings.phash_threshold),
            unit="hamming_bits",
            matched_ids=[m.evidence_id for m in reuse.matches],
            deficiencies=[DeficiencyCode.REUSED_PHOTO],
        )

    await ensure_corpus(session, complaint.ward)
    duplication = evaluate_duplication(complaint.ward, attempt.remarks, complaint.id)

    # One visual call. Degrades, never fails open.
    degraded = False
    model_used: str | None = None
    try:
        l3, l4, degraded, model_used = await evaluate_visual(
            get_auditor_agent(),
            storage,
            complaint,
            attempt,
            before_evidence,
            after_evidence,
            snapshot,
            defect_claim=asset.defect_claim,
            evidence_required=list(asset.evidence_standard or []),
        )
    except AppError as exc:
        degraded = True
        detail = f"Visual audit unavailable: {exc.detail}"
        log.warning("forensics.visual_unavailable", attempt_id=attempt.id, detail=exc.detail)
        l3 = LinkResult(link=LinkName.VISUAL_SUFFICIENCY, verdict=LinkVerdict.INCONCLUSIVE, reason=detail)
        l4 = LinkResult(link=LinkName.CLAIM_EVIDENCE, verdict=LinkVerdict.INCONCLUSIVE, reason=detail)

    links = [temporal, geospatial, l3, l4, provenance, duplication]

    # Mandatory evidence, fixed at intake.
    required: list[EvidenceRequirement] = []
    for raw in asset.evidence_standard or []:
        try:
            required.append(EvidenceRequirement(raw))
        except ValueError:
            continue

    missing: list[EvidenceRequirement] = []
    if EvidenceRequirement.GEO_TAGGED_CLOSEUP in required and (
        after_evidence.gps_lat is None or after_evidence.gps_lng is None
    ):
        missing.append(EvidenceRequirement.GEO_TAGGED_CLOSEUP)
    if EvidenceRequirement.CAPTURE_AFTER_COMPLETION in required and after_evidence.captured_at is None:
        missing.append(EvidenceRequirement.CAPTURE_AFTER_COMPLETION)
    if EvidenceRequirement.WORK_ORDER_REFERENCE in required and not attempt.work_order_reference:
        missing.append(EvidenceRequirement.WORK_ORDER_REFERENCE)
    if EvidenceRequirement.BEFORE_AFTER_PAIR in required and before_evidence is None:
        missing.append(EvidenceRequirement.BEFORE_AFTER_PAIR)
    if (
        EvidenceRequirement.SITE_SPECIFIC_REMARKS in required
        and duplication.verdict is LinkVerdict.FAIL
    ):
        missing.append(EvidenceRequirement.SITE_SPECIFIC_REMARKS)

    # The only place sufficiency is decided.
    decision = evaluate_chain(
        links,
        reuse_detected=reuse.detected,
        missing_evidence=missing,
        parameters=PolicyParameters(max_inconclusive=settings.max_inconclusive),
    )

    deficiencies: list[Deficiency] = []
    seen: set[DeficiencyCode] = set()
    for link in links:
        for code in link.deficiencies:
            if code in seen:
                continue
            seen.add(code)
            deficiencies.append(
                Deficiency(
                    code=code,
                    message=link.reason,
                    remedy=_REMEDIES.get(code, "Submit compliant evidence."),
                    link=link.link,
                )
            )
    for req in missing:
        code = (
            DeficiencyCode.MISSING_WORK_ORDER
            if req is EvidenceRequirement.WORK_ORDER_REFERENCE
            else DeficiencyCode.CAPTURE_TIME_UNKNOWN
            if req is EvidenceRequirement.CAPTURE_AFTER_COMPLETION
            else DeficiencyCode.MISSING_GEOTAG
        )
        if code in seen:
            continue
        seen.add(code)
        deficiencies.append(
            Deficiency(
                code=code,
                message=f"Missing mandatory evidence fixed at intake: {req.value}.",
                remedy=_REMEDIES.get(code, "Submit the required evidence."),
            )
        )

    report = ForensicReport(
        attempt_id=attempt.id,
        complaint_id=complaint.id,
        asset_id=complaint.asset_id,
        links=links,
        reuse_detected=reuse.detected,
        reuse_matches=reuse.matches,
        missing_evidence=missing,
        decision=decision,
        deficiencies=deficiencies,
        observed_condition=l4.reason,
        model_used=model_used,
        degraded=degraded,
        generated_at=datetime.now(UTC),
    )

    log.info(
        "forensics.report",
        attempt_id=attempt.id,
        chain_sufficient=decision.sufficient,
        reuse=reuse.detected,
        degraded=degraded,
        blocking=decision.blocking_reasons,
    )
    return report
