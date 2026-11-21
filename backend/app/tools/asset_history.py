"""Asset failure history, assembled for the priority function.

This is the tool that makes the passport load-bearing rather than decorative: it
turns a location's record of declared fixes and subsequent re-reports into the
history term of the mandatory priority feature.

A reopen is counted from the complaint counters rather than inferred from status,
because a reopened complaint is no longer in a resolved state and would otherwise
erase its own history.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import DecisionType, Status
from app.domain.models import ClosureAttempt, Complaint, Decision, utcnow
from app.domain.schemas import AssetHistorySnapshot


async def build_snapshot(
    session: AsyncSession,
    asset_id: str,
    *,
    exclude_complaint_id: str | None = None,
    now: datetime | None = None,
) -> AssetHistorySnapshot:
    """Summarise an asset's history at a point in time.

    exclude_complaint_id removes the report currently being triaged, so a new
    complaint does not count itself as prior history.
    """
    moment = now or utcnow()

    scope = [Complaint.asset_id == asset_id]
    if exclude_complaint_id is not None:
        scope.append(Complaint.id != exclude_complaint_id)

    totals = (
        await session.execute(
            select(
                func.count(Complaint.id),
                func.coalesce(func.sum(Complaint.reopen_count), 0),
            ).where(*scope)
        )
    ).one()
    prior_complaints, reopen_count = int(totals[0]), int(totals[1])

    prior_closures = int(
        (
            await session.execute(
                select(func.count(Complaint.id)).where(
                    *scope, Complaint.status == Status.RESOLVED.value
                )
            )
        ).scalar_one()
    )

    failed_attempts = int(
        (
            await session.execute(
                select(func.count(ClosureAttempt.id)).where(
                    ClosureAttempt.asset_id == asset_id,
                    ClosureAttempt.chain_sufficient.is_(False),
                )
            )
        ).scalar_one()
    )

    earliest_open = (
        await session.execute(
            select(func.min(Complaint.created_at)).where(
                *scope, Complaint.status != Status.RESOLVED.value
            )
        )
    ).scalar_one_or_none()

    open_age_days = 0.0
    if earliest_open is not None:
        open_age_days = max(0.0, (moment - earliest_open).total_seconds() / 86_400.0)

    last_accepted = (
        await session.execute(
            select(func.max(Decision.created_at))
            .join(ClosureAttempt, ClosureAttempt.id == Decision.attempt_id)
            .where(
                ClosureAttempt.asset_id == asset_id,
                Decision.decision == DecisionType.ACCEPT.value,
            )
        )
    ).scalar_one_or_none()

    days_since_repair: float | None = None
    if last_accepted is not None:
        days_since_repair = max(0.0, (moment - last_accepted).total_seconds() / 86_400.0)

    return AssetHistorySnapshot(
        asset_id=asset_id,
        prior_complaints=prior_complaints,
        prior_closures=prior_closures,
        reopen_count=reopen_count,
        failed_closure_attempts=failed_attempts,
        open_age_days=round(open_age_days, 4),
        days_since_verified_repair=days_since_repair,
    )
