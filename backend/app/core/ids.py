"""Human-readable identifiers and opaque tokens.

Public identifiers are prefixed and zero-padded so they are quotable in a support
conversation and sortable by creation order. Sequences are held in process memory
here; Phase 2 replaces the allocator with a database-backed implementation behind
the identical interface, so no call site changes.

Trace identifiers are 32 lowercase hex characters, matching the W3C trace-context
trace-id grammar, which allows later correlation with an external tracer.
"""

from __future__ import annotations

import re
import secrets
import threading
import uuid
from enum import StrEnum

_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SAFE_INBOUND_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class IdPrefix(StrEnum):
    """Entity prefixes used across the public API."""

    COMPLAINT = "WRD"
    ASSET = "AST"
    ATTEMPT = "ATT"
    EVENT = "EVT"
    EVIDENCE = "EVI"
    DECISION = "DEC"
    NOTIFICATION = "NTF"
    ACTOR = "ACT"


_PADDING: dict[IdPrefix, int] = {
    IdPrefix.COMPLAINT: 4,
    IdPrefix.ASSET: 4,
    IdPrefix.ATTEMPT: 4,
    IdPrefix.EVENT: 6,
    IdPrefix.EVIDENCE: 4,
    IdPrefix.DECISION: 4,
    IdPrefix.NOTIFICATION: 6,
    IdPrefix.ACTOR: 4,
}


def format_id(prefix: IdPrefix, sequence: int) -> str:
    """Render a prefixed identifier, raising if the sequence overflows its width."""
    if sequence < 0:
        raise ValueError("sequence must be non-negative")
    width = _PADDING[prefix]
    if sequence >= 10**width:
        raise ValueError(f"sequence {sequence} exceeds {width}-digit width for {prefix.value}")
    return f"{prefix.value}-{sequence:0{width}d}"


def parse_id(identifier: str) -> tuple[IdPrefix, int]:
    """Split a prefixed identifier into its prefix and numeric sequence."""
    prefix_part, separator, sequence_part = identifier.partition("-")
    if not separator or not sequence_part.isdigit():
        raise ValueError(f"malformed identifier: {identifier!r}")
    try:
        prefix = IdPrefix(prefix_part.upper())
    except ValueError as exc:
        raise ValueError(f"unknown identifier prefix: {prefix_part!r}") from exc
    return prefix, int(sequence_part)


def is_valid_id(identifier: str) -> bool:
    """Return True if the string is a well-formed identifier of a known entity."""
    try:
        parse_id(identifier)
    except ValueError:
        return False
    return True


class IdAllocator:
    """Thread-safe monotonic sequence source.

    A lock is used rather than an asyncio lock because allocation performs no
    awaitable work; this keeps the call synchronous and usable from any context.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[IdPrefix, int] = dict.fromkeys(IdPrefix, 0)

    def next_id(self, prefix: IdPrefix) -> str:
        """Allocate the next identifier for an entity type."""
        with self._lock:
            self._counters[prefix] += 1
            return format_id(prefix, self._counters[prefix])

    def set_sequence(self, prefix: IdPrefix, value: int) -> None:
        """Seed the counter so the next allocation is value + 1.

        Used by the demo seeder to reproduce the identifiers in the fixture, and
        by the database-backed allocator to resume above the persisted maximum.
        """
        if value < 0:
            raise ValueError("sequence value must be non-negative")
        with self._lock:
            self._counters[prefix] = value

    def peek(self, prefix: IdPrefix) -> int:
        """Return the last allocated sequence without advancing it."""
        with self._lock:
            return self._counters[prefix]

    def reset(self) -> None:
        """Clear all counters. Intended for tests and demo resets."""
        with self._lock:
            self._counters = dict.fromkeys(IdPrefix, 0)


_allocator = IdAllocator()


def next_id(prefix: IdPrefix) -> str:
    """Allocate from the process-wide allocator."""
    return _allocator.next_id(prefix)


def set_sequence(prefix: IdPrefix, value: int) -> None:
    """Seed the process-wide allocator."""
    _allocator.set_sequence(prefix, value)


def reset_sequences() -> None:
    """Reset the process-wide allocator."""
    _allocator.reset()


def get_allocator() -> IdAllocator:
    """Expose the allocator for dependency injection in tests."""
    return _allocator


def new_trace_id() -> str:
    """Generate a W3C-compatible 32-hex trace identifier."""
    return uuid.uuid4().hex


def normalise_inbound_trace_id(candidate: str | None) -> str | None:
    """Accept a caller-supplied identifier only if it is safe to log and echo.

    Untrusted input is length-limited and character-restricted to prevent log
    injection and header smuggling.
    """
    if not candidate:
        return None
    cleaned = candidate.strip()
    if _TRACE_ID_PATTERN.match(cleaned):
        return cleaned
    if _SAFE_INBOUND_ID.match(cleaned):
        return cleaned
    return None


def trace_id_from_traceparent(header: str | None) -> str | None:
    """Extract the trace-id from a W3C traceparent header, if well formed."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    candidate = parts[1].lower()
    if not _TRACE_ID_PATTERN.match(candidate) or candidate == "0" * 32:
        return None
    return candidate


def new_token(nbytes: int = 16) -> str:
    """Generate an opaque URL-safe token for idempotency keys and stream cursors."""
    return secrets.token_urlsafe(nbytes)
