"""Application factory and operational endpoints.

Configuration, logging, error handling, and cross-cutting middleware are wired here.
Process resources are owned by app.core.lifespan, which is imported rather than
redefined: a local definition would silently shadow it and skip schema creation.

Run from the backend directory:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from time import monotonic
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from app.core.security import IdempotencyMiddleware, RateLimitMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import ping as db_ping
from app.core.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    QuotaExceededError,
    RateLimitedError,
    UpstreamUnavailableError,
    register_error_handlers,
)
from app.core.lifespan import lifespan
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    SecurityHeadersMiddleware,
    SelectiveGZipMiddleware,
    TraceContextMiddleware,
)

VERSION = "0.1.0"

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully configured application instance."""
    resolved = settings or get_settings()
    configure_logging(resolved)

    app = FastAPI(
        title=resolved.app_name,
        version=VERSION,
        summary="AI-assisted civic grievance intake with evidence-verified closure.",
        description=(
            "Gemini classifies and prioritises reports. Deterministic checks and a "
            "bounded visual audit produce a Closure Forensics Report. The citizen "
            "accepts or rejects; the model never decides."
        ),
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
        docs_url=None if resolved.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved.is_production else "/openapi.json",
    )
    app.state.settings = resolved

    # Registration order is inverted relative to execution order. Trace context is
    # added last so it wraps everything, including the error handlers.
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware, api_prefix=resolved.api_prefix)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TraceContextMiddleware)

    if resolved.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Trace-Id", "X-Response-Time-Ms"],
        )

    register_error_handlers(app)
    app.include_router(api_router, prefix=resolved.api_prefix)
    _register_operational_routes(app, resolved)

    return app


def _register_operational_routes(app: FastAPI, settings: Settings) -> None:
    """Attach liveness, readiness, and non-production diagnostic routes."""

    @app.get("/", tags=["operations"], summary="Service identity")
    async def root() -> dict[str, Any]:
        return {
            "service": settings.service_name,
            "name": settings.app_name,
            "version": VERSION,
            "environment": settings.environment.value,
            "docs": None if settings.is_production else "/docs",
        }

    @app.get("/healthz", tags=["operations"], summary="Liveness probe")
    async def healthz() -> dict[str, Any]:
        """Liveness only. Performs no dependency checks, so a degraded upstream
        never causes an orchestrator to kill a healthy process.
        """
        return {
            "status": "ok",
            "version": VERSION,
            "uptime_seconds": round(monotonic() - app.state.started_at, 2),
        }

    @app.get("/readyz", tags=["operations"], summary="Readiness probe")
    async def readyz() -> ORJSONResponse:
        """Report dependency readiness.

        A missing model key is degraded rather than unready outside production, so
        the deterministic paths stay exercisable. Database and scheduler are always
        critical: without them the closure protocol cannot be enforced.
        """
        database_ok = await db_ping()
        scheduler = getattr(app.state, "scheduler", None)
        scheduler_ok = bool(scheduler is not None and scheduler.running)

        checks = {
            "config": "ok",
            "database": "ok" if database_ok else "unreachable",
            "scheduler": "ok" if scheduler_ok else "stopped",
            "gemini": "ok" if settings.has_gemini_key else "missing_key",
        }
        degraded = any(state != "ok" for state in checks.values())
        critical_ok = database_ok and scheduler_ok
        if settings.is_production:
            critical_ok = critical_ok and settings.has_gemini_key

        return ORJSONResponse(
            status_code=200 if critical_ok else 503,
            content={
                "status": "ok" if not degraded else "degraded",
                "ready": critical_ok,
                "checks": checks,
            },
        )

    if settings.is_production:
        return

    # Diagnostic routes exist to verify the error contract during development.
    # They are never mounted in production, independent of the debug flag.
    sample_errors: dict[str, type[AppError]] = {
        "bad_request": BadRequestError,
        "not_found": NotFoundError,
        "forbidden": ForbiddenError,
        "conflict": ConflictError,
        "rate_limited": RateLimitedError,
        "quota": QuotaExceededError,
        "upstream": UpstreamUnavailableError,
    }

    @app.get(
        f"{settings.api_prefix}/_debug/raise",
        tags=["diagnostics"],
        summary="Raise a representative application error",
    )
    async def raise_app_error(
        code: str = Query(default="not_found", description="Key from the sample error set"),
    ) -> dict[str, Any]:
        error_type = sample_errors.get(code)
        if error_type is None:
            raise BadRequestError(
                f"Unknown sample code {code!r}.",
                extra={"available": sorted(sample_errors)},
            )
        raise error_type(
            f"Deliberate {error_type.__name__} raised for contract verification.",
            extra={"requested_code": code},
        )

    @app.get(
        f"{settings.api_prefix}/_debug/boom",
        tags=["diagnostics"],
        summary="Raise an unhandled exception",
    )
    async def raise_unhandled() -> dict[str, Any]:
        raise RuntimeError("Deliberate unhandled exception for contract verification.")

    @app.get(
        f"{settings.api_prefix}/_debug/validate",
        tags=["diagnostics"],
        summary="Exercise the request-validation error path",
    )
    async def validate_query(
        n: int = Query(..., description="Required integer; pass a non-integer to trigger 422"),
    ) -> dict[str, int]:
        return {"n": n}

    @app.get(
        f"{settings.api_prefix}/_debug/config",
        tags=["diagnostics"],
        summary="Echo non-sensitive configuration",
    )
    async def echo_config() -> dict[str, Any]:
        """Confirm the environment contract loaded as intended. Secrets are
        reported as booleans only and are never returned.
        """
        return {
            "environment": settings.environment.value,
            "agent_runtime": settings.agent_runtime.value,
            "triage_model": settings.triage_model,
            "forensics_model": settings.forensics_model,
            "gemini_configured": settings.has_gemini_key,
            "effective_sla_seconds": settings.effective_sla_seconds,
            "geo_tolerance_m": settings.geo_tolerance_m,
            "min_repair_minutes": settings.min_repair_minutes,
            "phash_threshold": settings.phash_threshold,
            "dup_cosine_threshold": settings.dup_cosine_threshold,
            "priority_weights": {
                "urgency": settings.w_urgency,
                "impact": settings.w_impact,
                "history": settings.w_history,
            },
            "upload_path": str(settings.upload_path),
            "max_upload_bytes": settings.max_upload_bytes,
            "cors_origins": settings.cors_origin_list,
            "error_codes": [member.value for member in ErrorCode],
        }


app = create_app()


if __name__ == "__main__":
    import uvicorn

    runtime_settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=runtime_settings.host,
        port=runtime_settings.port,
        reload=not runtime_settings.is_production,
    )
