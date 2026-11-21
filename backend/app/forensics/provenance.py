"""L5a. Provenance and metadata integrity. Defaults to INCONCLUSIVE.

This is NOT AI-image detection. A VLM asked "is this generated?" returns confident
noise. We report only what the file itself states: Content Credentials, editing
software tags, absent camera identity, thumbnail/frame disagreement. Absence is
inconclusive, never an accusation.
"""

from __future__ import annotations

from app.domain.enums import DeficiencyCode, LinkName, LinkVerdict
from app.domain.models import EvidenceFile
from app.domain.schemas import LinkResult

_EDIT_HINTS = (
    "photoshop", "gimp", "lightroom", "snapseed", "affinity",
    "pixelmator", "generative", "firefly", "canva", "picsart",
)


def evaluate_provenance(after_evidence: EvidenceFile) -> LinkResult:
    exif = after_evidence.exif or {}
    c2pa = (after_evidence.c2pa_status or "absent").lower()

    if c2pa in {"invalid", "tampered", "failed"}:
        return LinkResult(
            link=LinkName.PROVENANCE,
            verdict=LinkVerdict.DEFICIENT,
            reason="Content Credentials manifest is present but its signature does not validate.",
            deficiencies=[DeficiencyCode.METADATA_STRIPPED],
        )

    software = after_evidence.software_tag or exif.get("software")
    if software and any(hint in str(software).lower() for hint in _EDIT_HINTS):
        return LinkResult(
            link=LinkName.PROVENANCE,
            verdict=LinkVerdict.DEFICIENT,
            reason=f"File was written by editing software ({software}), not by a camera app.",
            deficiencies=[DeficiencyCode.EDIT_SOFTWARE_DETECTED],
        )

    if exif.get("thumbnail_aspect_mismatch") is True:
        return LinkResult(
            link=LinkName.PROVENANCE,
            verdict=LinkVerdict.INCONCLUSIVE,
            reason="Embedded EXIF thumbnail disagrees with the full frame; the file was re-saved.",
            deficiencies=[DeficiencyCode.METADATA_STRIPPED],
        )

    if not after_evidence.camera_make and not after_evidence.camera_model:
        return LinkResult(
            link=LinkName.PROVENANCE,
            verdict=LinkVerdict.INCONCLUSIVE,
            reason="No camera make or model recorded. Provenance can be neither confirmed nor ruled out.",
            deficiencies=[DeficiencyCode.METADATA_STRIPPED],
        )

    suffix = " Content Credentials present." if c2pa in {"valid", "present"} else ""
    return LinkResult(
        link=LinkName.PROVENANCE,
        verdict=LinkVerdict.PASS,
        reason=(
            f"Camera identity present ({after_evidence.camera_make or ''} "
            f"{after_evidence.camera_model or ''}".strip()
            + f"); no editing software recorded.{suffix}"
        ).strip(),
    )