"""Process lifecycle ownership.

Startup order matters: the schema must exist before the seeder runs, and the
scheduler must start inside the running event loop before jobs are registered.
Shutdown reverses it, stopping the scheduler before the engine is disposed so no
job observes a closed pool.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import monotonic

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.core.config import Settings
from app.core.db import dispose_db, init_db, session_scope
from app.core.logging import get_logger
from app.modules.notify.service import register_outbox_job
from app.modules.review.sla import register_sla_job

log = get_logger(__name__)


async def _seed_if_available(settings: Settings) -> str:
    if not settings.seed_on_startup:
        return "disabled"
    try:
        from scripts.seed import seed_if_empty
    except ImportError:
        return "not_implemented"
    try:
        async with session_scope() as session:
            created = await seed_if_empty(session)
        return "seeded" if created else "already_populated"
    except Exception:
        log.exception("app.seed_failed")
        return "failed"


def _build_scheduler(settings: Settings) -> AsyncIOScheduler:
    return AsyncIOScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    app.state.started_at = monotonic()
    settings.upload_path.mkdir(parents=True, exist_ok=True)

    await init_db()
    seed_status = await _seed_if_available(settings)

    scheduler = _build_scheduler(settings)
    scheduler.start()
    register_sla_job(scheduler, settings)
    register_outbox_job(scheduler, settings)
    app.state.scheduler = scheduler

    log.info(
        "app.startup",
        environment=settings.environment.value,
        agent_runtime=settings.agent_runtime.value,
        gemini_configured=settings.has_gemini_key,
        sla_seconds=settings.effective_sla_seconds,
        seed_status=seed_status,
        scheduler_running=scheduler.running,
        jobs=[job.id for job in scheduler.get_jobs()],
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await dispose_db()
        log.info("app.shutdown", uptime_s=round(monotonic() - app.state.started_at, 2))