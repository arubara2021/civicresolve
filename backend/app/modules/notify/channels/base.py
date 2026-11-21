"""Delivery channel contract.

in_app now, email or push later. The dispatcher depends only on this protocol,
so adding a channel is one file plus one registration line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.domain.models import Notification


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    channel: str
    delivered: bool
    detail: str | None = None


@runtime_checkable
class Channel(Protocol):
    name: str

    async def deliver(self, notification: Notification) -> DeliveryResult: ...