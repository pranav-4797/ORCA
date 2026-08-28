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

# In-process cache: {normalized_query: (lat, lon, display_name) | None}
_cache: dict[str, tuple[float, float, str] | None] = {}


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
    if q in _cache:
        return _cache[q]

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
    _cache[q] = result
    return result


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
