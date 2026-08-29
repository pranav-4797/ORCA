"""
SAR Boundary Utilities — distance to India's maritime boundary.

Reuses the same marine_boundaries.geojson and geospatial math as
GeospatialAgent, but exposed as pure functions for the SAR pipeline.

All distances use the same haversine + segment projection as the
existing geofence so results are consistent between safety checks and
SAR proximity.
"""
from __future__ import annotations

import json
import math
import os
from typing import Optional

# Mirror the geospatial_agent utils — keep in sync
_BOUNDARIES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "marine_boundaries.geojson")


def _load_boundaries() -> list[dict]:
    try:
        with open(_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("features", [])
    except Exception:
        return []


_FEATURES: list[dict] | None = None


def _features() -> list[dict]:
    global _FEATURES
    if _FEATURES is None:
        _FEATURES = _load_boundaries()
    return _FEATURES


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _dist_to_segment_km(lat, lon, a: list[float], b: list[float]) -> float:
    """Approximate distance from point to segment [lon,lat]-[lon,lat]."""
    k = 111.32
    px = (lon - a[0]) * k * math.cos(math.radians(lat))
    py = (lat - a[1]) * k
    qx = (b[0] - a[0]) * k * math.cos(math.radians((a[1] + b[1]) / 2))
    qy = (b[1] - a[1]) * k
    seg2 = qx * qx + qy * qy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, (px * qx + py * qy) / seg2))
    dx = px - t * qx
    dy = py - t * qy
    return math.hypot(dx, dy)


def _point_in_ring(lat, lon, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def distance_to_boundary(lat: float, lon: float) -> tuple[float, str, str]:
    """
    Returns (distance_km, segment_name, zone_type) of the nearest boundary
    feature to the given point.

    distance is 0.0 when inside a Polygon zone (MPA). For LineString IMBL,
    distance is perpendicular distance to the nearest segment.

    Validates coordinates — raises ValueError for out-of-range.
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Invalid coordinates: lat={lat} lon={lon}")
    nearest = float("inf")
    nearest_name = ""
    nearest_type = ""
    for feat in _features():
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        name = props.get("name", "?")
        ztype = props.get("zone_type", "?")
        if geom.get("type") == "Polygon":
            rings = geom.get("coordinates", [])
            if rings and _point_in_ring(lat, lon, rings[0]):
                return 0.0, name, ztype
            # outside polygon — distance to outer ring
            if rings and rings[0]:
                ring = rings[0]
                dist = min(
                    _dist_to_segment_km(lat, lon, ring[i], ring[(i + 1) % len(ring)])
                    for i in range(len(ring))
                )
                if dist < nearest:
                    nearest = dist
                    nearest_name = name
                    nearest_type = ztype
        elif geom.get("type") == "LineString":
            pts = geom.get("coordinates", [])
            if len(pts) >= 2:
                dist = min(
                    _dist_to_segment_km(lat, lon, pts[i], pts[i + 1])
                    for i in range(len(pts) - 1)
                )
                if dist < nearest:
                    nearest = dist
                    nearest_name = name
                    nearest_type = ztype
    if nearest == float("inf"):
        return 999.9, "UNKNOWN_BOUNDARY", "UNKNOWN"
    return round(float(nearest), 2), nearest_name, nearest_type


def get_boundary_info() -> dict:
    """Return boundary metadata for /sar/status and disclaimers."""
    feats = _features()
    # Extract bounding area for SAR scan defaults (around IMBL segments)
    # Compute centroid of all IMBL LineStrings
    imbl_lats, imbl_lons = [], []
    for feat in feats:
        if feat.get("properties", {}).get("zone_type") == "IMBL":
            geom = feat.get("geometry", {})
            if geom.get("type") == "LineString":
                for lon, lat in geom.get("coordinates", []):
                    imbl_lats.append(lat)
                    imbl_lons.append(lon)
    if imbl_lats and imbl_lons:
        centroid_lat = sum(imbl_lats) / len(imbl_lats)
        centroid_lon = sum(imbl_lons) / len(imbl_lons)
        bbox = [min(imbl_lons), min(imbl_lats), max(imbl_lons), max(imbl_lats)]
    else:
        centroid_lat, centroid_lon = 9.5, 79.5
        bbox = [78.0, 7.5, 80.5, 10.5]
    return {
        "feature_count": len(feats),
        "imbl_segments": sum(1 for f in feats if f.get("properties", {}).get("zone_type") == "IMBL"),
        "mpa_zones": sum(1 for f in feats if f.get("properties", {}).get("zone_type") == "MPA"),
        "centroid": {"lat": round(centroid_lat, 4), "lon": round(centroid_lon, 4)},
        "bbox": bbox,
        "is_demo": True,  # explicitly label as demo until authoritative geometry configured
        "disclaimer": "Simplified treaty-digitized boundaries — NOT FOR NAVIGATION. DEMO geometry.",
        "source_geojson": "data/marine_boundaries.geojson",
    }


def is_near_boundary(lat: float, lon: float, radius_km: float = 10.0) -> bool:
    """True if point is within radius_km of any maritime boundary."""
    dist, _, _ = distance_to_boundary(lat, lon)
    return dist <= radius_km
