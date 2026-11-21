"""L6. Remark duplication across the ward corpus.

The Panchkula signature was identical remarks including identical typos, so
normalisation preserves spelling. Exact matches are a hard FAIL; high-cosine
rewordings are DEFICIENT. Both return the matched ticket IDs, never a bare bool.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import DeficiencyCode, LinkName, LinkVerdict
from app.domain.models import ClosureAttempt, Complaint
from app.domain.schemas import LinkResult
from app.tools.dup_text_tool import get_index

log = get_logger(__name__)

_loaded_wards: set[str] = set()


def reset_corpus() -> None:
    """Drop the load cache. Used by tests and by demo reset."""
    _loaded_wards.clear()
    get_index().invalidate()


async def ensure_corpus(session: AsyncSession, ward: str) -> int:
    """Load a ward's prior closure remarks into the index once per process."""
    if ward in _loaded_wards:
        return 0
    stmt = (
        select(ClosureAttempt.complaint_id, ClosureAttempt.remarks)
        .join(Complaint, Complaint.id == ClosureAttempt.complaint_id)
        .where(Complaint.ward == ward)
    )
    index = get_index()
    count = 0
    for complaint_id, remarks in (await session.execute(stmt)).all():
        if remarks and remarks.strip():
            index.upsert(ward, complaint_id, remarks)
            count += 1
    _loaded_wards.add(ward)
    log.debug("forensics.dup_corpus_loaded", ward=ward, remarks=count)
    return count


def remember_remarks(ward: str, complaint_id: str, remarks: str) -> None:
    """Publish a newly submitted remark so the next closure is compared against it."""
    get_index().upsert(ward, complaint_id, remarks)


def evaluate_duplication(ward: str, remarks: str, complaint_id: str) -> LinkResult:
    settings = get_settings()
    threshold = settings.dup_cosine_threshold
    matches = get_index().query(
        ward, remarks, threshold=threshold, exclude_identifier=complaint_id
    )

    if not matches:
        return LinkResult(
            link=LinkName.DUPLICATION,
            verdict=LinkVerdict.PASS,
            reason="Remarks are site-specific; no match in the ward closure corpus.",
            threshold=threshold,
        )

    exact = [m for m in matches if m.exact]
    if exact:
        ids = [m.identifier for m in exact]
        return LinkResult(
            link=LinkName.DUPLICATION,
            verdict=LinkVerdict.FAIL,
            reason=(
                f"Identical closure remarks (including punctuation and spelling) already used on "
                f"{len(ids)} other ticket(s) in {ward}: {', '.join(ids)}."
            ),
            measured_value=1.0,
            threshold=threshold,
            unit="cosine",
            matched_ids=ids,
            deficiencies=[DeficiencyCode.GENERIC_REMARKS],
        )

    near = [m.identifier for m in matches]
    top = max(m.score for m in matches)
    return LinkResult(
        link=LinkName.DUPLICATION,
        verdict=LinkVerdict.DEFICIENT,
        reason=(
            f"Remarks are {top:.2f} similar to closure text on {len(near)} other ticket(s): "
            f"{', '.join(near)}. Describe the work actually done at this location."
        ),
        measured_value=round(top, 4),
        threshold=threshold,
        unit="cosine",
        matched_ids=near,
        deficiencies=[DeficiencyCode.GENERIC_REMARKS],
    )