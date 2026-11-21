"""Structured logging with request-scoped context.

Two properties matter for this system. First, every log line emitted while
handling a request carries the same trace identifier, so a single forensic run can
be reconstructed from logs alone. Second, uvicorn's own loggers are routed through
the same formatter, so application and server output share one schema.

The trace identifier is held in a ContextVar and mirrored into structlog's
contextvars, which propagates correctly across awaited coroutines.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import Settings
from app.core.ids import new_trace_id

_trace_id_var: ContextVar[str | None] = ContextVar("civicresolve_trace_id", default=None)
_configured = False


def get_trace_id() -> str | None:
    """Return the trace identifier bound to the current execution context."""
    return _trace_id_var.get()


def bind_trace_id(trace_id: str) -> None:
    """Bind a trace identifier so all subsequent log lines inherit it."""
    _trace_id_var.set(trace_id)
    structlog.contextvars.bind_contextvars(trace_id=trace_id)


def bind_context(**values: Any) -> None:
    """Attach additional request-scoped fields, such as actor_id or complaint_id."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    """Reset request-scoped state. Must run at the end of every request."""
    _trace_id_var.set(None)
    structlog.contextvars.clear_contextvars()


def _static_fields_processor(static: dict[str, Any]):
    """Inject deployment identity into every event without per-call binding."""

    def processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        for key, value in static.items():
            event_dict.setdefault(key, value)
        return event_dict

    return processor


def configure_logging(settings: Settings) -> None:
    """Install the logging pipeline. Safe to call more than once."""
    global _configured

    level = getattr(logging, settings.log_level, logging.INFO)
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _static_fields_processor(
            {"service": settings.service_name, "environment": settings.environment.value}
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers at startup. Removing them and enabling
    # propagation makes server logs pass through the formatter above instead of
    # emitting a second, incompatible format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        server_logger = logging.getLogger(name)
        server_logger.handlers = []
        server_logger.propagate = True
        server_logger.setLevel(level)

    # Third-party chatter that carries no diagnostic value at INFO.
    for noisy in ("aiosqlite", "PIL", "httpx", "httpcore", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Falls back to a safe default if setup was skipped."""
    if not _configured:
        logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    return structlog.get_logger(name if name else "civicresolve")


def ensure_trace_id() -> str:
    """Return the current trace identifier, generating one for non-request contexts."""
    existing = get_trace_id()
    if existing:
        return existing
    generated = new_trace_id()
    bind_trace_id(generated)
    return generated
