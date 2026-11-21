"""Shared test infrastructure.

Tests run against an in-memory SQLite database held on a single static connection,
so each test gets a private schema with no file cleanup and no cross-test leakage.
The production engine and settings are never touched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.domain.models import Asset, Base


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """A private in-memory database with the full schema applied."""
    instance = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with instance.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session with expiry disabled so instances stay readable after commit."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as instance:
        yield instance


@pytest.fixture
async def asset(session: AsyncSession) -> Asset:
    """The chronic asset from the worked example."""
    record = Asset(
        id="AST-0042",
        asset_type="road_segment",
        ward="WARD-12",
        label="MG Road service lane, left wheel path near school gate",
        lat=28.45950,
        lng=77.02660,
        radius_m=50.0,
        defect_claim="unfilled pothole approx 40cm wide in left wheel path, broken edge",
        evidence_standard=["geo_tagged_closeup_of_repaired_zone", "work_order_reference"],
        min_repair_minutes=120,
    )
    session.add(record)
    await session.commit()
    return record
