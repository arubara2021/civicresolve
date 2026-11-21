"""Storage port. Local disk now, S3/R2 later, no caller changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Result of a content-addressed write."""

    key: str
    content_hash: str
    size_bytes: int
    mime_type: str


@runtime_checkable
class StoragePort(Protocol):
    async def save_original(self, data: bytes, *, mime_type: str | None = None) -> StoredObject: ...
    async def make_thumbnail(self, data: bytes) -> StoredObject: ...
    async def read(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    def path_for(self, key: str) -> str: ...