"""Synthetic seed photographs carrying real EXIF.

Images are generated rather than committed as binaries, so the repo stays small
and the demo is reproducible from source. Files stay JPEG: WebP conversion would
strip the EXIF the temporal and geospatial links depend on.

The honest capture is stamped on demand, not at seed time, because a photo
generated before the complaint was filed would fail the temporal link.
"""

from __future__ import annotations

import argparse
import io
from datetime import UTC, datetime
from pathlib import Path

import piexif
from PIL import Image, ImageDraw

SEED_DIR = Path("assets/seed")
ASSET_CENTRE = (28.45950, 77.02660)
GOOD_CAPTURE = (28.45954, 77.02657)

KINDS = ("before", "fake_after", "honest_after", "prior_reuse")


def render_road_scene(*, patched: bool, close_up: bool, seed_shift: int = 0) -> bytes:
    """Draw a deterministic road scene. No randomness, so hashes are stable."""
    width, height = 640, 480
    if close_up:
        image = Image.new("RGB", (width, height), (104, 102, 98))
        draw = ImageDraw.Draw(image)
        for y in range(0, height, 7):
            shade = 92 + ((y * 3 + seed_shift) % 26)
            draw.line([(0, y), (width, y)], fill=(shade, shade - 2, shade - 5))
        for i in range(260):
            x = (i * 137 + seed_shift * 11) % width
            y = (i * 89 + seed_shift * 7) % height
            level = 70 + (i % 40)
            draw.point((x, y), fill=(level, level, level))
        if patched:
            draw.ellipse([120, 130, 520, 360], fill=(34, 33, 36))
            draw.ellipse([150, 160, 490, 330], fill=(44, 43, 47))
            draw.arc([120, 130, 520, 360], 0, 360, fill=(150, 146, 138), width=5)
        else:
            draw.ellipse([140, 150, 500, 350], fill=(18, 16, 15))
            draw.ellipse([190, 195, 450, 315], fill=(9, 8, 8))
            draw.line([150, 250, 500, 232], fill=(128, 120, 110), width=4)
    else:
        image = Image.new("RGB", (width, height), (168, 186, 205))
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, width, 150], fill=(176, 196, 214))
        for x in range(0, width, 96):
            draw.rectangle([x + 8, 46, x + 74, 150], fill=(122, 116, 108))
            draw.rectangle([x + 20, 66, x + 40, 92], fill=(70, 78, 92))
        draw.rectangle([0, 150, width, height], fill=(98, 98, 102))
        for y in range(150, height, 22):
            shade = 88 + ((y + seed_shift) % 30)
            draw.rectangle([0, y, width, y + 11], fill=(shade, shade, shade + 4))
        draw.rectangle([0, 300, width, 306], fill=(226, 220, 120))
        draw.ellipse([268, 262, 372, 322], fill=(26, 24, 22))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Decimal degrees to EXIF degrees/minutes/seconds rationals."""
    degrees = int(abs(value))
    minutes_full = (abs(value) - degrees) * 60.0
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60.0, 3)
    return ((degrees, 1), (minutes, 1), (int(round(seconds * 1000)), 1000))


def inject_exif(
    data: bytes,
    *,
    lat: float,
    lng: float,
    captured_at: datetime,
    make: str = "Pixel",
    model: str = "Pixel 8",
    software: bytes | None = None,
) -> bytes:
    """Write GPS, capture time and camera identity into a JPEG."""
    moment = captured_at.astimezone(UTC)
    zeroth = {
        piexif.ImageIFD.Make: make.encode("ascii"),
        piexif.ImageIFD.Model: model.encode("ascii"),
    }
    if software is not None:
        zeroth[piexif.ImageIFD.Software] = software
    exif = {
        "0th": zeroth,
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: moment.strftime("%Y:%m:%d %H:%M:%S").encode("ascii"),
            piexif.ExifIFD.OffsetTimeOriginal: b"+00:00",
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lng >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _dms(lng),
        },
        "1st": {},
        "thumbnail": None,
    }
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(data)) as image:
        image.save(buffer, format="JPEG", quality=90, exif=piexif.dump(exif))
    return buffer.getvalue()


def build_scene(kind: str, *, captured_at: datetime | None = None, variant: int = 0) -> bytes:
    """Produce one of the four demo photographs.

    prior_reuse variants differ in bytes but share a perceptual hash, which is
    exactly the Panchkula pattern: the same photograph re-saved per ticket.
    fake_after carries no EXIF at all, as a messaging-app forward would not.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown scene kind {kind!r}; expected one of {KINDS}")
    moment = captured_at or datetime.now(UTC)

    if kind == "prior_reuse":
        return render_road_scene(patched=False, close_up=False, seed_shift=variant * 13)
    if kind == "fake_after":
        return render_road_scene(patched=False, close_up=False)
    if kind == "before":
        raw = render_road_scene(patched=False, close_up=True)
    else:
        raw = render_road_scene(patched=True, close_up=True)
    return inject_exif(raw, lat=GOOD_CAPTURE[0], lng=GOOD_CAPTURE[1], captured_at=moment)


def write_seed_images(out_dir: Path = SEED_DIR) -> dict[str, Path]:
    """Write the demo photographs to disk for manual upload during the demo."""
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    written: dict[str, Path] = {}
    for kind in ("before", "fake_after", "honest_after"):
        path = out_dir / f"{kind}.jpg"
        path.write_bytes(build_scene(kind, captured_at=now))
        written[kind] = path
    for index in range(6):
        path = out_dir / f"prior_reuse_{index + 1}.jpg"
        path.write_bytes(build_scene("prior_reuse", variant=index))
        written[f"prior_reuse_{index + 1}"] = path
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic seed JPEGs with EXIF.")
    parser.add_argument("--out", default=str(SEED_DIR), help="Output directory")
    args = parser.parse_args()
    for name, path in write_seed_images(Path(args.out)).items():
        print(f"{name:16s} -> {path}  ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()