"""Link 2: Geospatial Consistency.

Verifies that the closure photo was captured at the asset's location. Missing
geotags are a deficiency; a location mismatch is a failure.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.domain.enums import DeficiencyCode, LinkName, LinkVerdict
from app.domain.models import Asset, EvidenceFile
from app.domain.schemas import GeoPoint, LinkResult
from app.tools.geo_tool import haversine_m


def evaluate_geospatial(asset: Asset, after_evidence: EvidenceFile) -> LinkResult:
    """Check if the evidence GPS matches the asset location within tolerance."""
    settings = get_settings()

    if after_evidence.gps_lat is None or after_evidence.gps_lng is None:
        return LinkResult(
            link=LinkName.GEOSPATIAL,
            verdict=LinkVerdict.DEFICIENT,
            reason="EXIF GPS data is missing.",
            deficiencies=[DeficiencyCode.MISSING_GEOTAG],
        )

    distance = haversine_m(
        GeoPoint(lat=after_evidence.gps_lat, lng=after_evidence.gps_lng),
        GeoPoint(lat=asset.lat, lng=asset.lng),
    )

    if distance > settings.geo_tolerance_m:
        return LinkResult(
            link=LinkName.GEOSPATIAL,
            verdict=LinkVerdict.FAIL,
            reason=f"Capture location is {distance:.1f} m from asset (tolerance {settings.geo_tolerance_m} m).",
            measured_value=distance,
            threshold=settings.geo_tolerance_m,
            unit="meters",
            deficiencies=[DeficiencyCode.LOCATION_MISMATCH],
        )

    return LinkResult(
        link=LinkName.GEOSPATIAL,
        verdict=LinkVerdict.PASS,
        reason=f"Capture location is {distance:.1f} m from asset.",
        measured_value=distance,
        threshold=settings.geo_tolerance_m,
        unit="meters",
    )
