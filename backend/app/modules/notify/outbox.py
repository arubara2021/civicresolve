"""Transactional outbox for notifications.

The notification row is written in the same transaction as the state change it
describes, so a status can never change without a corresponding notification
existing. The dispatcher (Phase 10) then moves delivery_status forward
independently. This module only writes; it does not dispatch.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import IdPrefix
from app.core.sequences import allocate_id
from app.domain.models import Notification


async def write_notification(
    session: AsyncSession,
    *,
    recipient_id: str,
    recipient_type: str,
    event_type: str,
    title: str,
    body: str = "",
    complaint_id: str | None = None,
    asset_id: str | None = None,
    payload: dict[str, Any] | None = None,
    channel: str = "in_app",
) -> Notification:
    """Write a notification row. The caller owns the transaction."""
    record = Notification(
        id=await allocate_id(session, IdPrefix.NOTIFICATION),
        recipient_id=recipient_id,
        recipient_type=recipient_type,
        complaint_id=complaint_id,
        asset_id=asset_id,
        event_type=event_type,
        title=title,
        body=body,
        payload=payload or {},
        channel=channel,
        delivery_status="pending",
    )
    session.add(record)
    await session.flush()
    return record
