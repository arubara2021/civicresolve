"""Deterministic tool assertions.

Where the mathematics is exact, the number is asserted exactly: the 5.3 m capture
offset, Hamming distances on constructed hashes, cosine 1.0 on identical remarks.
Where perception is involved, the discriminative property is asserted instead of a
magic number, because pinning a perceptual distance to a specific integer would make
the test brittle without making the system more correct.

One test deliberately documents a limitation rather than a capability: a genuine
repair at the same location can stay inside the reuse threshold. That finding is
why reuse requires corroboration and is scoped to prior closure evidence.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import piexif
import pytest
from PIL import Image, ImageDraw, ImageEnhance
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EvidenceUnreadableError, PayloadTooLargeError
from app.domain.enums import Category, DecisionType, Status, SubStatus, Urgency
from app.domain.models import Asset, ClosureAttempt, Complaint, Decision
from app.domain.priority import compute_priority, history_risk
from app.domain.schemas import GeoPoint
from app.storage.local import LocalStorage
from app.tools.asset_history import build_snapshot
from app.tools.dup_text_tool import DuplicationIndex, exact_signature, normalize_remarks
from app.tools.exif_tool import extract_exif
from app.tools.geo_tool import distance_to_asset, haversine_m, within_radius
from app.tools.phash_tool import (
    BKTree,
    build_index,
    compute_dhash,
    compute_phash,
    hamming,
    int_to_hash,
    reuse_verdict,
)

ASSET_CENTRE = GeoPoint(lat=28.45950, lng=77.02660)
GOOD_CAPTURE = GeoPoint(lat=28.45954, lng=77.02657)
DISTANT_POINT = GeoPoint(lat=28.46310, lng=77.02290)

CLOSURE_REMARK = "Pothole filled with bitumen; road restored to motarable condition."
HONEST_REMARK = (
    "Left wheel path pothole at school gate cut and filled with bitumen mix, "
    "compacted, edge sealed — WO/4471"
)


def _road_image(*, patched: bool, seed_shift: int = 0) -> bytes:
    """Render a deterministic synthetic road scene. No randomness."""
    image = Image.new("RGB", (640, 480), (96, 96, 100))
    draw = ImageDraw.Draw(image)
    for row in range(0, 480, 24):
        shade = 88 + ((row + seed_shift) % 32)
        draw.rectangle([0, row, 640, row + 12], fill=(shade, shade, shade + 4))
    draw.rectangle([0, 300, 640, 306], fill=(228, 220, 120))
    if patched:
        draw.ellipse([250, 250, 400, 340], fill=(38, 38, 42))
    else:
        draw.ellipse([260, 260, 390, 330], fill=(24, 22, 20))
        draw.line([265, 300, 385, 292], fill=(140, 130, 120), width=3)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _unrelated_scene() -> bytes:
    """A structurally different scene: vertical massing and an inverted gradient.

    Used to assert discrimination, not a specific distance. The road fixture is
    dominated by horizontal structure; this one is dominated by vertical structure.
    """
    image = Image.new("RGB", (640, 480), (18, 18, 22))
    draw = ImageDraw.Draw(image)
    for row in range(480):
        level = 15 + int(225 * (1 - row / 480))
        draw.line([(0, row), (640, row)], fill=(level, level, level))
    for column in range(0, 640, 80):
        draw.rectangle([column, 110, column + 42, 480], fill=(10, 10, 14))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _brightened(data: bytes, delta: int = 3) -> bytes:
    """A near-duplicate: the same scene with a barely perceptible global shift."""
    with Image.open(io.BytesIO(data)) as image:
        adjusted = ImageEnhance.Brightness(image).enhance(1.0 + delta / 255.0)
        buffer = io.BytesIO()
        adjusted.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


def _dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    degrees = int(abs(value))
    minutes_full = (abs(value) - degrees) * 60.0
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60.0, 3)
    return ((degrees, 1), (minutes, 1), (int(round(seconds * 1000)), 1000))


def _tagged_image(point: GeoPoint, moment: str, *, software: bytes | None = None) -> bytes:
    """A JPEG carrying the metadata an honest in-app capture would produce."""
    base = _road_image(patched=True)
    exif = {
        "0th": {
            piexif.ImageIFD.Make: b"Pixel",
            piexif.ImageIFD.Model: b"Pixel 8",
        },
        "Exif": {piexif.ExifIFD.DateTimeOriginal: moment.encode("ascii")},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: _dms(point.lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: _dms(point.lng),
        },
        "1st": {},
        "thumbnail": None,
    }
    if software is not None:
        exif["0th"][piexif.ImageIFD.Software] = software
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(base)) as image:
        image.save(buffer, format="JPEG", quality=90, exif=piexif.dump(exif))
    return buffer.getvalue()


# Geospatial. Exact arithmetic.


def test_good_capture_is_five_point_three_metres_from_the_asset() -> None:
    assert round(haversine_m(GOOD_CAPTURE, ASSET_CENTRE), 1) == 5.3


def test_good_capture_is_within_tolerance() -> None:
    assert within_radius(GOOD_CAPTURE, ASSET_CENTRE, 50.0) is True


def test_distant_point_is_outside_tolerance() -> None:
    distance = distance_to_asset(DISTANT_POINT, ASSET_CENTRE.lat, ASSET_CENTRE.lng)
    assert 530.0 < distance < 550.0
    assert within_radius(DISTANT_POINT, ASSET_CENTRE, 50.0) is False


def test_identical_points_are_zero_metres_apart() -> None:
    assert haversine_m(ASSET_CENTRE, ASSET_CENTRE) == 0.0


def test_distance_is_symmetric() -> None:
    forward = haversine_m(GOOD_CAPTURE, ASSET_CENTRE)
    backward = haversine_m(ASSET_CENTRE, GOOD_CAPTURE)
    assert abs(forward - backward) < 1e-6


def test_negative_radius_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        within_radius(GOOD_CAPTURE, ASSET_CENTRE, -1.0)


# Perceptual hashing and the metric tree. Exact integer distances.


def test_hamming_distances_on_constructed_hashes_are_exact() -> None:
    base = int_to_hash(0)

    assert hamming(base, int_to_hash(0b11)) == 2
    assert hamming(base, int_to_hash(0xFF)) == 8
    assert hamming(base, int_to_hash(0x1FF)) == 9
    assert hamming(base, base) == 0


def test_bktree_finds_the_reused_photo_at_distance_two() -> None:
    """Distances from query 0b11: 0x0 is 2, 0xFF is 6, 0x1FF is 7. All within 8."""
    tree = build_index(
        [
            ("EVI-0001", int_to_hash(0)),
            ("EVI-0002", int_to_hash(0xFF)),
            ("EVI-0003", int_to_hash(0x1FF)),
        ]
    )
    hits = tree.search(int_to_hash(0b11), max_distance=8)

    assert [(hit.identifier, hit.distance) for hit in hits] == [
        ("EVI-0001", 2),
        ("EVI-0002", 6),
        ("EVI-0003", 7),
    ]


def test_bktree_tight_radius_isolates_the_reuse() -> None:
    tree = build_index(
        [
            ("EVI-0001", int_to_hash(0)),
            ("EVI-0002", int_to_hash(0xFF)),
            ("EVI-0003", int_to_hash(0x1FF)),
        ]
    )
    hits = tree.search(int_to_hash(0b11), max_distance=2)

    assert [hit.identifier for hit in hits] == ["EVI-0001"]


def test_bktree_excludes_beyond_the_threshold() -> None:
    tree = build_index([("EVI-0003", int_to_hash(0x1FF))])
    assert tree.search(int_to_hash(0), max_distance=8) == []


def test_bktree_groups_identical_hashes() -> None:
    tree = BKTree()
    for index in range(6):
        tree.insert(int_to_hash(0), f"EVI-{index:04d}")

    assert len(tree) == 1
    assert len(tree.search(int_to_hash(0), max_distance=0)) == 6


def test_bktree_nearest_and_empty_behaviour() -> None:
    empty = BKTree()
    assert empty.search(int_to_hash(0), 8) == []
    assert empty.nearest(int_to_hash(0)) is None

    tree = build_index([("EVI-0009", int_to_hash(0x1FF))])
    nearest = tree.nearest(int_to_hash(0))
    assert nearest is not None
    assert nearest.distance == 9


def test_phash_is_deterministic_and_detects_a_near_duplicate() -> None:
    original = _road_image(patched=False)
    reused = _brightened(original)

    first = compute_phash(original)
    assert compute_phash(original) == first
    assert hamming(first, compute_phash(reused)) <= 8


def test_phash_ranks_reuse_closer_than_an_unrelated_scene() -> None:
    """The discriminative property, asserted without pinning a perceptual number."""
    before = _road_image(patched=False)
    reuse_distance = hamming(compute_phash(before), compute_phash(_brightened(before)))
    unrelated_distance = hamming(compute_phash(before), compute_phash(_unrelated_scene()))

    assert reuse_distance <= 8
    assert unrelated_distance > reuse_distance


def test_phash_is_a_reuse_detector_not_a_change_detector() -> None:
    """Documented limitation, not a capability.

    A genuine repair at the same location shares the scene's low-frequency layout
    and can land inside the similarity threshold. Phase 7 therefore scopes reuse
    comparison to prior closure evidence and requires corroboration, rather than
    comparing an after image against its own before image.
    """
    before = _road_image(patched=False)
    repaired = _road_image(patched=True, seed_shift=17)

    assert hamming(compute_phash(before), compute_phash(repaired)) <= 8


def test_reuse_verdict_requires_corroboration() -> None:
    assert reuse_verdict(40, identical_content=True, threshold=8) == "reuse"
    assert reuse_verdict(4, identical_content=False, threshold=8) == "similar"


def test_reuse_verdict_strict_distance() -> None:
    assert reuse_verdict(0, identical_content=False, threshold=8) == "reuse"
    assert reuse_verdict(2, identical_content=False, threshold=8) == "reuse"
    assert reuse_verdict(2, identical_content=False, threshold=8, strict_distance=1) == "similar"


def test_reuse_verdict_distinct_and_validation() -> None:
    assert reuse_verdict(9, identical_content=False, threshold=8) == "distinct"
    with pytest.raises(ValueError, match="non-negative"):
        reuse_verdict(-1, identical_content=False, threshold=8)


def test_dhash_is_stable_and_sensitive() -> None:
    original = _road_image(patched=False)
    assert compute_dhash(original) == compute_dhash(original)
    assert hamming(compute_dhash(original), compute_dhash(_brightened(original))) <= 12


def test_hashing_corrupt_bytes_raises_a_typed_error() -> None:
    with pytest.raises(EvidenceUnreadableError):
        compute_phash(b"not an image")


def test_malformed_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="hex characters"):
        hamming("abcd", int_to_hash(0))


# Metadata extraction.


def test_absent_metadata_is_reported_not_raised() -> None:
    result = extract_exif(_road_image(patched=True))

    assert result.exif_present is False
    assert result.captured_at is None
    assert result.gps is None
    assert "exif_absent" in result.warnings
    assert "gps_absent" in result.warnings
    assert "capture_timestamp_absent" in result.warnings
    assert result.width == 640


def test_corrupt_bytes_never_raise() -> None:
    result = extract_exif(b"\x00\x01garbage")

    assert result.exif_present is False
    assert result.warnings


def test_injected_capture_metadata_round_trips_to_five_point_three_metres() -> None:
    data = _tagged_image(GOOD_CAPTURE, "2026:11:20 14:07:22")
    result = extract_exif(data)

    assert result.exif_present is True
    assert result.captured_at == datetime(2026, 11, 20, 14, 7, 22, tzinfo=UTC)
    assert result.capture_tz_assumed is True
    assert result.gps is not None
    assert round(haversine_m(result.gps, ASSET_CENTRE), 1) == 5.3
    assert result.camera_model == "Pixel 8"


def test_editing_software_tag_is_surfaced() -> None:
    data = _tagged_image(GOOD_CAPTURE, "2026:11:20 14:07:22", software=b"Adobe Photoshop 25.0")
    result = extract_exif(data)

    assert result.software is not None
    assert result.edit_software_hint is True


# Remark duplication.


def test_normalisation_preserves_the_shared_typo() -> None:
    normalized = normalize_remarks(CLOSURE_REMARK)

    assert "motarable" in normalized
    assert normalized == "pothole filled with bitumen road restored to motarable condition"


def test_punctuation_and_case_variants_share_a_signature() -> None:
    variant = "POTHOLE FILLED WITH BITUMEN, ROAD RESTORED TO MOTARABLE CONDITION"
    assert exact_signature(variant) == exact_signature(CLOSURE_REMARK)


def test_identical_remark_across_six_tickets_scores_one() -> None:
    index = DuplicationIndex()
    identifiers = ["WRD-1042", "WRD-1044", "WRD-1051", "WRD-1055", "WRD-1060", "WRD-1063"]
    for identifier in identifiers:
        index.upsert("WARD-12", identifier, CLOSURE_REMARK)

    matches = index.query("WARD-12", CLOSURE_REMARK, threshold=0.92)

    assert len(matches) == 6
    assert all(match.exact for match in matches)
    assert all(match.score >= 0.999 for match in matches)
    assert {match.identifier for match in matches} == set(identifiers)


def test_site_specific_remark_does_not_match_the_bulk_corpus() -> None:
    index = DuplicationIndex()
    for identifier in ("WRD-1042", "WRD-1044"):
        index.upsert("WARD-12", identifier, CLOSURE_REMARK)

    assert index.query("WARD-12", HONEST_REMARK, threshold=0.92) == []


def test_query_can_exclude_itself() -> None:
    index = DuplicationIndex()
    index.upsert("WARD-12", "WRD-1071", CLOSURE_REMARK)
    index.upsert("WARD-12", "WRD-1042", CLOSURE_REMARK)

    matches = index.query("WARD-12", CLOSURE_REMARK, exclude_identifier="WRD-1071")
    assert [match.identifier for match in matches] == ["WRD-1042"]


def test_wards_are_isolated_and_invalidation_works() -> None:
    index = DuplicationIndex()
    index.upsert("WARD-12", "WRD-1042", CLOSURE_REMARK)
    index.upsert("WARD-13", "WRD-2001", CLOSURE_REMARK)

    assert index.size("WARD-12") == 1
    assert index.query("WARD-99", CLOSURE_REMARK) == []

    index.invalidate("WARD-12")
    assert index.size("WARD-12") == 0
    assert index.size("WARD-13") == 1


def test_empty_remark_is_ignored() -> None:
    index = DuplicationIndex()
    index.upsert("WARD-12", "WRD-1042", "   ")
    assert index.size("WARD-12") == 0


# Storage.


async def test_original_bytes_are_preserved_and_deduplicated(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    data = _tagged_image(GOOD_CAPTURE, "2026:11:20 14:07:22")

    first = await storage.save_original(data)
    second = await storage.save_original(data)

    assert first.key == second.key
    assert await storage.read(first.key) == data
    assert extract_exif(await storage.read(first.key)).gps is not None


async def test_thumbnail_is_smaller_and_separate(tmp_path) -> None:
    storage = LocalStorage(tmp_path, thumbnail_max_px=320)
    original = await storage.save_original(_road_image(patched=True))
    preview = await storage.make_thumbnail(_road_image(patched=True))

    assert preview.key != original.key
    assert preview.size_bytes < original.size_bytes


async def test_oversize_upload_is_rejected(tmp_path) -> None:
    storage = LocalStorage(tmp_path, max_bytes=10)
    with pytest.raises(PayloadTooLargeError):
        await storage.save_original(_road_image(patched=True))


async def test_non_image_upload_is_rejected(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(EvidenceUnreadableError):
        await storage.save_original(b"definitely not an image")


# History feeding priority. This is the cross-phase integration assertion.


async def test_chronic_asset_history_reproduces_priority_eighty(
    session: AsyncSession, asset: Asset
) -> None:
    """Six declared fixes and five reopens must yield history risk 100 and score 79.9."""
    reopen_budget = [1, 1, 1, 1, 1, 0]
    for index, reopens in enumerate(reopen_budget, start=1):
        session.add(
            Complaint(
                id=f"WRD-10{index:02d}",
                asset_id=asset.id,
                reporter_id=f"CIT-{index:03d}",
                title="Pothole in left wheel path",
                description="Recurring pothole near the school gate.",
                category=Category.POTHOLE.value,
                ward="WARD-12",
                lat=ASSET_CENTRE.lat,
                lng=ASSET_CENTRE.lng,
                status=Status.RESOLVED.value,
                sub_status=SubStatus.CITIZEN_ACCEPTED.value,
                department="roads_maintenance",
                reopen_count=reopens,
            )
        )
    await session.flush()

    rejected = ClosureAttempt(
        id="ATT-0001",
        complaint_id="WRD-1001",
        asset_id=asset.id,
        attempt_number=1,
        officer_id="OFF-117",
        remarks=CLOSURE_REMARK,
        chain_sufficient=False,
    )
    session.add(rejected)
    await session.flush()

    session.add(
        Decision(
            id="DEC-0001",
            attempt_id="ATT-0001",
            complaint_id="WRD-1001",
            actor_type="citizen",
            actor_id="CIT-201",
            decision=DecisionType.REJECT.value,
            reason="Road still broken at the reported location.",
            chain_sufficient_at_decision=False,
        )
    )
    await session.commit()

    snapshot = await build_snapshot(session, asset.id, exclude_complaint_id="WRD-1071")

    assert snapshot.prior_complaints == 6
    assert snapshot.prior_closures == 6
    assert snapshot.reopen_count == 5
    assert snapshot.failed_closure_attempts == 1
    assert snapshot.open_age_days == 0.0
    assert history_risk(snapshot) == 100.0

    result = compute_priority(Urgency.P2, 78, snapshot)
    assert result.score == 79.9
    assert result.final_urgency is Urgency.P1


async def test_new_asset_has_no_history(session: AsyncSession) -> None:
    session.add(Asset(id="AST-9999", ward="WARD-12", label="New segment", lat=28.46, lng=77.03))
    await session.commit()

    snapshot = await build_snapshot(session, "AST-9999")

    assert snapshot.prior_complaints == 0
    assert snapshot.reopen_count == 0
    assert history_risk(snapshot) == 0.0
