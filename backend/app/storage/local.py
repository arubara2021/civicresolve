"""Content-addressed local storage.

The sha256 of the bytes is the filename, so dedup is free and a reused photograph
is provably the same file. Originals are written verbatim — never re-encoded —
because re-encoding destroys the EXIF the temporal and geospatial links need.
Only the derived thumbnail is compressed.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from app.core.security import ensure_allowed_mime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import (
    EvidenceUnreadableError,
    NotFoundError,
    PayloadTooLargeError,
    StorageFailureError,
)
from app.core.logging import get_logger

from .base import StoredObject

log = get_logger(__name__)

_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "HEIF": ".heic", "GIF": ".gif"}
_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "HEIF": "image/heic",
    "GIF": "image/gif",
}


class LocalStorage:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        thumbnail_max_px: int | None = None,
        jpeg_quality: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self._root = Path(root).expanduser().resolve() if root is not None else settings.upload_path
        self._thumb_px = thumbnail_max_px or settings.thumbnail_max_px
        self._quality = jpeg_quality or settings.jpeg_quality
        self._max_bytes = max_bytes if max_bytes is not None else settings.max_upload_bytes
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageFailureError("Storage key escapes the upload root.")
        return candidate

    @staticmethod
    def _sniff(data: bytes) -> str:
        try:
            with Image.open(io.BytesIO(data)) as image:
                fmt = (image.format or "JPEG").upper()
                image.verify()
                return fmt
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise EvidenceUnreadableError("Uploaded file is not a readable image.") from exc

    async def _write(self, key: str, data: bytes) -> None:
        path = self._resolve(key)

        def _sync() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                return
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)

        try:
            await asyncio.to_thread(_sync)
        except OSError as exc:
            raise StorageFailureError(f"Could not write evidence: {exc}") from exc

    async def save_original(self, data: bytes, *, mime_type: str | None = None) -> StoredObject:
        if not data:
            raise EvidenceUnreadableError("Uploaded file is empty.")
        if len(data) > self._max_bytes:
            raise PayloadTooLargeError(
                f"File is {len(data)} bytes; limit is {self._max_bytes}.",
                extra={"limit_bytes": self._max_bytes},
            )
        fmt = await asyncio.to_thread(self._sniff, data)
        ensure_allowed_mime(_MIME.get(fmt, "application/octet-stream"))
        digest = hashlib.sha256(data).hexdigest()
        key = f"originals/{digest[:2]}/{digest}{_EXT.get(fmt, '.bin')}"
        await self._write(key, data)
        return StoredObject(
            key=key,
            content_hash=digest,
            size_bytes=len(data),
            mime_type=mime_type or _MIME.get(fmt, "application/octet-stream"),
        )

    async def make_thumbnail(self, data: bytes) -> StoredObject:
        def _sync() -> bytes:
            with Image.open(io.BytesIO(data)) as image:
                rgb = image.convert("RGB")
                rgb.thumbnail((self._thumb_px, self._thumb_px), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                rgb.save(buffer, format="JPEG", quality=self._quality, optimize=True)
                return buffer.getvalue()

        try:
            preview = await asyncio.to_thread(_sync)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise EvidenceUnreadableError("Could not render a preview of this image.") from exc

        digest = hashlib.sha256(preview).hexdigest()
        key = f"thumbnails/{digest[:2]}/{digest}.jpg"
        await self._write(key, preview)
        return StoredObject(
            key=key, content_hash=digest, size_bytes=len(preview), mime_type="image/jpeg"
        )

    async def read(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise NotFoundError(f"Evidence {key!r} is not in storage.") from exc
        except OSError as exc:
            raise StorageFailureError(f"Could not read evidence: {exc}") from exc

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._resolve(key).is_file)

    def path_for(self, key: str) -> str:
        return str(self._resolve(key))


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None