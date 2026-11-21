"""Great-circle distance. Pure mathematics, no dependencies, no I/O.

Distances are reported as claimed proximity, never as proof of attendance. A
geotag can be written by a spoofing application, which is exactly what the second
Gurugram case involved, so the geospatial link states presence as a claim.
"""

from __future__ import annotations

import math

from app.domain.schemas import GeoPoint

EARTH_RADIUS_M = 6_371_008.8
"""IUGG mean Earth radius. Consistent with standard haversine implementations."""


def haversine_m(origin: GeoPoint, target: GeoPoint) -> float:
    """Return the great-circle distance between two coordinates in metres."""
    lat1 = math.radians(origin.lat)
    lat2 = math.radians(target.lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(target.lng - origin.lng)

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def within_radius(point: GeoPoint, centre: GeoPoint, radius_m: float) -> bool:
    """True when a point falls inside the asset's recorded tolerance."""
    if radius_m < 0:
        raise ValueError("radius_m must be non-negative")
    return haversine_m(point, centre) <= radius_m


def distance_to_asset(point: GeoPoint, lat: float, lng: float) -> float:
    """Convenience wrapper for comparing against an asset row."""
    return haversine_m(point, GeoPoint(lat=lat, lng=lng))
