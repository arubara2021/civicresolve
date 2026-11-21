"""Durable identifier allocation.

core.ids remains pure formatting. This module owns the counter state, using a
single atomic upsert so concurrent allocations cannot produce duplicates. The
statement is SQLite-specific; a Postgres deployment swaps the dialect import and
keeps the identical interface.
"""

from __future__ import annotations

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import IdPrefix, format_id
from app.domain.models import IdSequence


async def allocate_id(session: AsyncSession, prefix: IdPrefix) -> str:
    """Atomically advance a counter and return the next formatted identifier.

    The caller owns the transaction. If it rolls back, the counter stays advanced,
    which leaves a gap but never a collision.
    """
    statement = (
        sqlite_insert(IdSequence)
        .values(name=prefix.value, value=1)
        .on_conflict_do_update(
            index_elements=[IdSequence.name],
            set_={"value": IdSequence.value + 1},
        )
        .returning(IdSequence.value)
    )
    result = await session.execute(statement)
    return format_id(prefix, result.scalar_one())


async def sync_sequence(session: AsyncSession, prefix: IdPrefix, value: int) -> None:
    """Set a counter so the next allocation is value + 1.

    Used by the seeder to reproduce the identifiers in the demo fixture, and by a
    restore operation to resume above an existing maximum.
    """
    if value < 0:
        raise ValueError("sequence value must be non-negative")
    statement = (
        sqlite_insert(IdSequence)
        .values(name=prefix.value, value=value)
        .on_conflict_do_update(
            index_elements=[IdSequence.name],
            set_={"value": value},
        )
    )
    await session.execute(statement)
