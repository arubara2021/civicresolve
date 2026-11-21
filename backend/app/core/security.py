"""Request hardening for a public deployment.

Three concerns, all pure ASGI so long-lived SSE streams pass through untouched.

Per-IP token bucket. A public repo plus a public URL is an abuse target, and every
intake call spends paid model quota. The bucket allows a burst then refills at the
configured sustained rate.

Idempotency replay. A client that retries a POST after a network blip must not
create a second complaint. A keyed request's first response is cached and replayed
verbatim, including its status code.

MIME allowlist. Enforced against the format the server actually decoded, never
the client's declared Content-Type, which is trivially forged.

State is in-process. A multi-worker deployment would move both stores to Redis
behind the same interfaces; no call site changes.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

import orjson
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings, get_settings
from app.core.errors import PROBLEM_TYPE_BASE, UnsupportedMediaTypeError
from app.core.logging import ensure_trace_id, get_logger

log = get_logger(__name__)

EXEMPT_PATHS = ("/healthz", "/readyz", "/docs", "/openapi.json", "/api/stream")
_CACHED_METHODS = frozenset({"POST", "PATCH", "PUT"})
_MAX_BUCKETS = 10_000
_MAX_CACHED = 2_000


def client_ip(scope: Scope) -> str:
    """Best-effort client address.

    X-Forwarded-For is honoured only as the left-most entry, which is what a
    single trusted proxy sets. Behind an untrusted proxy this is spoofable, so
    the limiter is a cost control, not an authentication boundary.
    """
    headers = Headers(scope=scope)
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    """Refill at per_min/60, capacity burst. One bucket per client key."""

    def __init__(self, per_min: int, burst: int) -> None:
        self._rate = per_min / 60.0
        self._capacity = float(burst)
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, updated=now)
            self._buckets[key] = bucket
            if len(self._buckets) > _MAX_BUCKETS:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(key)

        bucket.tokens = min(self._capacity, bucket.tokens + (now - bucket.updated) * self._rate)
        bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0
        return False, max(1, int((1.0 - bucket.tokens) / self._rate) + 1)

    def reset(self) -> None:
        self._buckets.clear()


@dataclass(slots=True)
class _CachedResponse:
    status: int
    headers: list[tuple[bytes, bytes]]
    body: bytes
    stored_at: float = field(default_factory=time.monotonic)


class IdempotencyStore:
    """TTL cache of keyed responses. Bounded so a flood cannot exhaust memory."""

    def __init__(self, ttl_s: int) -> None:
        self._ttl = float(ttl_s)
        self._entries: OrderedDict[str, _CachedResponse] = OrderedDict()

    def get(self, key: str) -> _CachedResponse | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.stored_at > self._ttl:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return entry

    def put(self, key: str, response: _CachedResponse) -> None:
        self._entries[key] = response
        self._entries.move_to_end(key)
        while len(self._entries) > _MAX_CACHED:
            self._entries.popitem(last=False)

    def reset(self) -> None:
        self._entries.clear()


_limiter: TokenBucketLimiter | None = None
_store: IdempotencyStore | None = None


def get_limiter(settings: Settings | None = None) -> TokenBucketLimiter:
    global _limiter
    if _limiter is None:
        resolved = settings or get_settings()
        _limiter = TokenBucketLimiter(resolved.rate_limit_per_min, resolved.rate_limit_burst)
    return _limiter


def get_idempotency_store(settings: Settings | None = None) -> IdempotencyStore:
    global _store
    if _store is None:
        resolved = settings or get_settings()
        _store = IdempotencyStore(resolved.idempotency_ttl_s)
    return _store


def reset_security_state() -> None:
    """Drop both stores and force a rebuild from configuration.

    Clearing buckets alone is not enough: a test that mutates capacity would
    leak that mutation into every later test in the process. Discarding the
    singletons makes each reset a genuine fresh start.
    """
    global _limiter, _store
    if _limiter is not None:
        _limiter.reset()
    if _store is not None:
        _store.reset()
    _limiter = None
    _store = None


def ensure_allowed_mime(mime_type: str) -> None:
    """Reject a decoded format outside the configured allowlist.

    Called with the format the server actually sniffed from the bytes, so a
    forged Content-Type header cannot smuggle an unsupported file past it.
    """
    allowed = get_settings().allowed_mime_types
    if mime_type.lower() not in allowed:
        raise UnsupportedMediaTypeError(
            f"File type {mime_type!r} is not accepted. Allowed: {', '.join(sorted(allowed))}."
        )


async def _send_problem(
    send: Send, *, status: int, code: str, title: str, detail: str, retry_after_s: int
) -> None:
    """Emit an RFC 9457 document directly.

    Middleware sits outside the exception handlers, so raising AppError here
    would escape the envelope. The problem shape is built explicitly instead.
    """
    trace_id = ensure_trace_id()
    payload = {
        "type": f"{PROBLEM_TYPE_BASE}/{code.lower().replace('_', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "trace_id": trace_id,
        "retryable": True,
    }
    body = orjson.dumps(payload)
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", str(retry_after_s).encode()),
                (b"x-trace-id", trace_id.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """Per-IP token bucket. Health probes and the SSE channel are exempt."""

    def __init__(self, app: ASGIApp, *, exempt: tuple[str, ...] = EXEMPT_PATHS) -> None:
        self.app = app
        self.exempt = exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in self.exempt):
            await self.app(scope, receive, send)
            return

        allowed, retry_after = get_limiter().allow(client_ip(scope))
        if not allowed:
            log.warning("security.rate_limited", path=path, ip=client_ip(scope))
            await _send_problem(
                send,
                status=429,
                code="RATE_LIMITED",
                title="Too many requests",
                detail="Request rate exceeded for this client. Retry after the indicated delay.",
                retry_after_s=retry_after,
            )
            return
        await self.app(scope, receive, send)


class IdempotencyMiddleware:
    """Replay a keyed mutating request instead of executing it twice."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _CACHED_METHODS:
            await self.app(scope, receive, send)
            return

        key = Headers(scope=scope).get("idempotency-key")
        if not key:
            await self.app(scope, receive, send)
            return

        store = get_idempotency_store()
        cache_key = f"{scope['method']}:{scope.get('path', '')}:{key}"
        cached = store.get(cache_key)
        if cached is not None:
            log.info("security.idempotent_replay", path=scope.get("path"), key=key[:16])
            headers = [
                (name, value)
                for name, value in cached.headers
                if name.lower() not in {b"content-length", b"idempotency-replayed"}
            ]
            headers.append((b"content-length", str(len(cached.body)).encode()))
            headers.append((b"idempotency-replayed", b"true"))
            await send(
                {"type": "http.response.start", "status": cached.status, "headers": headers}
            )
            await send({"type": "http.response.body", "body": cached.body})
            return

        captured: dict[str, object] = {}
        chunks: list[bytes] = []

        async def send_and_capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, send_and_capture)

        status = int(captured.get("status", 500))
        # A 5xx is not a durable outcome. Caching it would pin a transient
        # failure to the key for the whole TTL and block a legitimate retry.
        if status < 500:
            store.put(
                cache_key,
                _CachedResponse(
                    status=status,
                    headers=captured.get("headers", []),
                    body=b"".join(chunks),
                ),
            )