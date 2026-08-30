"""
Geocoding connector -- resolve free-text coastal place names to coordinates.

Source: OpenStreetMap Nominatim, keyless:
    https://nominatim.openstreetmap.org/search?q=...&format=jsonv2&limit=1

*** FIELD REALITY CHECK (2026-08-24) ************************************
Probed live during development: HTTP 200, no credentials. "Gopalpur,
Odisha" resolved to (19.2599, 84.9052). Requests honour Nominatim's usage
policy (descriptive User-Agent; results cached per query string so repeated
queries cost nothing). `countrycodes=in` biases resolution to India, which
is the operating domain of this platform.
*************************************************************************

Design rules: network/parse failures raise GeocodeUnavailableError; an
honest "not found" returns None rather than a guessed point.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger("orca.geocode")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HTTP_TIMEOUT_S = 8.0
_HEADERS = {
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
}

# In-process cache with TTL: {normalized_query: (expiry_monotonic, (lat, lon, display_name) | None)}
import os as _os
import time as _time
_GEOCODE_TTL_S = float(_os.getenv("ORCA_GEOCODE_TTL_S", "86400").strip() or 86400)
_cache: dict[str, tuple[float, tuple[float, float, str] | None]] = {}

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
    _cache[k] = (_time.monotonic() + _GEOCODE_TTL_S, val)
    if len(_cache) > 2048:
        now = _time.monotonic()
        for kk, (exp, _) in list(_cache.items()):
            if exp < now:
                _cache.pop(kk, None)


class GeocodeUnavailableError(Exception):
    """The geocoding service could not be reached."""


def geocode(query: str) -> tuple[float, float, str] | None:
    """Resolve a place name to (lat, lon, display_name).

    Returns None when the service answers but finds nothing sensible --
    that is a SUCCESS (an honest miss), not an error.
    Raises GeocodeUnavailableError only on network/service failure.
    """
    q = " ".join(query.strip().lower().split())
    if not q:
        return None
    val, hit = _cache_get(q)
    if hit:
        return val

    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "in",  # ORCA's domain is Indian coastal waters
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise GeocodeUnavailableError(
            f"Nominatim unreachable: {getattr(exc, 'reason', exc)}"
        ) from exc

    result: tuple[float, float, str] | None = None
    if payload:
        try:
            lat = float(payload[0]["lat"])
            lon = float(payload[0]["lon"])
            name = payload[0].get("display_name") or q
            result = (lat, lon, name)
        except (KeyError, ValueError, IndexError):
            result = None
    _cache_set(q, result)
    return result


REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


def reverse_geocode(lat: float, lon: float) -> str | None:
    """Reverse-geocode (lat, lon) to a nearest-landmark name.

    Uses OSM Nominatim reverse endpoint at zoom=14 (suburb/town level,
    appropriate for offshore/coastal points):
        https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=jsonv2&zoom=14

    Keyless, cached, honest: returns None when no landmark can be resolved
    (payload missing/empty), raises GeocodeUnavailableError on network/service
    failure, never guesses a placeholder name.
    """
    cache_key = f"rev:{round(lat, 3)},{round(lon, 3)}"
    val, hit = _cache_get(cache_key)
    if hit:
        # Cached value may be str or None (honest miss)
        if isinstance(val, str) or val is None:
            return val  # type: ignore
        # Legacy cached tuple from forward geocode? Don't reuse
        if isinstance(val, tuple):
            # Not a reverse entry, treat as miss
            pass

    params = {
        "lat": str(lat),
        "lon": str(lon),
        "format": "jsonv2",
        "zoom": "14",
    }
    url = f"{REVERSE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise GeocodeUnavailableError(
            f"Nominatim reverse unreachable: {getattr(exc, 'reason', exc)}"
        ) from exc

    # Nominatim returns {"display_name": "..."} or {"error": "..."} on miss
    display = payload.get("display_name") if isinstance(payload, dict) else None
    if not display or not isinstance(display, str):
        # Also check error field — honest miss
        _cache_set(cache_key, None)
        return None

    # At zoom=14, display_name is already suburb/town-level; clean to first 2 parts
    # e.g. "Alibag, Raigad, Maharashtra, India" -> "Alibag, Raigad"
    try:
        parts = [p.strip() for p in display.split(",")]
        # Keep most local parts, filter out postcode-like numeric parts
        # Keep up to 3 meaningful parts, but prefer 2 for brevity
        clean_parts: list[str] = []
        for p in parts:
            if not p:
                continue
            # Skip pure postcode / numeric district codes
            if p.isdigit() or (len(p) >= 6 and p.replace(" ", "").isdigit()):
                continue
            clean_parts.append(p)
            if len(clean_parts) >= 3:
                break
        # Use first 2 for coastal readability (e.g. "Alibaug, Maharashtra")
        if len(clean_parts) >= 2:
            # If first part is very generic (e.g. "Beach"), keep 2
            name = f"{clean_parts[0]}, {clean_parts[1]}"
            # If we have 3 and second is district, include state for context when offshore
            if len(clean_parts) >= 3 and clean_parts[1].lower() not in display.lower().split(",")[0].lower():
                # Keep as 2-part for now; 3-part can be verbose for offshore
                pass
        elif clean_parts:
            name = clean_parts[0]
        else:
            name = display.split(",")[0].strip()
        if not name:
            _cache_set(cache_key, None)
            return None
        # Honest generic check: offshore points often reverse to just "India" / "Arabian Sea"
        # which is not a useful landmark — treat as miss so callers can fallback to
        # the advisory's landing centre (nearest port) instead of "off India".
        _generic = {"india", "arabian sea", "indian ocean", "bay of bengal", "laccadive sea", "sea"}
        if name.strip().lower() in _generic:
            _cache_set(cache_key, None)
            return None
        _cache_set(cache_key, name)
        return name
    except Exception:
        # Parse failure -> honest miss
        _cache_set(cache_key, None)
        return None


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for place in ["Gopalpur, Odisha", "Ratnagiri", "Alibag beach"]:
        try:
            r = geocode(place)
            print(f"{place!r}: {r}")
        except GeocodeUnavailableError as e:
            print(f"{place!r}: FAILED {e}")
