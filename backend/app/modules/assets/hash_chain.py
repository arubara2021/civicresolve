"""The tamper-evident passport log.

Each event hash binds the previous hash together with the full event envelope:
asset, sequence number, type, actor, timestamp and payload. Binding the envelope
rather than only the payload means reordering events, relabelling an actor, or
backdating a timestamp also breaks the chain, not just editing the payload.

The preimage is canonical JSON: sorted keys, no incidental whitespace, stable
datetime and enum rendering. Without canonicalisation, two semantically identical
payloads could hash differently and verification would report false tampering.

This module exposes append, read and verify. It contains no update or delete path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import IdPrefix
from app.core.logging import get_logger
from app.core.sequences import allocate_id
from app.domain.enums import ActorType, EventType
from app.domain.models import Asset, Event, utcnow

log = get_logger(__name__)

GENESIS_HASH = "0" * 64
TIMESTAMP_SPEC = "microseconds"


class AssetMissingError(ValueError):
    """An append was attempted against an asset that does not exist."""


class ChainVerification(BaseModel):
    """Result of recomputing an asset's chain from its events."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    valid: bool
    events_checked: int = Field(ge=0)
    broken_seq: int | None = None
    reason: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    head_matches: bool = True
    verified_at: datetime


def _json_default(value: Any) -> Any:
    """Render types JSON does not natively support, deterministically."""
    if isinstance(value, datetime):
        return _render_timestamp(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, set | frozenset):
        return sorted(value)
    raise TypeError(f"unsupported type in canonical payload: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialise deterministically. Key insertion order must not affect the hash."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def _render_timestamp(moment: datetime) -> str:
    """Normalise to aware UTC with fixed precision before hashing or storing."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec=TIMESTAMP_SPEC)


def event_preimage(
    *,
    asset_id: str,
    seq: int,
    event_type: EventType | str,
    actor_type: ActorType | str,
    actor_id: str | None,
    occurred_at: datetime,
    payload: Mapping[str, Any],
    prev_hash: str,
) -> dict[str, Any]:
    """Assemble the exact structure that gets hashed. Shared by append and verify."""
    return {
        "prev_hash": prev_hash,
        "asset_id": asset_id,
        "seq": seq,
        "event_type": EventType(event_type).value,
        "actor_type": ActorType(actor_type).value,
        "actor_id": actor_id,
        "occurred_at": _render_timestamp(occurred_at),
        "payload": dict(payload),
    }


def compute_event_hash(preimage: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical preimage."""
    return hashlib.sha256(canonical_json(preimage).encode("utf-8")).hexdigest()


_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _asset_lock(asset_id: str) -> asyncio.Lock:
    """Serialise appends per asset within this process.

    The unique constraint on (asset_id, seq) is the real correctness guarantee.
    This lock only avoids contending for it under normal operation.
    """
    async with _locks_guard:
        lock = _locks.get(asset_id)
        if lock is None:
            lock = asyncio.Lock()
            _locks[asset_id] = lock
        return lock


async def append_event(
    session: AsyncSession,
    *,
    asset_id: str,
    event_type: EventType,
    actor_type: ActorType,
    actor_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> Event:
    """Append one event and advance the asset's chain tip.

    The caller owns the transaction, so an event and the state change it describes
    commit together or not at all. Nothing is committed here.
    """
    lock = await _asset_lock(asset_id)
    async with lock:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            raise AssetMissingError(f"asset {asset_id!r} does not exist")

        seq = asset.last_event_seq + 1
        prev_hash = asset.chain_head_hash or GENESIS_HASH
        moment = occurred_at or utcnow()
        body = dict(payload or {})

        preimage = event_preimage(
            asset_id=asset_id,
            seq=seq,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            occurred_at=moment,
            payload=body,
            prev_hash=prev_hash,
        )
        digest = compute_event_hash(preimage)

        record = Event(
            id=await allocate_id(session, IdPrefix.EVENT),
            asset_id=asset_id,
            seq=seq,
            event_type=event_type.value,
            actor_type=actor_type.value,
            actor_id=actor_id,
            payload=body,
            occurred_at=moment,
            prev_hash=prev_hash,
            event_hash=digest,
        )
        session.add(record)

        asset.last_event_seq = seq
        asset.chain_head_hash = digest

        await session.flush()
        log.debug("passport.appended", asset_id=asset_id, seq=seq, event_type=event_type.value)
        return record


async def read_events(session: AsyncSession, asset_id: str, *, after_seq: int = 0) -> list[Event]:
    """Read an asset's events in sequence order."""
    statement = (
        select(Event).where(Event.asset_id == asset_id, Event.seq > after_seq).order_by(Event.seq)
    )
    return list((await session.execute(statement)).scalars().all())


async def verify_chain(session: AsyncSession, asset_id: str) -> ChainVerification:
    """Recompute the chain and report the first divergence.

    Checks, in order: sequence contiguity from one, previous-hash linkage, and the
    event hash recomputed from stored fields. Finally the cached asset tip is
    compared against the recomputed tip.
    """
    verified_at = utcnow()
    asset = await session.get(Asset, asset_id)
    if asset is None:
        return ChainVerification(
            asset_id=asset_id,
            valid=False,
            events_checked=0,
            reason="asset_not_found",
            head_matches=False,
            verified_at=verified_at,
        )

    events = await read_events(session, asset_id)
    prev_hash = GENESIS_HASH
    expected_seq = 1

    for record in events:
        if record.seq != expected_seq:
            return ChainVerification(
                asset_id=asset_id,
                valid=False,
                events_checked=expected_seq - 1,
                broken_seq=expected_seq,
                reason="sequence_gap",
                head_matches=False,
                verified_at=verified_at,
            )

        if record.prev_hash != prev_hash:
            return ChainVerification(
                asset_id=asset_id,
                valid=False,
                events_checked=expected_seq - 1,
                broken_seq=record.seq,
                reason="prev_hash_mismatch",
                expected_hash=prev_hash,
                actual_hash=record.prev_hash,
                head_matches=False,
                verified_at=verified_at,
            )

        recomputed = compute_event_hash(
            event_preimage(
                asset_id=record.asset_id,
                seq=record.seq,
                event_type=record.event_type,
                actor_type=record.actor_type,
                actor_id=record.actor_id,
                occurred_at=record.occurred_at,
                payload=record.payload,
                prev_hash=record.prev_hash,
            )
        )
        if recomputed != record.event_hash:
            return ChainVerification(
                asset_id=asset_id,
                valid=False,
                events_checked=expected_seq - 1,
                broken_seq=record.seq,
                reason="event_content_modified",
                expected_hash=recomputed,
                actual_hash=record.event_hash,
                head_matches=False,
                verified_at=verified_at,
            )

        prev_hash = record.event_hash
        expected_seq += 1

    head_matches = asset.chain_head_hash == prev_hash if events else asset.chain_head_hash is None
    if not head_matches:
        return ChainVerification(
            asset_id=asset_id,
            valid=False,
            events_checked=len(events),
            broken_seq=len(events) or None,
            reason="head_pointer_mismatch",
            expected_hash=prev_hash if events else None,
            actual_hash=asset.chain_head_hash,
            head_matches=False,
            verified_at=verified_at,
        )

    return ChainVerification(
        asset_id=asset_id,
        valid=True,
        events_checked=len(events),
        head_matches=True,
        verified_at=verified_at,
    )
