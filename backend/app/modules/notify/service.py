"""Outbox dispatcher.

The row is written inside the state-change transaction; this loop moves it
forward independently. That split is the guarantee: a status can never change
without a notification existing, and a delivery failure can never roll back a
legitimate state change.

Retries are bounded. A permanently failing row is marked failed and left visible
rather than retried forever, so the inbox still shows it and an operator can see
the delivery problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.domain.models import Notification
from app.modules.notify.channels.base import Channel
from app.modules.notify.channels.in_app import InAppChannel

log = get_logger(__name__)

PENDING = "pending"
RETRYING = "retrying"
DELIVERED = "delivered"
FAILED = "failed"

MAX_DISPATCH_ATTEMPTS = 5
JOB_ID = "outbox_dispatch"


@dataclass(slots=True)
class DispatchReport:
    scanned: int = 0
    delivered: int = 0
    retried: int = 0
    failed: int = 0
    ids: list[str] = field(default_factory=list)


def default_channels() -> list[Channel]:
    """in_app only. Email is intentionally not built."""
    return [InAppChannel()]


async def dispatch_pending(
    session: AsyncSession,
    *,
    limit: int = 100,
    channels: list[Channel] | None = None,
) -> DispatchReport:
    """Deliver every pending row. The caller owns the transaction."""
    active = channels if channels is not None else default_channels()
    report = DispatchReport()

    stmt = (
        select(Notification)
        .where(
            Notification.delivery_status.in_([PENDING, RETRYING]),
            Notification.dispatch_attempts < MAX_DISPATCH_ATTEMPTS,
        )
        .order_by(Notification.created_at)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    report.scanned = len(rows)

    for notification in rows:
        notification.dispatch_attempts += 1
        outcomes = []
        for channel in active:
            try:
                outcomes.append(await channel.deliver(notification))
            except Exception as exc:
                log.warning(
                    "notify.channel_error",
                    channel=getattr(channel, "name", "unknown"),
                    notification_id=notification.id,
                    error=type(exc).__name__,
                )
                outcomes.append(None)

        ok = bool(outcomes) and all(item is not None and item.delivered for item in outcomes)
        if ok:
            notification.delivery_status = DELIVERED
            notification.dispatched_at = datetime.now(UTC)
            report.delivered += 1
            report.ids.append(notification.id)
        elif notification.dispatch_attempts >= MAX_DISPATCH_ATTEMPTS:
            notification.delivery_status = FAILED
            report.failed += 1
            log.error("notify.delivery_failed", notification_id=notification.id)
        else:
            notification.delivery_status = RETRYING
            report.retried += 1

    await session.flush()
    if report.scanned:
        log.info(
            "notify.dispatched",
            scanned=report.scanned,
            delivered=report.delivered,
            retried=report.retried,
            failed=report.failed,
        )
    return report


async def _tick() -> None:
    """One dispatcher tick. Never raises, so one bad row cannot kill the job."""
    try:
        async with session_scope() as session:
            await dispatch_pending(session)
    except Exception:
        log.exception("notify.dispatch_failed")


def register_outbox_job(scheduler: AsyncIOScheduler, settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    scheduler.add_job(
        _tick,
        trigger="interval",
        seconds=max(0.25, resolved.outbox_poll_s),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("notify.job_registered", interval_s=resolved.outbox_poll_s)