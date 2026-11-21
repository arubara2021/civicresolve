"""Checkpoint 10. A status change reaches a subscribed client, survives a
reconnect, and can never be lost by a rollback of the state change.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import EventType
from app.domain.models import Asset, Notification
from app.modules.notify.channels.base import DeliveryResult
from app.modules.notify.channels.in_app import list_notifications, mark_read, unread_count
from app.modules.notify.outbox import write_notification
from app.modules.notify.service import (
    DELIVERED,
    FAILED,
    PENDING,
    RETRYING,
    dispatch_pending,
)
from app.modules.notify.sse import get_broker, replay_after, sequence_of

RECIPIENT = "CIT-201"


class _BrokenChannel:
    name = "broken"

    async def deliver(self, notification: Notification) -> DeliveryResult:
        return DeliveryResult(channel=self.name, delivered=False, detail="transport down")


async def _notify(session: AsyncSession, title: str) -> Notification:
    row = await write_notification(
        session,
        recipient_id=RECIPIENT,
        recipient_type="citizen",
        event_type=EventType.FORENSIC_REPORT_ISSUED.value,
        title=title,
        body="Evidence submitted.",
        complaint_id="WRD-1071",
        asset_id="AST-0042",
    )
    await session.commit()
    return row


async def test_outbox_row_starts_pending(session: AsyncSession, asset: Asset) -> None:
    row = await _notify(session, "Closure submitted")
    assert row.delivery_status == PENDING
    assert row.dispatch_attempts == 0
    assert row.read_at is None


async def test_dispatch_marks_delivered_and_is_idempotent(
    session: AsyncSession, asset: Asset
) -> None:
    await _notify(session, "Closure submitted")
    first = await dispatch_pending(session)
    await session.commit()
    second = await dispatch_pending(session)

    assert first.delivered == 1
    assert second.scanned == 0
    row = (await session.execute(select(Notification))).scalars().one()
    assert row.delivery_status == DELIVERED
    assert row.dispatched_at is not None


async def test_dispatch_reaches_a_live_subscriber(session: AsyncSession, asset: Asset) -> None:
    await _notify(session, "Closure submitted")
    broker = get_broker()
    async with broker.subscribe(RECIPIENT) as queue:
        assert await broker.subscriber_count(RECIPIENT) == 1
        await dispatch_pending(session)
        await session.commit()
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event["event_type"] == EventType.FORENSIC_REPORT_ISSUED.value
    assert event["title"] == "Closure submitted"
    assert await broker.subscriber_count(RECIPIENT) == 0


async def test_reconnect_replays_only_events_after_the_cursor(
    session: AsyncSession, asset: Asset
) -> None:
    first = await _notify(session, "First")
    await dispatch_pending(session)
    await session.commit()

    cursor = sequence_of(first.id)
    second = await _notify(session, "Second")
    third = await _notify(session, "Third")
    await dispatch_pending(session)
    await session.commit()

    replayed = await replay_after(session, RECIPIENT, cursor)
    assert [row.id for row in replayed] == [second.id, third.id]
    assert await replay_after(session, RECIPIENT, sequence_of(third.id)) == []


async def test_undelivered_rows_are_not_replayed(session: AsyncSession, asset: Asset) -> None:
    row = await _notify(session, "Still pending")
    assert await replay_after(session, RECIPIENT, 0) == []
    assert row.delivery_status == PENDING


async def test_unread_count_and_mark_read(session: AsyncSession, asset: Asset) -> None:
    first = await _notify(session, "One")
    await _notify(session, "Two")
    assert await unread_count(session, RECIPIENT) == 2

    changed = await mark_read(session, recipient_id=RECIPIENT, notification_ids=[first.id])
    await session.commit()
    assert changed == 1
    assert await unread_count(session, RECIPIENT) == 1

    rows, total, unread = await list_notifications(session, RECIPIENT, unread_only=True)
    assert total == 1
    assert unread == 1
    assert rows[0].title == "Two"

    assert await mark_read(session, recipient_id=RECIPIENT) == 1
    await session.commit()
    assert await unread_count(session, RECIPIENT) == 0


async def test_mark_read_is_idempotent(session: AsyncSession, asset: Asset) -> None:
    await _notify(session, "One")
    assert await mark_read(session, recipient_id=RECIPIENT) == 1
    await session.commit()
    assert await mark_read(session, recipient_id=RECIPIENT) == 0


async def test_failing_channel_retries_then_fails(session: AsyncSession, asset: Asset) -> None:
    await _notify(session, "One")
    statuses = []
    for _ in range(5):
        report = await dispatch_pending(session, channels=[_BrokenChannel()])
        await session.commit()
        row = (await session.execute(select(Notification))).scalars().one()
        statuses.append(row.delivery_status)
        assert report.delivered == 0

    assert statuses[:4] == [RETRYING] * 4
    assert statuses[4] == FAILED
    final = await dispatch_pending(session, channels=[_BrokenChannel()])
    assert final.scanned == 0


async def test_recipients_are_isolated(session: AsyncSession, asset: Asset) -> None:
    await _notify(session, "For citizen")
    await write_notification(
        session,
        recipient_id="OFF-117",
        recipient_type="officer",
        event_type=EventType.CITIZEN_REJECTED.value,
        title="For officer",
    )
    await session.commit()
    await dispatch_pending(session)
    await session.commit()

    _, citizen_total, _ = await list_notifications(session, RECIPIENT)
    _, officer_total, _ = await list_notifications(session, "OFF-117")
    assert citizen_total == 1
    assert officer_total == 1
    assert await replay_after(session, "OFF-117", 0) != await replay_after(session, RECIPIENT, 0)


async def test_rollback_leaves_no_notification(session: AsyncSession, asset: Asset) -> None:
    """The outbox row shares the state-change transaction, so it cannot survive alone."""
    await write_notification(
        session,
        recipient_id=RECIPIENT,
        recipient_type="citizen",
        event_type=EventType.COMPLAINT_ASSIGNED.value,
        title="Should vanish",
    )
    await session.rollback()
    rows = (await session.execute(select(Notification))).scalars().all()
    assert rows == []


def test_sequence_of_handles_malformed_ids() -> None:
    assert sequence_of("NTF-000007") == 7
    assert sequence_of("garbage") == 0
    assert sequence_of("WRD-1071") == 0