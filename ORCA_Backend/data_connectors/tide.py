"""
Tide connector -- REAL tide prediction from real gauge observations.

Source: University of Hawaii Sea Level Center (UHSLC) "Fast Delivery"
hourly tide-gauge dataset via their keyless ERDDAP server:
    https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_fast.csv

*** FIELD REALITY CHECK (2026-08-24) ************************************
Probed live during development: HTTP 200, no credentials. Verified Indian
stations in the dataset:
    153 Minicoy (8.117, 73.05)      157 Vishakhapatnam (17.683, 83.283)
    174 Cochin   (9.967, 76.267)    908 Port Blair (11.683, 92.767)
Fast Delivery lags real time by ~4-6 weeks (RQ data replaces it as it
ages), which is irrelevant for harmonic fitting: we fit on the most
recent ~45 days available and predict the requested hour.
*************************************************************************

Method (the PDF's own documented design -- Section 9 lists tide as
"Locally computed harmonic prediction model", Tier 2 Derived):
    1. fetch the nearest station's last N days of hourly sea level,
    2. least-squares fit amplitude+phase of the 8 dominant tidal
       constituents (+ mean sea level) in PURE PYTHON (normal equations,
       no numpy dependency),
    3. evaluate the fitted model at the requested UTC hour.

The returned level is metres relative to the station's mean sea level
over the fit window (i.e., tidal height above/below MSL) -- the quantity
that matters operationally (high/low water timing and range). Absolute
chart datum heights are out of scope.

Design rules (mirroring imd_live.py):
    - Network / data failures raise TideUnavailableError; the caller
      decides the fallback and must tag it honestly.
    - No station within _MAX_STATION_KM raises too (tides differ too much
      across basins -- a far-off gauge would be fake accuracy).
"""

from __future__ import annotations

import csv
import io
import logging
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("orca.tide")

ERDDAP_BASE = (
    "https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_fast.csv"
)
_HTTP_TIMEOUT_S = 20.0
_FIT_DAYS = 120          # max window of gauge data used for the harmonic fit
_MIN_SAMPLES = 14 * 24   # need >= ~2 weeks of hourly data for a stable fit
_MAX_STATION_KM = 400.0  # beyond this a gauge is not representative
# Fitted harmonic models are reused across queries: UHSLC Fast Delivery
# itself lags real time by weeks, so refitting every request buys nothing.
# TTL only guards against pathological staleness.
_MODEL_TTL_S = 6 * 3600
_model_cache: dict[int, tuple[float, datetime, list, float, int]] = {}

_HEADERS = {"User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)"}

# Station registry -- verified live via ERDDAP distinct() probe 2026-08-24.
UHSLC_INDIA_STATIONS = {
    "minicoy":     {"uhslc_id": 153, "name": "Minicoy Island",     "lat": 8.117,  "lon": 73.05},
    "vishakhapatnam": {"uhslc_id": 157, "name": "Vishakhapatnam", "lat": 17.683, "lon": 83.283},
    "cochin":      {"uhslc_id": 174, "name": "Kochi (Cochin)",    "lat": 9.967,  "lon": 76.267},
    "port_blair":  {"uhslc_id": 908, "name": "Port Blair",        "lat": 11.683, "lon": 92.767},
}

# Principal tidal constituent speeds, degrees per hour (Doodson numbers).
_CONSTITUENTS = [
    ("M2", 28.9841042),
    ("S2", 30.0000000),
    ("N2", 28.4397295),
    ("K2", 30.0821373),
    ("K1", 15.0410686),
    ("O1", 13.9430356),
    ("P1", 14.9589314),
    ("Q1", 13.3986609),
]


class TideUnavailableError(Exception):
    """No usable gauge near the location, or the UHSLC feed failed."""


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_station(lat: float, lon: float) -> tuple[str, dict, float]:
    """(key, station, distance_km) of closest registered gauge."""
    best_key, best_dist = None, float("inf")
    for key, st in UHSLC_INDIA_STATIONS.items():
        d = _haversine_km(lat, lon, st["lat"], st["lon"])
        if d < best_dist:
            best_key, best_dist = key, d
    if best_key is None or best_dist > _MAX_STATION_KM:
        raise TideUnavailableError(
            f"no UHSLC tide gauge within {_MAX_STATION_KM:.0f} km "
            f"(nearest {best_dist:.0f} km) -- refusing to extrapolate tides"
        )
    st = dict(UHSLC_INDIA_STATIONS[best_key])
    st["distance_km"] = round(best_dist, 1)
    return best_key, st, best_dist


def _erddap_get(query: str) -> str:
    url = f"{ERDDAP_BASE}?{query}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise TideUnavailableError(
            f"UHSLC feed unreachable: {getattr(exc, 'reason', exc)}"
        ) from exc


def _erddap_rows(raw: str) -> list[dict]:
    """ERDDAP CSVs carry a units line under the header:
        time,sea_level
        UTC,millimeters
        2026-06-30T23:00:00Z,83
    Skip the units line so DictReader sees only real data rows.
    """
    lines = raw.splitlines()
    return list(csv.DictReader(io.StringIO("\n".join(lines[:1] + lines[2:]))))


