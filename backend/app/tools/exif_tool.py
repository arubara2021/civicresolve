"""Metadata extraction that never raises.

Absence of metadata is a normal outcome, not an error. Most upload pipelines and
messaging apps strip EXIF, so treating a missing tag as a failure would penalise
honest submissions. This tool therefore returns explicit absence plus warnings, and
the forensics layer decides what absence means.

One honesty note carried in the result: EXIF capture timestamps are local wall time
with no offset unless OffsetTimeOriginal is present. When the offset is absent the
timestamp is interpreted as UTC and capture_tz_assumed is set, so the temporal link
can state its assumption rather than silently asserting precision it does not have.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import exifread
import piexif
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger
from app.domain.schemas import GeoPoint

log = get_logger(__name__)

_MAX_RAW_TAGS = 60
_EDIT_SOFTWARE_HINTS = (
    "photoshop",
    "gimp",
    "lightroom",
    "snapseed",
    "affinity",
    "pixelmator",
    "generative",
    "firefly",
    "canva",
)


class ExifData(BaseModel):
    """Everything the deterministic links need from a file's metadata."""

    model_config = ConfigDict(frozen=True)

    exif_present: bool = False
    captured_at: datetime | None = None
    capture_tz_assumed: bool = False
    gps: GeoPoint | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    software: str | None = None
    orientation: int | None = None
    width: int | None = None
    height: int | None = None
    has_thumbnail: bool = False
    thumbnail_aspect_mismatch: bool | None = None
    edit_software_hint: bool = False
    raw: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def _ratio_to_float(value: Any) -> float | None:
    """Convert an EXIF rational to a float, tolerating both library shapes."""
    try:
        numerator = getattr(value, "num", None)
        denominator = getattr(value, "den", None)
        if numerator is not None and denominator:
            return float(numerator) / float(denominator)
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms_to_decimal(values: Any, ref: str | None) -> float | None:
    """Convert degrees/minutes/seconds plus a hemisphere reference to decimal degrees."""
    try:
        parts = [_ratio_to_float(item) for item in list(values)[:3]]
    except TypeError:
        return None
    if len(parts) < 3 or any(part is None for part in parts):
        return None

    degrees, minutes, seconds = parts
    decimal = float(degrees) + float(minutes) / 60.0 + float(seconds) / 3600.0
    if ref and ref.strip().upper() in {"S", "W"}:
        decimal = -decimal
    if decimal == 0.0:
        return None
    return decimal


def _parse_exif_datetime(text: str, offset: str | None) -> tuple[datetime | None, bool]:
    """Parse an EXIF timestamp, returning the value and whether UTC was assumed."""
    cleaned = text.strip().replace("/", ":")
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(cleaned[:19], pattern)
        except ValueError:
            continue
        if offset:
            try:
                sign = -1 if offset.strip().startswith("-") else 1
                hours, minutes = offset.strip().lstrip("+-").split(":")[:2]
                delta = timedelta(hours=int(hours), minutes=int(minutes))
                return naive.replace(tzinfo=timezone(sign * delta)), False
            except (ValueError, IndexError):
                pass
        return naive.replace(tzinfo=UTC), True
    return None, False


def _aspect_ratio(width: int, height: int) -> float | None:
    if width <= 0 or height <= 0:
        return None
    return width / height


def extract_exif(data: bytes) -> ExifData:
    """Best-effort metadata extraction. Returns absence and warnings on any failure."""
    warnings: list[str] = []
    raw: dict[str, str] = {}
    tags: dict[str, Any] = {}

    width: int | None = None
    height: int | None = None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception:
        warnings.append("image_dimensions_unreadable")

    try:
        tags = exifread.process_file(io.BytesIO(data), details=False)
    except Exception:
        warnings.append("exif_parser_failed")

    if not tags:
        # Emit the full absence vocabulary. Downstream links check for specific
        # deficiencies, and distinguishing "no EXIF at all" from "EXIF present but
        # GPS stripped" matters — the former is the honest case, the latter is a
        # red flag that the forensics layer reports explicitly.
        warnings.extend(["exif_absent", "capture_timestamp_absent", "gps_absent"])
        return ExifData(
            exif_present=False,
            width=width,
            height=height,
            warnings=warnings,
        )

    for key, tag in list(tags.items())[:_MAX_RAW_TAGS]:
        raw[key] = str(tag)

    def text_of(key: str) -> str | None:
        tag = tags.get(key)
        if tag is None:
            return None
        rendered = str(tag).strip()
        return rendered or None

    captured_at, tz_assumed = (None, False)
    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        candidate = text_of(key)
        if candidate:
            captured_at, tz_assumed = _parse_exif_datetime(
                candidate, text_of("EXIF OffsetTimeOriginal")
            )
            if captured_at is not None:
                break
    if captured_at is None:
        warnings.append("capture_timestamp_absent")
    elif tz_assumed:
        warnings.append("capture_timezone_assumed_utc")

    gps: GeoPoint | None = None
    lat_tag = tags.get("GPS GPSLatitude")
    lng_tag = tags.get("GPS GPSLongitude")
    if lat_tag is not None and lng_tag is not None:
        lat = _dms_to_decimal(lat_tag.values, text_of("GPS GPSLatitudeRef"))
        lng = _dms_to_decimal(lng_tag.values, text_of("GPS GPSLongitudeRef"))
        if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
            gps = GeoPoint(lat=lat, lng=lng)
        else:
            warnings.append("gps_tag_invalid")
    else:
        warnings.append("gps_absent")

    software = text_of("Image Software")
    edit_hint = bool(software and any(hint in software.lower() for hint in _EDIT_SOFTWARE_HINTS))

    orientation: int | None = None
    orientation_tag = tags.get("Image Orientation")
    if orientation_tag is not None:
        try:
            orientation = int(orientation_tag.values[0])
        except (TypeError, ValueError, IndexError):
            warnings.append("orientation_unreadable")

    has_thumbnail = False
    aspect_mismatch: bool | None = None
    try:
        loaded = piexif.load(data)
        thumbnail = loaded.get("thumbnail")
        if thumbnail:
            has_thumbnail = True
            with Image.open(io.BytesIO(thumbnail)) as thumb:
                thumb_ratio = _aspect_ratio(*thumb.size)
            full_ratio = _aspect_ratio(width or 0, height or 0)
            if thumb_ratio and full_ratio:
                aspect_mismatch = abs(thumb_ratio - full_ratio) > 0.05
    except Exception:
        warnings.append("thumbnail_unreadable")

    return ExifData(
        exif_present=True,
        captured_at=captured_at,
        capture_tz_assumed=tz_assumed,
        gps=gps,
        camera_make=text_of("Image Make"),
        camera_model=text_of("Image Model"),
        software=software,
        orientation=orientation,
        width=width,
        height=height,
        has_thumbnail=has_thumbnail,
        thumbnail_aspect_mismatch=aspect_mismatch,
        edit_software_hint=edit_hint,
        raw=raw,
        warnings=warnings,
    )
