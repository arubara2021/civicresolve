"""Link 1: Temporal Integrity.

Verifies that the closure evidence was captured after the complaint was filed,
and that the time elapsed is physically plausible for the category of repair.
Missing capture timestamps are treated as an evidentiary deficiency rather than
an automatic failure, because most messaging apps strip EXIF.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.enums import DeficiencyCode, LinkName, LinkVerdict
from app.domain.models import Complaint, EvidenceFile, ClosureAttempt
from app.domain.schemas import LinkResult


def evaluate_temporal(
    complaint: Complaint,
    attempt: ClosureAttempt,
    after_evidence: EvidenceFile,
) -> LinkResult:
    """Check if the evidence was captured after the complaint and after a plausible repair time."""
    captured = after_evidence.captured_at or attempt.work_completed_at

    if captured is None:
        return LinkResult(
            link=LinkName.TEMPORAL,
            verdict=LinkVerdict.DEFICIENT,
            reason="No capture timestamp available in EXIF or submission.",
            deficiencies=[DeficiencyCode.CAPTURE_TIME_UNKNOWN],
        )

    # Ensure timezone awareness for comparison
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    created = (
        complaint.created_at.replace(tzinfo=UTC)
        if complaint.created_at.tzinfo is None
        else complaint.created_at
    )

    delta_minutes = (captured - created).total_seconds() / 60.0

    if delta_minutes < 0:
        return LinkResult(
            link=LinkName.TEMPORAL,
            verdict=LinkVerdict.FAIL,
            reason=f"Evidence captured {abs(delta_minutes):.0f} min BEFORE complaint.",
            measured_value=delta_minutes,
            threshold=0,
            unit="minutes",
            deficiencies=[DeficiencyCode.STALE_CAPTURE],
        )

    if delta_minutes < complaint.min_repair_minutes:
        return LinkResult(
            link=LinkName.TEMPORAL,
            verdict=LinkVerdict.FAIL,
            reason=f"Repair took {delta_minutes:.0f} min; minimum plausible is {complaint.min_repair_minutes} min.",
            measured_value=delta_minutes,
            threshold=float(complaint.min_repair_minutes),
            unit="minutes",
            deficiencies=[DeficiencyCode.IMPLAUSIBLE_DURATION],
        )

    return LinkResult(
        link=LinkName.TEMPORAL,
        verdict=LinkVerdict.PASS,
        reason=f"Evidence captured {delta_minutes:.0f} min after complaint.",
        measured_value=delta_minutes,
        threshold=float(complaint.min_repair_minutes),
        unit="minutes",
    )