def _fetch_levels(uhslc_id: int) -> list[tuple[datetime, float]]:
    """Hourly (utc_datetime, metres) samples over the station's last
    available record window (up to _FIT_DAYS).

    UHSLC Fast Delivery lags real time by weeks (observed 2026-08-24:
    coverage ended 2026-06-30), and some stations are gappy. This does NOT
    hurt prediction quality -- tidal motion is driven by deterministic
    lunar/solar astronomy, so a least-squares harmonic fit on recent
    observations extrapolates forward exactly the way published annual
    tide tables do.
    """
    # Step 1: latest timestamp actually present for this station
    # (orderByMax collapses the table to its newest row -- cheap).
    raw = _erddap_get(
        f"time&uhslc_id={int(uhslc_id)}"
        f"&orderByMax({urllib.parse.quote('\"time\"', safe='()\"')})"
    )
    rows = _erddap_rows(raw)
    if not rows or not rows[0].get("time"):
        raise TideUnavailableError("UHSLC returned no coverage info")
    try:
        end = datetime.fromisoformat(rows[0]["time"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise TideUnavailableError(f"UHSLC bad coverage date: {exc}") from exc

    start = end - timedelta(days=_FIT_DAYS)
    raw = _erddap_get(
        f"time,sea_level&uhslc_id={int(uhslc_id)}"
        f"&time>={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )

    samples: list[tuple[datetime, float]] = []
    for row in _erddap_rows(raw):
        try:
            t = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            mm = float(row["sea_level"])
        except (KeyError, ValueError):
            continue
        if mm <= -32000:  # ERDDAP fill value (-32767)
            continue
        samples.append((t, mm / 1000.0))
    if len(samples) < _MIN_SAMPLES:
        raise TideUnavailableError(
            f"only {len(samples)} usable hourly samples from UHSLC -- too few to fit"
        )
    return samples


# ---------------------------------------------------------------------------
# Pure-Python linear algebra (no numpy): normal equations + Gaussian elim.
# ---------------------------------------------------------------------------

def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise TideUnavailableError("singular harmonic design matrix")
        M[col], M[pivot] = M[pivot], M[col]
        pv = M[col][col]
        for r in range(n):
            if r != col and M[r][col]:
                f = M[r][col] / pv
                for c in range(col, n + 1):
                    M[r][c] -= f * M[col][c]
    return [M[i][n] / M[i][i] for i in range(n)]


def _get_model(
    uhslc_id: int,
) -> tuple[datetime, list, float, int]:
    """Fitted harmonic model for one station, cached across queries.

    Returns (t0, coeffs, rms, n_samples). Downloads + fits only on a miss;
    both predict_* entry points share this so the year-scale CSV download
    and the pure-Python least-squares run at most once per TTL window.
    """
    now = time.monotonic()
    hit = _model_cache.get(uhslc_id)
    if hit is not None and now - hit[0] < _MODEL_TTL_S:
        return hit[1], hit[2], hit[3], hit[4]
    samples = _fetch_levels(uhslc_id)
    coeffs, rms = _fit_harmonic_predictor(samples)
    _model_cache[uhslc_id] = (now, samples[0][0], coeffs, rms, len(samples))
    return samples[0][0], coeffs, rms, len(samples)


def predict_level_m(
    lat: float, lon: float, when_utc: datetime | None = None
) -> dict:
    """Predicted tide height (m rel. MSL) at `when_utc` from the nearest
    gauge with a usable record. Stations are tried nearest-first; the first
    one yielding enough recent data wins.

    Returns:
        {
            "level_m": float,           # predicted height vs local mean sea level
            "station_name": str,
            "station_distance_km": float,
            "fit_rms_m": float,         # residual RMS of the harmonic fit
            "samples_used": int,
            "predicted_for_utc": str,
        }
    Raises TideUnavailableError when nothing trustworthy exists.
    """
    when_utc = when_utc or datetime.now(timezone.utc)

    ranked = sorted(
        UHSLC_INDIA_STATIONS.items(),
        key=lambda kv: _haversine_km(lat, lon, kv[1]["lat"], kv[1]["lon"]),
    )
    errors: list[str] = []
    for _, st in ranked:
        dist = _haversine_km(lat, lon, st["lat"], st["lon"])
        if dist > _MAX_STATION_KM:
            continue
        try:
            t0, coeffs, rms, n_samples = _get_model(st["uhslc_id"])
        except TideUnavailableError as exc:
            errors.append(f'{st["name"]}: {exc}')
            continue

        h = (when_utc - t0).total_seconds() / 3600.0
        level = coeffs[0]
        i = 1
        for _, w in _CONSTITUENTS:
            ph = math.radians(w * h)
            level += coeffs[i] * math.cos(ph) + coeffs[i + 1] * math.sin(ph)
            i += 2

        return {
            "level_m": round(level, 3),
            "station_name": st["name"],
            "station_distance_km": round(dist, 1),
            "fit_rms_m": round(rms, 3),
            "samples_used": n_samples,
            "predicted_for_utc": when_utc.isoformat(timespec="seconds"),
        }

    raise TideUnavailableError(
        "no usable tide gauge within "
        f"{_MAX_STATION_KM:.0f} km ({'; '.join(errors) or 'none in range'})"
    )


def predict_highs_lows(
    lat: float,
    lon: float,
    when_utc: datetime | None = None,
    hours_after: int = 24,
    utc_offset_seconds: int = 19800,
) -> dict:
    """Next high/low tide events + daily range around `when_utc`.

    Evaluates the fitted harmonic model every 10 minutes over a window of
    [-6 h, +hours_after] around the target, then picks local extrema
    (P1 #14). Times come back as LOCAL ISO wall-clock at the given offset so
    answers can say 'high tide at 14:20' without the user converting.

    Returns:
        {
            "extremes": [{"kind": "high"|"low", "time_local": ISO,
                          "height_m": float}],
            "daily_range_m": float,     # max - min over the window
            "station_name": str,
            "station_distance_km": float,
            "fit_rms_m": float,
        }
    """
    when_utc = when_utc or datetime.now(timezone.utc)

    ranked = sorted(
        UHSLC_INDIA_STATIONS.items(),
        key=lambda kv: _haversine_km(lat, lon, kv[1]["lat"], kv[1]["lon"]),
    )
    errors: list[str] = []
    for _, st in ranked:
        dist = _haversine_km(lat, lon, st["lat"], st["lon"])
        if dist > _MAX_STATION_KM:
            continue
        try:
            t0, coeffs, rms, _ = _get_model(st["uhslc_id"])
        except TideUnavailableError as exc:
            errors.append(f'{st["name"]}: {exc}')
            continue

        def level_at(t: datetime) -> float:
            h = (t - t0).total_seconds() / 3600.0
            lvl = coeffs[0]
            i = 1
            for _, w in _CONSTITUENTS:
                ph = math.radians(w * h)
                lvl += coeffs[i] * math.cos(ph) + coeffs[i + 1] * math.sin(ph)
                i += 2
            return lvl

        # Sample every 10 minutes across the window.
        start = when_utc - timedelta(hours=6)
        series: list[tuple[datetime, float]] = []
        step = timedelta(minutes=10)
        t = start
        while t <= when_utc + timedelta(hours=hours_after):
            series.append((t, level_at(t)))
            t += step

        # Local extrema: strictly greater/smaller than both neighbours.
        extremes: list[dict] = []
        for k in range(1, len(series) - 1):
            pt, pv = series[k]
            _, prev_v = series[k - 1]
            _, next_v = series[k + 1]
            if pv >= prev_v and pv >= next_v and (pv > prev_v or pv > next_v):
                kind = "high"
            elif pv <= prev_v and pv <= next_v and (pv < prev_v or pv < next_v):
                kind = "low"
            else:
                continue
            local_t = (pt + timedelta(seconds=utc_offset_seconds))
            extremes.append({
                "kind": kind,
                "time_local": local_t.replace(tzinfo=None).isoformat(timespec="minutes"),
                "height_m": round(pv, 2),
            })

        values = [v for _, v in series]
        return {
            "extremes": extremes,
            "daily_range_m": round(max(values) - min(values), 2),
            "station_name": st["name"],
            "station_distance_km": round(dist, 1),
            "fit_rms_m": round(rms, 3),
        }

    raise TideUnavailableError(
        "no usable tide gauge within "
        f"{_MAX_STATION_KM:.0f} km ({'; '.join(errors) or 'none in range'})"
    )


def _fit_harmonic_predictor(samples):
    """Fit returning coefficients aligned with _CONSTITUENTS order.

    Same math as _fit_harmonics but self-contained so predict_level_m has a
    single clean entry point.
    """
    t0 = samples[0][0]

    def basis_at(h: float) -> list[float]:
        row = [1.0]
        for _, w in _CONSTITUENTS:
            ph = math.radians(w * h)
            row.append(math.cos(ph))
            row.append(math.sin(ph))
        return row

    n_col = 1 + 2 * len(_CONSTITUENTS)
    A = [[0.0] * n_col for _ in range(n_col)]
    bv = [0.0] * n_col
    for t, v in samples:
        h = (t - t0).total_seconds() / 3600.0
        basis = basis_at(h)
        for i in range(n_col):
            bv[i] += basis[i] * v
            for j in range(i, n_col):
                A[i][j] += basis[i] * basis[j]
    for i in range(n_col):
        for j in range(i):
            A[i][j] = A[j][i]

    coeffs = _solve(A, bv)

    sse = 0.0
    for t, v in samples:
        h = (t - t0).total_seconds() / 3600.0
        pred = sum(c * x for c, x in zip(coeffs, basis_at(h)))
        sse += (pred - v) ** 2
    rms = math.sqrt(sse / max(len(samples), 1))
    return coeffs, rms


if __name__ == "__main__":
    # Manual probe: python -m data_connectors.tide  (Kochi offshore point)
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import json

    print(json.dumps(predict_level_m(9.93, 76.30), indent=2))  # near Kochi

