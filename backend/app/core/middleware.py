"""Cross-cutting HTTP concerns implemented as pure ASGI middleware.

BaseHTTPMiddleware is deliberately avoided. It wraps the downstream application in
a way that interferes with long-lived streaming responses, and this service exposes
a Server-Sent Events channel. Pure ASGI middleware passes the send callable through
untouched, so streaming is unaffected.

Middleware ordering is set in the application factory: the last middleware added is
the outermost, which is why trace context is registered last.
"""

from __future__ import annotations

from time import perf_counter
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.ids import new_trace_id, normalise_inbound_trace_id, trace_id_from_traceparent
from app.core.logging import bind_trace_id, clear_context, get_logger

log = get_logger(__name__)

TRACE_HEADER: Final = "X-Trace-Id"
TIMING_HEADER: Final = "X-Response-Time-Ms"


class TraceContextMiddleware:
    """Establish a trace identifier, time the request, and log its completion.

    The timing header reports time to first response byte, which is what a client
    perceives as latency. The completion log reports total wall time including the
    response body, which is what matters for capacity.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        excluded_paths: tuple[str, ...] = ("/healthz", "/readyz"),
    ) -> None:
        self.app = app
        self.excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope)
        trace_id = (
            trace_id_from_traceparent(inbound.get("traceparent"))
            or normalise_inbound_trace_id(inbound.get(TRACE_HEADER.lower()))
            or normalise_inbound_trace_id(inbound.get("x-request-id"))
            or new_trace_id()
        )

        clear_context()
        bind_trace_id(trace_id)

        started = perf_counter()
        status_code = 500
        path = scope.get("path", "")
        method = scope.get("method", "")

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[TRACE_HEADER] = trace_id
                headers[TIMING_HEADER] = f"{(perf_counter() - started) * 1000:.2f}"
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            if path not in self.excluded_paths:
                log.info(
                    "http.request",
                    method=method,
                    path=path,
                    status=status_code,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                )
            clear_context()


class SecurityHeadersMiddleware:
    """Apply conservative response headers and disable caching of API payloads."""

    def __init__(self, app: ASGIApp, *, api_prefix: str = "/api") -> None:
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                if path.startswith(self.api_prefix):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class SelectiveGZipMiddleware:
    """Compress ordinary responses while leaving event streams uncompressed.

    Compressing a Server-Sent Events channel introduces buffering that delays or
    withhelds individual events, which defeats the purpose of the channel.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = 1024,
        streaming_paths: tuple[str, ...] = ("/api/stream",),
    ) -> None:
        self.app = app
        self.streaming_paths = streaming_paths
        self._gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if any(path.startswith(prefix) for prefix in self.streaming_paths):
            await self.app(scope, receive, send)
            return
        await self._gzip(scope, receive, send)


def install_middleware(app: ASGIApp) -> None:
    """Placeholder retained for symmetry; ordering is applied in the factory.

    Starlette resolves middleware order at stack build time, so registration must
    happen on the FastAPI instance rather than through a helper that receives an
    already-wrapped ASGI application.
    """
    raise NotImplementedError("Register middleware in app.main.create_app instead.")


def current_api_prefix() -> str:
    """Read the API prefix without importing the application instance."""
    return get_settings().api_prefix
