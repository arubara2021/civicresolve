"""In-app channel: the inbox and the live push.

The notification row already IS the in-app message; the outbox wrote it in the
same transaction as the state change. Delivery therefore means publishing it to
any live SSE stream, not writing a second copy. An offline recipient still has
the row waiting, which is what makes the inbox authoritative and the stream an
optimisation rather than the source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.models import Notification
from app.modules.notify.channels.base import DeliveryResult
from app.modules.notify.sse import get_broker, serialise

log = get_logger(__name__)


class InAppChannel:
    name = "in_app"

    async def deliver(self, notification: Notification) -> DeliveryResult:
        reached = await get_broker().publish(notification.recipient_id, serialise(notification))
        return DeliveryResult(
            channel=self.name,
            delivered=True,
            detail=f"live_streams={reached}",
        )


async def list_notifications(
    session: AsyncSession,
    recipient_id: str,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Notification], int, int]:
    """Return (rows, total, unread_count) for one recipient."""
    filters = [Notification.recipient_id == recipient_id]
    if unread_only:
        filters.append(Notification.read_at.is_(None))

    total = int(
        (await session.execute(select(func.count(Notification.id)).where(*filters))).scalar_one()
    )
    unread = int(
        (
            await session.execute(
                select(func.count(Notification.id)).where(
                    Notification.recipient_id == recipient_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
    )
    stmt = (
        select(Notification)
        .where(*filters)
        .order_by(Notification.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total, unread


async def unread_count(session: AsyncSession, recipient_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count(Notification.id)).where(
                    Notification.recipient_id == recipient_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def mark_read(
    session: AsyncSession,
    *,
    recipient_id: str,
    notification_ids: list[str] | None = None,
) -> int:
    """Mark specific notifications, or the whole inbox, as read. Idempotent."""
    filters = [
        Notification.recipient_id == recipient_id,
        Notification.read_at.is_(None),
    ]
    if notification_ids:
        filters.append(Notification.id.in_(notification_ids))
    statement = update(Notification).where(*filters).values(read_at=datetime.now(UTC))
    result = await session.execute(statement)
    await session.flush()
    return int(result.rowcount or 0)