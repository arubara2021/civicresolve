"""Per-actor Server-Sent Events stream.

One-way push, auto-reconnect. The browser's EventSource sends Last-Event-ID on
reconnect, and the stream replays every delivered notification above that cursor
before attaching to the live feed, so a dropped connection loses nothing.

The broker is in-process. A multi-worker deployment would swap it for Redis
pub/sub behind the same two methods; nothing else changes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.ids import IdPrefix, parse_id
from app.core.logging import get_logger
from app.domain.models import Notification

log = get_logger(__name__)

_QUEUE_MAX = 256
DELIVERED = "delivered"


def sequence_of(notification_id: str) -> int:
    """Numeric cursor for a notification ID. Malformed IDs sort to zero."""
    try:
        prefix, value = parse_id(notification_id)
    except ValueError:
        return 0
    return value if prefix is IdPrefix.NOTIFICATION else 0


def serialise(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "event_type": notification.event_type,
        "title": notification.title,
        "body": notification.body,
        "complaint_id": notification.complaint_id,
        "asset_id": notification.asset_id,
        "recipient_id": notification.recipient_id,
        "payload": notification.payload,
        "created_at": notification.created_at.isoformat(),
        "read": notification.read_at is not None,
    }


class NotificationBroker:
    """Fan-out to every live stream owned by one recipient."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, recipient_id: str, event: dict) -> int:
        async with self._lock:
            queues = list(self._subscribers.get(recipient_id, ()))
        reached = 0
        for queue in queues:
            try:
                queue.put_nowait(event)
                reached += 1
            except asyncio.QueueFull:
                # A stalled client must never block the dispatcher. It will
                # recover the missed events from the replay cursor on reconnect.
                log.warning("sse.queue_full", recipient_id=recipient_id)
        return reached

    @asynccontextmanager
    async def subscribe(self, recipient_id: str) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        async with self._lock:
            self._subscribers.setdefault(recipient_id, set()).add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                bucket = self._subscribers.get(recipient_id)
                if bucket is not None:
                    bucket.discard(queue)
                    if not bucket:
                        self._subscribers.pop(recipient_id, None)

    async def subscriber_count(self, recipient_id: str) -> int:
        async with self._lock:
            return len(self._subscribers.get(recipient_id, ()))


_broker = NotificationBroker()


def get_broker() -> NotificationBroker:
    return _broker


async def replay_after(
    session: AsyncSession, recipient_id: str, after_seq: int, *, limit: int = 200
) -> list[Notification]:
    """Delivered notifications newer than the client's cursor, oldest first."""
    stmt = (
        select(Notification)
        .where(
            Notification.recipient_id == recipient_id,
            Notification.delivery_status == DELIVERED,
        )
        .order_by(Notification.id.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    selected = [row for row in rows if sequence_of(row.id) > after_seq]
    selected.sort(key=lambda row: sequence_of(row.id))
    return selected


async def _event_stream(recipient_id: str, request: Request, last_seq: int) -> AsyncIterator[dict]:
    """Attach to the live feed first, then replay the gap. Never holds a DB session."""
    cursor = last_seq
    broker = get_broker()
    heartbeat = get_settings().sse_heartbeat_s

    async with broker.subscribe(recipient_id) as queue:
        async with session_scope() as session:
            backlog = await replay_after(session, recipient_id, cursor)
        for notification in backlog:
            cursor = sequence_of(notification.id)
            yield {
                "id": notification.id,
                "event": notification.event_type,
                "data": json.dumps(serialise(notification)),
            }
        log.info("sse.subscribed", recipient_id=recipient_id, replayed=len(backlog))
        yield {"event": "stream_ready", "data": json.dumps({"recipient_id": recipient_id})}
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except TimeoutError:
                continue
            seq = sequence_of(str(event.get("id", "")))
            if seq and seq <= cursor:
                continue
            cursor = seq or cursor
            yield {
                "id": event.get("id"),
                "event": event.get("event_type", "notification"),
                "data": json.dumps(event),
            }
    log.info("sse.unsubscribed", recipient_id=recipient_id)


def stream_response(recipient_id: str, request: Request) -> EventSourceResponse:
    """Build the SSE response, honouring Last-Event-ID for reconnect replay.

    recipient_id is a query parameter because this prototype has no auth layer.
    Phase 11 must bind it to an authenticated actor before public deployment.
    """
    header = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    last_seq = sequence_of(header) if header else 0
    settings = get_settings()
    return EventSourceResponse(
        _event_stream(recipient_id, request, last_seq),
        ping=settings.sse_heartbeat_s,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )