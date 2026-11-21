"""Async persistence infrastructure.

SQLite runs in WAL mode so readers never block the writer, with a busy timeout so
a concurrent write waits instead of failing. Foreign keys are enforced, which
SQLite disables by default and which the append-only design relies on.

Sessions do not auto-commit. Services own their transaction boundaries explicitly,
because the notification outbox must be written inside the same transaction as the
state change it describes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.models import Base

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Configure every new SQLite connection.

    The listener attaches to the synchronous engine facade. It runs inside the
    greenlet context SQLAlchemy establishes for the async driver, so the cursor
    calls below are valid even though the driver is aiosqlite.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def get_engine() -> AsyncEngine:
    """Return the process engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            future=True,
        )
        if _engine.dialect.name == "sqlite":
            _apply_sqlite_pragmas(_engine)
        log.info("db.engine_created", dialect=_engine.dialect.name)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the session factory bound to the process engine."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def init_db() -> None:
    """Create any missing tables. Idempotent and safe on every boot."""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    log.info("db.schema_ready", tables=len(Base.metadata.tables))


async def dispose_db() -> None:
    """Close all pooled connections during shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        log.info("db.engine_disposed")
    _engine = None
    _sessionmaker = None


async def ping() -> bool:
    """Cheap readiness check. Returns False rather than raising."""
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        log.warning("db.ping_failed", exc_info=True)
        return False
    return True


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Rolls back on failure and always closes.

    Committing is the service's responsibility, so a request handler can compose
    several writes into one atomic unit.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for scripts and scheduled jobs."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
