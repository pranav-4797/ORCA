"""
Heatmap scan — which regions show high chlorophyll + favourable SST.

Answers the PS query: "Which regions show high chlorophyll concentration and
favourable sea surface temperature?" by sampling a grid around the reference
point via the same INCOIS live pipeline used by OceanStateAgent (incois_marine).

Design:
- Grid sampling (not ring): radius_km around centre, step_km resolution.
- Each grid point: get_marine_snapshot (SST + CHL) via ThreadPool, cached 10 min.
- Filter: SST in [favourable_min, favourable_max] (default 26-29 C, typical PFZ
  favourable range) AND CHL >= chl_min (default 0.7 mg/m3, high productivity).
- Never fabricates: unavailable fields are skipped, not hidden.
- Concurrency capped at 8 workers (same as PFZ ring) to avoid overwhelming
  INCOIS THREDDS (each point = 6 WMS fetches).
- Short TTL cache per centre/radius/step/thresholds to keep demo snappy.
"""

from __future__ import annotations

import math
import time
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import data_connectors.incois_marine as incois_marine

logger = logging.getLogger("orca.heatmap")

_HEATMAP_TTL_S = 120  # 2 min — same as OceanState TTL
_heatmap_cache: dict[tuple, tuple[float, dict]] = {}

# Favourable SST range for fish productivity (PFZ proxy): 26-29 C is warm but not
# too warm, chlorophyll >0.7 indicates high productivity (typical INCOIS PFZ
# guidance uses >0.5-1.0 mg/m3 as productive).
DEFAULT_SST_MIN = 26.0
DEFAULT_SST_MAX = 29.0
DEFAULT_CHL_MIN = 0.7


def _grid_points(center_lat: float, center_lon: float, radius_km: float, step_km: float):
    """Generate (lat, lon) grid points within radius_km of centre, step_km spacing."""
    # Approx degrees per km
    dlat_step = step_km / 111.0
    # Longitude degrees per km depends on latitude
    cos_lat = max(math.cos(math.radians(center_lat)), 0.2)
    dlon_step = step_km / (111.0 * cos_lat)
    # Number of steps in each direction
    lat_steps = max(1, int(radius_km / step_km))
    lon_steps = max(1, int(radius_km / step_km))
    points = []
    for di in range(-lat_steps, lat_steps + 1):
        for dj in range(-lon_steps, lon_steps + 1):
            lat = center_lat + di * dlat_step
            lon = center_lon + dj * dlon_step
            # Rough circular filter
            dist_km = math.hypot(di * step_km, dj * step_km)
            if dist_km <= radius_km + 1e-6:
                points.append((round(lat, 4), round(lon, 4)))
    return points


def scan_heatmap(
    center_lat: float,
    center_lon: float,
    radius_km: float = 50.0,
    step_km: float = 12.0,
    sst_min: float = DEFAULT_SST_MIN,
    sst_max: float = DEFAULT_SST_MAX,
    chl_min: float = DEFAULT_CHL_MIN,
    max_points: int = 80,
) -> dict:
    """
    Scan grid around centre, return GeoJSON-ready product + stats.

    Returns dict:
      {
        "centre": [lat, lon],
        "radius_km": ...,
        "step_km": ...,
        "thresholds": {"sst_min": ..., "sst_max": ..., "chl_min": ...},
        "scanned": int,
        "hits": [{"lat": ..., "lon": ..., "sst": ..., "chl": ...}, ...],
        "scanned_at": ISO8601,
        "provenance": "INCOIS THREDDS SST + ERDDAP CHL (live) — per-point field_sources"
      }
    """
    radius_km = max(10.0, min(float(radius_km), 120.0))
    step_km = max(5.0, min(float(step_km), 25.0))
    sst_min = float(sst_min)
    sst_max = float(sst_max)
    chl_min = float(chl_min)

    cache_key = (round(center_lat, 2), round(center_lon, 2), round(radius_km, 1), round(step_km, 1), round(sst_min, 1), round(sst_max, 1), round(chl_min, 2))
    hit = _heatmap_cache.get(cache_key)
    if hit is not None and time.monotonic() - hit[0] < _HEATMAP_TTL_S:
        return hit[1]

    points = _grid_points(center_lat, center_lon, radius_km, step_km)
    # Cap to avoid hammering INCOIS
    if len(points) > max_points:
        # Subsample uniformly
        step = len(points) / max_points
        points = [points[int(i * step)] for i in range(max_points)]

    ft = datetime.now(timezone.utc)
    results: list[dict] = []
    scanned = 0

    def fetch_one(pt):
        lat, lon = pt
        try:
            snap = incois_marine.get_marine_snapshot(lat, lon, ft)
            sst = snap.get("sst")
            chl = snap.get("chlorophyll")
            # Validate ranges (same as incois_marine._validate)
            if sst is not None and not (20 <= float(sst) <= 35):
                sst = None
            if chl is not None and not (0 <= float(chl) <= 50):
                chl = None
            return {"lat": lat, "lon": lon, "sst": sst, "chl": chl, "snap": snap}
        except Exception as exc:
            logger.debug("heatmap fetch failed for %.4f,%.4f: %s", lat, lon, exc)
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fetch_one, pt): pt for pt in points}
        for f in as_completed(futs):
            r = f.result()
            if r is None:
                continue
            scanned += 1
            sst = r["sst"]
            chl = r["chl"]
            if sst is None or chl is None:
                continue
            try:
                sst_f = float(sst)
                chl_f = float(chl)
            except (TypeError, ValueError):
                continue
            if sst_min <= sst_f <= sst_max and chl_f >= chl_min:
                results.append({
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "sst": round(sst_f, 2),
                    "chl": round(chl_f, 3),
                })

    # Sort hits by chlorophyll descending (most productive first), then SST closeness to 27.5
    results.sort(key=lambda h: (-h["chl"], abs(h["sst"] - 27.5)))

    payload = {
        "centre": [round(center_lat, 4), round(center_lon, 4)],
        "radius_km": radius_km,
        "step_km": step_km,
        "thresholds": {"sst_min": sst_min, "sst_max": sst_max, "chl_min": chl_min},
        "scanned": scanned,
        "total_grid": len(points),
        "hits": results[:20],  # top 20
        "hits_count": len(results),
        "scanned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provenance": "INCOIS THREDDS SST + ERDDAP OceanSat-2 CHL (live, per-point) — unavailable fields skipped, never simulated",
    }
    _heatmap_cache[cache_key] = (time.monotonic(), payload)
    return payload


def hits_to_geojson(scan_result: dict) -> dict:
    """Convert scan_result hits to GeoJSON FeatureCollection for map overlay."""
    features = []
    for h in scan_result.get("hits", []):
        features.append({
            "type": "Feature",
            "properties": {
                "kind": "heatmap_hit",
                "sst_celsius": h["sst"],
                "chlorophyll_mg_m3": h["chl"],
            },
            "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
        })
    # Add centre
    centre = scan_result.get("centre")
    if centre:
        features.append({
            "type": "Feature",
            "properties": {"kind": "heatmap_centre"},
            "geometry": {"type": "Point", "coordinates": [centre[1], centre[0]]},
        })
    return {
        "type": "FeatureCollection",
        "scanned": scan_result.get("scanned"),
        "hits_count": scan_result.get("hits_count"),
        "thresholds": scan_result.get("thresholds"),
        "features": features,
    }
