"""Notification HTTP surface.

GET  /api/notifications                 inbox for one recipient
GET  /api/notifications/unread-count    badge number
POST /api/notifications/read            mark one, many, or all as read
GET  /api/stream                        per-actor SSE, auto-reconnect with replay

recipient_id is a query parameter because this prototype has no auth. It must be
bound to an authenticated actor before public deployment.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import get_session
from app.modules.notify.channels.in_app import list_notifications, mark_read, unread_count
from app.modules.notify.sse import serialise, stream_response

router = APIRouter(tags=["notifications"])


class MarkReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipient_id: str = Field(min_length=3, max_length=64)
    notification_ids: list[str] | None = None


@router.get("/notifications", summary="List a recipient's notifications")
async def get_notifications(
    recipient_id: str = Query(..., min_length=3, max_length=64),
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    rows, total, unread = await list_notifications(
        session, recipient_id, unread_only=unread_only, limit=limit, offset=offset
    )
    return ORJSONResponse(
        content={
            "total": total,
            "unread": unread,
            "returned": len(rows),
            "items": [serialise(row) for row in rows],
        }
    )


@router.get("/notifications/unread-count", summary="Unread badge count")
async def get_unread_count(
    recipient_id: str = Query(..., min_length=3, max_length=64),
    session: AsyncSession = Depends(get_session),
) -> ORJSONResponse:
    return ORJSONResponse(
        content={"recipient_id": recipient_id, "unread": await unread_count(session, recipient_id)}
    )


@router.post("/notifications/read", summary="Mark notifications as read")
async def read_notifications(
    payload: MarkReadIn, session: AsyncSession = Depends(get_session)
) -> ORJSONResponse:
    changed = await mark_read(
        session, recipient_id=payload.recipient_id, notification_ids=payload.notification_ids
    )
    await session.commit()
    return ORJSONResponse(
        content={
            "marked_read": changed,
            "unread": await unread_count(session, payload.recipient_id),
        }
    )


@router.get("/stream", summary="Per-actor Server-Sent Events stream")
async def stream(
    request: Request,
    recipient_id: str = Query(..., min_length=3, max_length=64),
) -> EventSourceResponse:
    return stream_response(recipient_id, request)