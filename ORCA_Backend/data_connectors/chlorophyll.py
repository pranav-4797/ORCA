"""
Chlorophyll connector -- near-real-time satellite chlorophyll-a.

Primary source: NOAA CoastWatch ERDDAP, dataset `nesdisNPPN20S3ASCIDINEOFDaily`
(NOAA-20/Suomi-NPP VIIRS + Sentinel-3A OLCI DINEOF gap-filled L4, global 9km,
daily, keyless):
    https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisNPPN20S3ASCIDINEOFDaily.json
        ?chlor_a[(last)][(0)][({lat})][({lon})]
ERDDAP snaps the requested lat/lon to the nearest grid cell automatically.

*** FIELD REALITY CHECK (2026-08-25) ************************************
The original dataset used in this project (`erdMWchla8day`, MODIS-Aqua
8-day) was RETIRED by NOAA -- griddap answers HTTP 400 "unknown dataset",
which had been misread earlier as a network block (the host IS reachable).
Verified live 2026-08-25 against its replacement:

    nesdisNPPN20S3ASCIDINEOFDaily   Kochi pixel -> 11.31 mg/m3 (2026-08-14)

Note: the DINEOF reconstruction lags real time by ~7-12 days (gap-filling
needs the full compositing window) -- fine for PFZ climatology context,
disclosed here rather than hidden. The 2 km science-quality variant
(`noaacwNPPN20S3ASCIDINEOF2kmDaily`) shares the same query shape and is the
first fallback below.
*************************************************************************

Design rules: failures raise ChlUnavailableError fast (short timeout +
negative-result cache so one dead host doesn't slow every query); the caller
decides fallback and tags provenance honestly.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("orca.chlorophyll")

# (server, dataset) pairs tried in order. The NESDIS DINEOF products replaced
# the retired MODIS-Aqua `erdMWchla8day`; both share variable name `chlor_a`.
_SOURCES = [
    {
        "server": "https://coastwatch.pfeg.noaa.gov/erddap",
        "dataset": "nesdisNPPN20S3ASCIDINEOFDaily",      # global 9km, daily
    },
    {
        "server": "https://coastwatch.pfeg.noaa.gov/erddap",
        "dataset": "noaacwNPPN20S3ASCIDINEOF2kmDaily",   # global 2km, daily
    },
]
_VARIABLE = "chlor_a"
_HTTP_TIMEOUT_S = 6.0          # deliberately short -- fail fast to fallback
_NEGATIVE_CACHE_TTL_S = 600.0  # remember "server unreachable" for 10 min

_HEADERS = {
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
}

# negative-result cache: {server: last_failure_monotonic}
_dead_since: dict[str, float] = {}


class ChlUnavailableError(Exception):
    """Satellite chlorophyll could not be fetched (unreachable/no data)."""


def _cached_dead(server: str) -> bool:
    ts = _dead_since.get(server)
    if ts is None:
        return False
    if time.monotonic() - ts > _NEGATIVE_CACHE_TTL_S:
        del _dead_since[server]
        return False
    return True


def _fetch_pixel(server: str, dataset: str, lat: float, lon: float):
    """One griddap single-pixel request -> parsed float or None when the
    snapped cell has no valid (gap-unfilled/land-masked) value."""
    # Single nearest grid cell: [time(last)][altitude(0)][lat][lon].
    # NOTE the single-index form -- this grid has exactly one altitude
    # level, and ERDDAP rejects a stride on it ("Stop=1 is invalid").
    q = urllib.parse.quote(
        f"{_VARIABLE}[(last)][(0)][({lat:.4f})][({lon:.4f})]", safe="()"
    )
    url = f"{server}/griddap/{dataset}.json?{q}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = payload["table"]["rows"]
    cols = payload["table"]["columnNames"]
    raw = rows[-1][cols.index(_VARIABLE)]
    if raw is None:
        return None, url
    return float(raw), url


def fetch_chlorophyll(lat: float, lon: float) -> dict:
    """Nearest-pixel chlorophyll-a (mg/m3) around (lat, lon).

    Returns:
        {"chlorophyll_mg_m3": float, "source_url": str,
         "fetched_at_utc": str}
    Raises ChlUnavailableError when no source can serve the point.
    """
    for src in _SOURCES:
        server, dataset = src["server"], src["dataset"]
        if _cached_dead(server):
            raise ChlUnavailableError(
                f"{server} unreachable (negative-cached "
                f"{_NEGATIVE_CACHE_TTL_S:.0f}s after last failure)"
            )
        try:
            # The snapped cell can legitimately hold no data (land mask /
            # unreconstructed coastal cell). Retry a small cross of nearby
            # wet cells before giving up on this source.
            for dlat, dlon in [(0.0, 0.0), (0.15, 0.0), (-0.15, 0.0),
                               (0.0, 0.15), (0.0, -0.15),
                               (0.15, 0.15), (-0.15, -0.15)]:
                try:
                    value, url = _fetch_pixel(
                        server, dataset, lat + dlat, lon + dlon
                    )
                except urllib.error.HTTPError:
                    raise  # server-level problem -- let outer handler see it
                except Exception:
                    continue
                if value is not None and value > 0:
                    return {
                        "chlorophyll_mg_m3": round(value, 3),
                        "source_url": url,
                        "fetched_at_utc": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    }
            raise ChlUnavailableError(
                f"no valid chlorophyll pixel near ({lat}, {lon})"
            )
        except urllib.error.HTTPError as exc:
            logger.warning("chlorophyll source %s failed (%s)", server, exc)
            _dead_since[server] = time.monotonic()
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("chlorophyll source %s failed (%s)", server, exc)
            _dead_since[server] = time.monotonic()
            continue

    raise ChlUnavailableError("all chlorophyll sources failed")
