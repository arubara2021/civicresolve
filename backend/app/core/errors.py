"""Application error taxonomy and RFC 9457 Problem Details responses.

Every failure leaving this API has the same shape and a stable machine-readable
code. Clients branch on ``code``, never on prose. Unexpected exceptions are logged
with a full traceback but reported to the caller as a generic internal error, so
implementation detail never leaks through an error body.

The ``type`` member is a stable identifier for the problem class. It is not
required to resolve to a live document.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import ensure_trace_id, get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://civicresolve.dev/problems"

log = get_logger(__name__)


class ErrorCode(StrEnum):
    """Stable identifiers. Values are part of the public API contract."""

    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    EVIDENCE_UNREADABLE = "EVIDENCE_UNREADABLE"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    STORAGE_FAILURE = "STORAGE_FAILURE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for expected, deliberately raised failures.

    Subclasses set the class-level defaults; call sites supply only a detail
    message and optional structured context.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: int = 500
    title: str = "Internal error"
    retryable: bool = False

    def __init__(
        self,
        detail: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.title
        self.extra = extra or {}
        self.headers = headers or {}
        super().__init__(self.detail)

    def to_problem(self, trace_id: str) -> dict[str, Any]:
        """Render the RFC 9457 representation of this failure."""
        slug = self.code.value.lower().replace("_", "-")
        problem: dict[str, Any] = {
            "type": f"{PROBLEM_TYPE_BASE}/{slug}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
            "code": self.code.value,
            "trace_id": trace_id,
            "retryable": self.retryable,
        }
        if self.extra:
            problem["context"] = self.extra
        return problem


class BadRequestError(AppError):
    code = ErrorCode.BAD_REQUEST
    status_code = 400
    title = "Malformed request"


class ValidationFailedError(AppError):
    code = ErrorCode.VALIDATION_FAILED
    status_code = 422
    title = "Request validation failed"


class UnauthenticatedError(AppError):
    code = ErrorCode.UNAUTHENTICATED
    status_code = 401
    title = "Authentication required"


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    status_code = 403
    title = "Action not permitted"


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    status_code = 404
    title = "Resource not found"


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    status_code = 409
    title = "Conflicting state"


class InvalidStateTransitionError(AppError):
    """Raised when a status change is not permitted by the closure protocol."""

    code = ErrorCode.INVALID_STATE_TRANSITION
    status_code = 409
    title = "Illegal status transition"


class PayloadTooLargeError(AppError):
    code = ErrorCode.PAYLOAD_TOO_LARGE
    status_code = 413
    title = "Upload exceeds size limit"


class UnsupportedMediaTypeError(AppError):
    code = ErrorCode.UNSUPPORTED_MEDIA_TYPE
    status_code = 415
    title = "Unsupported file type"


class RateLimitedError(AppError):
    code = ErrorCode.RATE_LIMITED
    status_code = 429
    title = "Too many requests"
    retryable = True

    def __init__(self, detail: str | None = None, *, retry_after_s: int = 60) -> None:
        super().__init__(detail, headers={"Retry-After": str(retry_after_s)})


class QuotaExceededError(AppError):
    """The configured daily model-call ceiling has been reached."""

    code = ErrorCode.QUOTA_EXCEEDED
    status_code = 429
    title = "Model quota exhausted"
    retryable = True


class EvidenceUnreadableError(AppError):
    """An uploaded file could not be decoded or its metadata could not be parsed."""

    code = ErrorCode.EVIDENCE_UNREADABLE
    status_code = 422
    title = "Evidence file unreadable"


class UpstreamTimeoutError(AppError):
    code = ErrorCode.UPSTREAM_TIMEOUT
    status_code = 504
    title = "Model request timed out"
    retryable = True


class UpstreamUnavailableError(AppError):
    """Model access failed. Callers must degrade, never resolve a complaint."""

    code = ErrorCode.UPSTREAM_UNAVAILABLE
    status_code = 503
    title = "Model temporarily unavailable"
    retryable = True


class StorageFailureError(AppError):
    code = ErrorCode.STORAGE_FAILURE
    status_code = 500
    title = "Evidence storage failure"


class ConfigurationError(AppError):
    code = ErrorCode.CONFIGURATION_ERROR
    status_code = 500
    title = "Server misconfiguration"


class InternalError(AppError):
    code = ErrorCode.INTERNAL_ERROR
    status_code = 500
    title = "Internal error"


_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    429: ErrorCode.RATE_LIMITED,
}


def _problem_response(
    problem: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Emit a problem document, always echoing the trace identifier as a header."""
    response_headers = {"X-Trace-Id": problem["trace_id"]}
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=problem["status"],
        content=problem,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=response_headers,
    )


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Handle deliberately raised application failures."""
    trace_id = ensure_trace_id()
    problem = exc.to_problem(trace_id)

    event = "error.client" if exc.status_code < 500 else "error.server"
    logger = log.warning if exc.status_code < 500 else log.error
    logger(event, code=exc.code.value, status=exc.status_code, detail=exc.detail, **exc.extra)

    return _problem_response(problem, exc.headers)


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Normalise FastAPI validation output into the problem shape.

    The raw error list can contain non-serialisable objects inside ``ctx``, so
    fields are projected explicitly rather than passed through.
    """
    trace_id = ensure_trace_id()
    fields = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]) or "body",
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    error = ValidationFailedError(
        "One or more fields failed validation.",
        extra={"fields": fields},
    )
    log.warning("error.validation", code=error.code.value, field_count=len(fields))
    return _problem_response(error.to_problem(trace_id))


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Map framework-level HTTP exceptions onto the same envelope."""
    trace_id = ensure_trace_id()
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."

    problem = {
        "type": f"{PROBLEM_TYPE_BASE}/{code.value.lower().replace('_', '-')}",
        "title": detail,
        "status": exc.status_code,
        "detail": detail,
        "code": code.value,
        "trace_id": trace_id,
        "retryable": exc.status_code in {429, 503},
    }
    log.warning("error.http", code=code.value, status=exc.status_code)
    return _problem_response(problem, dict(exc.headers or {}))


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler. Logs the traceback, returns an opaque failure."""
    trace_id = ensure_trace_id()
    settings = get_settings()

    log.exception("error.unhandled", exception_type=type(exc).__name__)

    error = InternalError(
        str(exc) if settings.debug else "An unexpected error occurred. Quote the trace_id."
    )
    problem = error.to_problem(trace_id)
    if settings.debug:
        problem["context"] = {"exception_type": type(exc).__name__}
    return _problem_response(problem)


def register_error_handlers(app: FastAPI) -> None:
    """Attach every handler. Called once from the application factory."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
