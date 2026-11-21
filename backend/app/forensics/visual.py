"""Links 3 and 4: visual sufficiency and claim/evidence reconciliation.

One AuditorAgent call produces both links. Every downgrade here protects an
honest officer: a verdict with no cited visible observation, a PASS on a frame
that does not show the defect zone, or an accusation below the configured
confidence floor becomes INCONCLUSIVE. The model never decides closure.
"""

from __future__ import annotations

from app.agents.ports import AuditorAgent, AuditorInput
from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import (
    ClaimVerdict,
    DeficiencyCode,
    Framing,
    LinkName,
    LinkVerdict,
    claim_to_link_verdict,
)
from app.domain.models import ClosureAttempt, Complaint, EvidenceFile
from app.domain.schemas import AssetHistorySnapshot, LinkResult
from app.storage.base import StoragePort

log = get_logger(__name__)

_SEVERITY = {
    ClaimVerdict.SUPPORTED: 0,
    ClaimVerdict.INCONCLUSIVE: 1,
    ClaimVerdict.PARTIAL: 2,
    ClaimVerdict.CONTRADICTED: 3,
}


def _has_observation(text: str | None) -> bool:
    """A usable observation is a real sentence, not a blank or a token."""
    return bool(text and len(text.strip()) >= 8)


async def evaluate_visual(
    auditor: AuditorAgent,
    storage: StoragePort,
    complaint: Complaint,
    attempt: ClosureAttempt,
    before_ev: EvidenceFile | None,
    after_ev: EvidenceFile,
    asset_snapshot: AssetHistorySnapshot | None,
    *,
    defect_claim: str | None = None,
    evidence_required: list[str] | None = None,
) -> tuple[LinkResult, LinkResult, bool, str | None]:
    """Return (link 3, link 4, degraded, model_used).

    defect_claim and evidence_required come from the asset, where they were
    locked at intake. Falling back to the complaint triage blob keeps older
    callers working, but the asset is the authoritative standard.
    """
    settings = get_settings()
    after_bytes = await storage.read(after_ev.storage_key)
    before_bytes = await storage.read(before_ev.storage_key) if before_ev else None

    triage = complaint.triage or {}
    inputs = AuditorInput(
        defect_claim=defect_claim or triage.get("defect_claim", ""),
        evidence_required=evidence_required or triage.get("evidence_required_for_closure", []),
        closure_remarks=attempt.remarks,
        work_order_reference=attempt.work_order_reference,
        before_image_bytes=before_bytes,
        before_image_mime=before_ev.mime_type if before_ev else None,
        after_image_bytes=after_bytes,
        after_image_mime=after_ev.mime_type,
        asset_snapshot=asset_snapshot,
        ward=complaint.ward,
    )

    outcome = await auditor.audit(inputs)
    result = outcome.result
    degraded = outcome.call.degraded
    floor = settings.visual_min_confidence

    sufficiency = result.visual_sufficiency
    l3_verdict = sufficiency.verdict
    l3_reason = sufficiency.reason
    l3_deficiencies: list[DeficiencyCode] = []

    if not _has_observation(l3_reason):
        l3_verdict = LinkVerdict.INCONCLUSIVE
        l3_reason = "Auditor gave no cited visible observation; framing could not be assessed."
    elif l3_verdict is LinkVerdict.PASS and not sufficiency.defect_zone_visible:
        l3_verdict = LinkVerdict.INCONCLUSIVE
        l3_reason = "Frame marked sufficient but the defect zone is not visible in it."
    elif l3_verdict is LinkVerdict.FAIL and result.confidence < floor:
        l3_verdict = LinkVerdict.INCONCLUSIVE
        l3_reason = f"Framing objection below confidence floor ({result.confidence:.2f} < {floor})."

    if l3_verdict is LinkVerdict.FAIL:
        if sufficiency.framing is Framing.WIDE_STREET_VIEW:
            l3_deficiencies.append(DeficiencyCode.WIDE_FRAMING)
        if not sufficiency.defect_zone_visible:
            l3_deficiencies.append(DeficiencyCode.DEFECT_ZONE_NOT_VISIBLE)
        if not l3_deficiencies:
            l3_deficiencies.append(DeficiencyCode.DEFECT_ZONE_NOT_VISIBLE)

    l3 = LinkResult(
        link=LinkName.VISUAL_SUFFICIENCY,
        verdict=l3_verdict,
        reason=l3_reason,
        measured_value=round(result.confidence, 3),
        threshold=floor,
        unit="confidence",
        deficiencies=l3_deficiencies,
    )

    worst = ClaimVerdict.SUPPORTED
    cited: list[str] = []
    for claim in result.claim_assessments:
        verdict = claim.verdict
        if not _has_observation(claim.observation):
            verdict = ClaimVerdict.INCONCLUSIVE
        elif verdict is ClaimVerdict.CONTRADICTED and result.confidence < floor:
            verdict = ClaimVerdict.INCONCLUSIVE
        if _SEVERITY[verdict] > _SEVERITY[worst]:
            worst = verdict
        cited.append(f"{claim.claim}: {claim.observation}")

    l4_verdict = claim_to_link_verdict(worst)
    l4 = LinkResult(
        link=LinkName.CLAIM_EVIDENCE,
        verdict=l4_verdict,
        reason="; ".join(cited) or result.observed_condition,
        deficiencies=[DeficiencyCode.CLAIM_UNSUPPORTED]
        if l4_verdict is LinkVerdict.FAIL
        else [],
    )

    if degraded:
        log.warning("forensics.visual_degraded", attempt_id=attempt.id)

    return l3, l4, degraded, outcome.call.model_used