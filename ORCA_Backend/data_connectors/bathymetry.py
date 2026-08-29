"""
Bathymetry connector -- real sea-floor depth for safe-route planning.

Source: GEBCO/INCOIS bathymetry-derived bathymetry (keyless griddap).
Original ETOPO1 data was publicly available; this implementation uses
a GEBCO-derived grid for ORCA v1 compliance.

Design rules: failures raise BathymetryUnavailableError fast (short timeout
+ negative cache); callers must disclose the data source.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("orca.bathymetry")

# INCOIS/GEBCO bathymetry-derived griddap endpoint (keyless)
_SERVER = "https://erddap.incois.gov.in/erddap/griddap/gebco_gridded_2023"
_DATASET = "gebco_2023"
_VARIABLE = "altitude"
_HTTP_TIMEOUT_S = 6.0
_NEGATIVE_CACHE_TTL_S = 600.0

_HEADERS = {
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
}

_dead_since: float | None = None


class BathymetryUnavailableError(Exception):
    """Depth could not be fetched for the requested point."""


def _cached_dead() -> bool:
    global _dead_since
    if _dead_since is None:
        return False
    if time.monotonic() - _dead_since > _NEGATIVE_CACHE_TTL_S:
        _dead_since = None
        return False
    return True


def get_depth_m(lat: float, lon: float) -> float:
    """Sea-floor elevation (m; negative = depth below sea level).

    Raises BathymetryUnavailableError when the feed cannot serve the point.
    """
    global _dead_since
    if _cached_dead():
        raise BathymetryUnavailableError(
            f"bathymetry source negative-cached "
            f"{_NEGATIVE_CACHE_TTL_S:.0f}s after last failure"
        )
    q = urllib.parse.quote(f"{_VARIABLE}[({lat:.4f})][({lon:.4f})]", safe="()")
    url = f"{_SERVER}/griddap/{_DATASET}.json?{q}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        _dead_since = time.monotonic()
        raise BathymetryUnavailableError(f"ETOPO feed failed: {exc}") from exc
    try:
        rows = payload["table"]["rows"]
        cols = payload["table"]["columnNames"]
        value = float(rows[-1][cols.index(_VARIABLE)])
    except (KeyError, ValueError, IndexError) as exc:
        raise BathymetryUnavailableError(f"unexpected ERDDAP payload: {exc}") from exc
    return value


def get_depths_batch(points: list[tuple[float, float]]) -> dict[tuple[float, float], float]:
    """Depths for many points via ONE bounding-box griddap request.

    Returns {rounded(lat,4), rounded(lon,4)} -> depth for every REQUESTED
    point that had data (values snapped to the ETOPO grid). Raises
    BathymetryUnavailableError if the bulk fetch fails entirely.
    """
    global _dead_since
    if not points:
        return {}
    if _cached_dead():
        raise BathymetryUnavailableError("bathymetry source negative-cached")

    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    pad = 0.05
    la_min, la_max = min(lats) - pad, max(lats) + pad
    lo_min, lo_max = min(lons) - pad, max(lons) + pad

    expr = (
        f"{_VARIABLE}[({la_min:.4f}):({la_max:.4f})]"
        f"[({lo_min:.4f}):({lo_max:.4f})]"
    )
    q = urllib.parse.quote(expr, safe="()")
    url = f"{_SERVER}/griddap/{_DATASET}.csv?{q}"

    raw = None
    last_exc: Exception | None = None
    for attempt in range(1):
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            last_exc = exc
    if raw is None:
        _dead_since = time.monotonic()
        raise BathymetryUnavailableError(f"ETOPO bulk feed failed: {last_exc}")

    import csv as _csv
    import io as _io

    lines = raw.splitlines()
    # ERDDAP CSVs carry a units row under the header.
    reader = _csv.DictReader(_io.StringIO("\n".join(lines[:1] + lines[2:])))
    grid: dict[tuple[float, float], float] = {}
    for row in reader:
        try:
            la = round(float(row["latitude"]), 4)
            lo = round(float(row["longitude"]), 4)
            v = float(row[_VARIABLE])
        except (KeyError, ValueError, TypeError):
            continue
        grid[(la, lo)] = v

    # Snap each requested point to its nearest grid cell.
    out: dict[tuple[float, float], float] = {}
    if grid:
        # ETOPO180 is a REGULAR lat/lon grid: both axes step exactly
        # 1 arc-minute of degrees (no cosine scaling -- that's distance,
        # not grid geometry).
        step_lat = step_lon = 1.0 / 60.0
        for la, lo in points:
            key = (round(round(la / step_lat) * step_lat, 4),
                   round(round(lo / step_lon) * step_lon, 4))
            if key in grid:
                out[(round(la, 4), round(lo, 4))] = grid[key]
            else:
                # nearest-key fallback within one cell
                best = min(
                    grid.keys(),
                    key=lambda k: abs(k[0] - la) + abs(k[1] - lo),
                    default=None,
                )
                if best is not None and \
                        abs(best[0] - la) <= step_lat and \
                        abs(best[1] - lo) <= step_lon:
                    out[(round(la, 4), round(lo, 4))] = grid[best]
    return out


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for name, la, lo in [
        ("Ratnagiri offshore", 17.15, 73.10),
        ("Odisha offshore", 19.90, 85.60),
        ("Inland Pune (+)", 18.52, 73.86),
    ]:
        print(f"{name}: {get_depth_m(la, lo)} m")
