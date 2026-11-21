"""Resilient Gemini client with timeout, retry, fallback, circuit breaker and quota.

Every model call the application makes goes through one of the two public methods
on GeminiClient. The client owns:

- Hard timeouts so a slow model never stalls a request indefinitely.
- Exponential backoff with jitter on retryable failures (429 and 5xx).
- A simple circuit breaker that opens after consecutive failures, so a sustained
  outage does not keep burning quota or latency budget.
- A rolling daily quota counter so a public deployment cannot be driven to an
  unlimited bill by a misbehaving client.
- A fallback model that is tried once when the primary fails, so triage degrades
  gracefully rather than failing closed.

Configuration-driven timeouts and thresholds mean production hardening does not
require a code change. The client is constructed once at startup and injected
through FastAPI dependencies.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.agents.ports import AgentCallRecord
from app.core.config import Settings, get_settings
from app.core.errors import (
    ConfigurationError,
    QuotaExceededError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from app.core.logging import get_logger

log = get_logger(__name__)

_RETRYABLE_STATUS: Final = frozenset({429, 500, 502, 503, 504})
_DEFAULT_MAX_ATTEMPTS: Final = 3
_DEFAULT_BACKOFF_MIN: Final = 0.5
_DEFAULT_BACKOFF_MAX: Final = 8.0


@dataclass(slots=True)
class _BreakerState:
    """Process-local circuit breaker state.

    This is intentionally in-memory only. A real multi-process deployment would
    back this with Redis; for the prototype and a single-instance deployment the
    in-process state is sufficient.
    """

    consecutive_failures: int = 0
    open_until: float = 0.0
    total_successes: int = 0
    total_failures: int = 0


@dataclass(slots=True)
class _QuotaState:
    """Rolling 24-hour usage counter. Resets when the day rolls over."""

    day: str = ""
    count: int = 0


class GeminiClient:
    """Resilient Gemini client. Construct once at startup and share."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._sdk = self._build_sdk(self._settings)
        self._breaker = _BreakerState()
        self._quota = _QuotaState()
        self._lock = asyncio.Lock()

    @staticmethod
    def _build_sdk(settings: Settings) -> genai.Client:
        """Construct the SDK lazily so tests can inject a stub without a key."""
        if not settings.has_gemini_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is not configured; model calls are unavailable."
            )
        return genai.Client(api_key=settings.gemini_key_value())

    async def _check_breaker(self) -> None:
        async with self._lock:
            if self._breaker.consecutive_failures >= self._settings.breaker_threshold:
                if time.monotonic() < self._breaker.open_until:
                    raise UpstreamUnavailableError(
                        "Model circuit breaker is open; service is degraded.",
                        extra={
                            "failures": self._breaker.consecutive_failures,
                            "threshold": self._settings.breaker_threshold,
                        },
                    )
                self._breaker.consecutive_failures = 0

    async def _record_success(self) -> None:
        async with self._lock:
            self._breaker.consecutive_failures = 0
            self._breaker.total_successes += 1

    async def _record_failure(self) -> None:
        async with self._lock:
            self._breaker.consecutive_failures += 1
            self._breaker.total_failures += 1
            if self._breaker.consecutive_failures >= self._settings.breaker_threshold:
                self._breaker.open_until = time.monotonic() + self._settings.breaker_reset_s
                log.warning(
                    "gemini.breaker_opened",
                    failures=self._breaker.consecutive_failures,
                    reset_s=self._settings.breaker_reset_s,
                )

    def _consume_quota(self) -> None:
        """Advance the rolling daily counter. Raises when the cap is exceeded."""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self._quota.day != day:
            self._quota.day = day
            self._quota.count = 0
        if self._quota.count >= self._settings.gemini_daily_cap:
            raise QuotaExceededError(
                "Daily model-call cap reached; service will resume tomorrow.",
                extra={
                    "daily_cap": self._settings.gemini_daily_cap,
                    "used": self._quota.count,
                },
            )
        self._quota.count += 1

    @property
    def quota_usage(self) -> tuple[int, int]:
        """Return (used, cap) for diagnostics without mutating state."""
        return self._quota.count, self._settings.gemini_daily_cap

    @property
    def breaker_open(self) -> bool:
        """Report whether the breaker is currently tripped."""
        if self._breaker.consecutive_failures < self._settings.breaker_threshold:
            return False
        return time.monotonic() < self._breaker.open_until

    async def _one_call(
        self,
        model: str,
        contents: Sequence[Any],
        config: types.GenerateContentConfig,
        timeout_s: float,
    ) -> types.GenerateContentResponse:
        """A single model call with a hard timeout and retryable-error detection."""

        async def _invoke() -> types.GenerateContentResponse:
            return await self._sdk.aio.models.generate_content(
                model=model, contents=list(contents), config=config
            )
        last_error: Exception | None = None
        delay = _DEFAULT_BACKOFF_MIN
        attempts = 0
        max_attempts = max(1, self._settings.gemini_max_retries)
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            started = time.monotonic()
            try:
                return await asyncio.wait_for(_invoke(), timeout=timeout_s)
            except TimeoutError as exc:
                last_error = exc
                log.warning(
                    "gemini.timeout",
                    model=model,
                    attempt=attempt,
                    timeout_s=timeout_s,
                    elapsed_s=round(time.monotonic() - started, 3),
                )
            except genai_errors.APIError as exc:
                status = getattr(exc, "code", None)
                if status not in _RETRYABLE_STATUS or attempt == max_attempts:
                    raise
                last_error = exc
                log.warning(
                    "gemini.retryable",
                    model=model,
                    attempt=attempt,
                    status=status,
                    backoff_s=round(delay, 3),
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, _DEFAULT_BACKOFF_MAX)
            except Exception as exc:
                # Unexpected exception — surface immediately; do not mask it.
                last_error = exc
                log.exception("gemini.unexpected", model=model, attempt=attempt)
                raise

        if isinstance(last_error, asyncio.TimeoutError):
            raise UpstreamTimeoutError(
                f"Model {model!r} did not respond within {timeout_s} seconds."
            )
        raise UpstreamUnavailableError(f"Model {model!r} failed after {attempts} attempts.")

    async def call_with_fallback(
        self,
        *,
        primary_model: str,
        fallback_model: str,
        contents: Sequence[Any],
        config: types.GenerateContentConfig,
        timeout_s: float,
    ) -> tuple[types.GenerateContentResponse, AgentCallRecord]:
        """Primary-then-fallback invocation with breaker and quota bookkeeping."""
        await self._check_breaker()
        self._consume_quota()
        fallback_used = False
        total_attempts = 0
        started = time.monotonic()

        try:
            response = await self._one_call(primary_model, contents, config, timeout_s)
            total_attempts += 1
            model_used = primary_model
        except (UpstreamTimeoutError, UpstreamUnavailableError, genai_errors.APIError) as exc:
            log.warning(
                "gemini.primary_failed",
                model=primary_model,
                fallback=fallback_model,
                error_type=type(exc).__name__,
            )
            fallback_used = True
            # The fallback is a second paid call. Charging it separately keeps
            # the daily cap an honest ceiling rather than a lower bound.
            self._consume_quota()
            try:
                response = await self._one_call(fallback_model, contents, config, timeout_s)
                total_attempts += 1
                model_used = fallback_model
            except Exception:
                await self._record_failure()
                raise

        await self._record_success()
        return response, AgentCallRecord(
            model_used=model_used,
            latency_s=round(time.monotonic() - started, 3),
            fallback_used=fallback_used,
            attempts=total_attempts,
        )

    async def call(
        self,
        *,
        model: str,
        contents: Sequence[Any],
        config: types.GenerateContentConfig,
        timeout_s: float,
    ) -> tuple[types.GenerateContentResponse, AgentCallRecord]:
        """Single-model invocation for callers that do not need fallback."""
        await self._check_breaker()
        self._consume_quota()

        started = time.monotonic()
        try:
            response = await self._one_call(model, contents, config, timeout_s)
        except Exception:
            await self._record_failure()
            raise
        await self._record_success()
        return response, AgentCallRecord(
            model_used=model,
            latency_s=round(time.monotonic() - started, 3),
            fallback_used=False,
            attempts=1,
        )


_client: GeminiClient | None = None


def get_client() -> GeminiClient:
    """Return the process-wide client, constructing it on first use."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client


def reset_client() -> None:
    """Discard the cached client. Intended for tests and configuration changes."""
    global _client
    _client = None


def build_text_part(text: str) -> types.Part:
    """Construct a text Part. Centralised so a future format change is one line."""
    return types.Part.from_text(text=text)


def build_image_part(data: bytes, mime_type: str) -> types.Part:
    """Construct an inline image Part from raw bytes.

    The original bytes are passed through verbatim; the client does not re-encode
    them, because re-encoding would strip the EXIF that the temporal and
    geospatial links depend on.
    """
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def build_config(
    *,
    response_schema: dict | type,
    system_instruction: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> types.GenerateContentConfig:
    """Construct a GenerateContentConfig with structured output enforced.

    system_instruction is passed as a first-class field rather than prepended to
    the user turn. Providers weight system instructions more strongly than user
    text, which matters here because the instruction carries the auditor's
    behavioural constraints rather than just formatting hints.
    """
    settings = get_settings()
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        system_instruction=system_instruction,
        temperature=temperature if temperature is not None else settings.gemini_temperature,
        max_output_tokens=max_tokens,
    )
