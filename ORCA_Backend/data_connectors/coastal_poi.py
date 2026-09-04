"""
Coastal POI connector -- fetch live points of interest (beaches, lighthouses, etc.)
via the Overpass API (OpenStreetMap).

Source: Overpass API, keyless:
    https://overpass-api.de/api/interpreter

Design rules: network/parse failures raise CoastalPoiUnavailableError;
honest "not found" returns an empty list.
"""

from __future__ import annotations
import json
import logging
import urllib.parse
import urllib.request
import os as _os
import time as _time

logger = logging.getLogger("orca.coastal_poi")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_HTTP_TIMEOUT_S = 15.0
_HEADERS = {
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
}

# In-process cache with TTL: {bbox_key: (expiry_monotonic, list[dict])}
_COASTAL_POI_TTL_S = float(_os.getenv("ORCA_POI_TTL_S", "3600").strip() or 3600)
_cache: dict[str, tuple[float, list[dict]]] = {}

def _cache_get(k: str):
    hit = _cache.get(k)
    if hit is None:
        return None, False
    exp, val = hit
    if _time.monotonic() > exp:
        _cache.pop(k, None)
        return None, False
    return val, True

def _cache_set(k: str, val):
    _cache[k] = (_time.monotonic() + _COASTAL_POI_TTL_S, val)
    if len(_cache) > 1024:
        now = _time.monotonic()
        for kk, (exp, _) in list(_cache.items()):
            if exp < now:
                _cache.pop(kk, None)

class CoastalPoiUnavailableError(Exception):
    """The Overpass API service could not be reached."""

def get_coastal_pois(lat: float, lon: float, radius_km: float = 10.0) -> list[dict]:
    """Fetch nearby coastal POIs within a bounding box around (lat, lon).

    Tags queried: tourism=beach|viewpoint, natural=beach, man_made=lighthouse, harbour=yes.
    Returns a list of {name, type, lat, lon}.
    """
    # Calculate bounding box (approx 1 deg ~ 111km)
    delta = radius_km / 111.0
    south, north = lat - delta, lat + delta
    west, east = lon - delta, lon + delta

    bbox = f"{south},{north},{west},{east}"
    cache_key = f"poi:{round(lat, 3)},{round(lon, 3)},{radius_km}"

    val, hit = _cache_get(cache_key)
    if hit:
        return val or []

    # Overpass Query
    query = (
        f'[out:json][timeout:25];'
        f'( '
        f'node["tourism"~"beach|viewpoint"]({bbox});'
        f'way["tourism"~"beach|viewpoint"]({bbox});'
        f'relation["tourism"~"beach|viewpoint"]({bbox});'
        f'node["natural"="beach"]({bbox});'
        f'way["natural"="beach"]({bbox});'
        f'relation["natural"="beach"]({bbox});'
        f'node["man_made"="lighthouse"]({bbox});'
        f'way["man_made"="lighthouse"]({bbox});'
        f'relation["man_made"="lighthouse"]({bbox});'
        f'node["harbour"="yes"]({bbox});'
        f'way["harbour"="yes"]({bbox});'
        f'relation["harbour"="yes"]({bbox});'
        f');'
        f'out center;'
    )

    params = {"data": query}
    url = f"{OVERPASS_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise CoastalPoiUnavailableError(
            f"Overpass API unreachable: {getattr(exc, 'reason', exc)}"
        ) from exc

    pois: list[dict] = []
    elements = payload.get("elements", [])

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("description") or "Unnamed POI"

        # Determine Type
        poi_type = "POI"
        if "beach" in tags.get("tourism", "").lower() or tags.get("natural") == "beach":
            poi_type = "Beach"
        elif tags.get("man_made") == "lighthouse":
            poi_type = "Lighthouse"
        elif tags.get("harbour") == "yes":
            poi_type = "Harbour"
        elif "viewpoint" in tags.get("tourism", "").lower():
            poi_type = "Viewpoint"

        # Coordinates
        if el["type"] == "node":
            lat_val, lon_val = el["lat"], el["lon"]
        elif el["type"] in ("way", "relation"):
            # For ways/relations, use the center of the first coordinate as a proxy
            # (Simplification for markers)
            center = el.get("center")
            if center:
                lat_val, lon_val = center["lat"], center["lon"]
            else:
                # Fallback to first member node's coords if available (Overpass 'out center' is better)
                # but since we used 'out body', we don't have centers.
                # I should use 'out center' for non-nodes.
                continue
        else:
            continue

        pois.append({
            "name": name,
            "type": poi_type,
            "lat": float(lat_val),
            "lon": float(lon_val),
        })

    _cache_set(cache_key, pois)
    return pois

if __name__ == "__main__":
    # Quick test: Goa region
    try:
        res = get_coastal_pois(15.49, 73.82)
        print(f"Found {len(res)} POIs: {res}")
    except Exception as e:
        print(f"Error: {e}")
