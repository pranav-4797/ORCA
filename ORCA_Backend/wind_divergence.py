"""
Satellite-Model Wind Divergence Flag -- ORCA Innovation #4.

    forecast wind (Open-Meteo, existing OceanStateAgent)
            +
    satellite-observed wind (data_connectors/satellite_wind.py)
            v
    divergence analysis  ->  MATCH / MODERATE_DIVERGENCE / HIGH_DIVERGENCE
            v
    confidence penalty + explainable warning (never overrides safety rules)

Design mirrors fleet_convergence.py: one small self-contained engine, env-
configurable thresholds (no magic numbers), a TTL cache so satellite
lookups never add latency to a normal query, and a status field that keeps
real and simulated observations honestly labelled and never blended.

LATENCY: satellite passes are infrequent (a scatterometer revisits a given
point roughly 1-2x/day), so the observation cache TTL is long relative to
the ocean-forecast cache. A cache miss on the (currently unactivated) real
provider is a same-process env-var check -- effectively free -- so normal
queries are never held up waiting on a network call to a satellite source.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from data_connectors.satellite_wind import DemoSatelliteWindProvider, MosdacScatWindConnector
from models import (
    DivergenceStatus,
    Location,
    WindDivergenceResult,
    WindObservation,
    WindObsStatus,
)

# ---------------------------------------------------------------------------
# Configurable thresholds -- no magic numbers.
# ---------------------------------------------------------------------------
MODERATE_ABS_KMH = float(os.getenv("ORCA_WIND_DIVERGENCE_MODERATE_KMH", "9").strip() or 9)
HIGH_ABS_KMH = float(os.getenv("ORCA_WIND_DIVERGENCE_HIGH_KMH", "15").strip() or 15)
MODERATE_PCT = float(os.getenv("ORCA_WIND_DIVERGENCE_MODERATE_PCT", "25").strip() or 25)
HIGH_PCT = float(os.getenv("ORCA_WIND_DIVERGENCE_HIGH_PCT", "50").strip() or 50)
# Direction divergence is reported always; it only escalates a borderline
# speed match up to MODERATE (never on its own to HIGH -- speed carries the
# safety-relevant signal per the brief).
DIRECTION_MODERATE_DEG = float(os.getenv("ORCA_WIND_DIRECTION_MODERATE_DEG", "45").strip() or 45)

# Spatial/temporal tolerance for treating an observation as usable.
MAX_SPATIAL_KM = float(os.getenv("ORCA_WIND_MAX_SPATIAL_KM", "50").strip() or 50)
MAX_AGE_MIN = float(os.getenv("ORCA_WIND_MAX_AGE_MIN", "180").strip() or 180)

# Confidence penalty applied to the response's overall confidence_score
# when divergence is HIGH -- flags the forecast as less trustworthy without
# claiming the satellite "proves" it wrong (brief requirement #11).
HIGH_DIVERGENCE_CONFIDENCE_PENALTY = float(
    os.getenv("ORCA_WIND_HIGH_DIVERGENCE_PENALTY", "0.15").strip() or 0.15
)

# Whole-observation TTL cache -- satellite passes are infrequent, so this
# can be much longer than the forecast cache without going stale in a way
# that matters. Env-overridable for latency tuning / demos.
_OBS_TTL_S = int(os.getenv("ORCA_SATWIND_TTL_S", "1800").strip() or 1800)  # 30 min
_obs_cache: dict[tuple, tuple[float, WindObservation]] = {}

_KMH_PER_KNOT = 1.852

_real_provider = MosdacScatWindConnector()
_demo_provider = DemoSatelliteWindProvider()


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def get_satellite_observation(
    location: Location, demo_scenario: Optional[str] = None,
) -> WindObservation:
    """Cached fetch: real provider first (fast UNAVAILABLE if not configured),
    demo provider only when explicitly requested via `demo_scenario`.

    Real and simulated observations are never mixed for the same call --
    demo_scenario short-circuits straight to the demo provider so a demo
    request always returns something clearly SIMULATED, and a normal
    request never silently receives simulated data.
    """
    cache_key = (round(location.lat, 3), round(location.lon, 3), demo_scenario or "")
    hit = _obs_cache.get(cache_key)
    if hit is not None and time.monotonic() - hit[0] < _OBS_TTL_S:
        return hit[1]

    now = datetime.now(timezone.utc)
    if demo_scenario is not None:
        obs = _demo_provider.get_observation(location, now, scenario=demo_scenario)
    else:
        obs = _real_provider.get_observation(location, now)
        # Real path is not activated (no credential / no live endpoint) --
        # this is an instant, purely local check, never a network call, so
        # it never adds latency to a normal fisherman query.

    _obs_cache[cache_key] = (time.monotonic(), obs)
    return obs


def _classify(abs_diff: float, pct_diff: float, direction_diff: Optional[float]) -> DivergenceStatus:
    if abs_diff >= HIGH_ABS_KMH or pct_diff >= HIGH_PCT:
        return DivergenceStatus.HIGH_DIVERGENCE
    is_moderate = abs_diff >= MODERATE_ABS_KMH or pct_diff >= MODERATE_PCT
    if not is_moderate and direction_diff is not None and direction_diff >= DIRECTION_MODERATE_DEG:
        is_moderate = True
    return DivergenceStatus.MODERATE_DIVERGENCE if is_moderate else DivergenceStatus.MATCH


def _direction_diff_deg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _warning_for(status: DivergenceStatus, abs_diff: float) -> str:
    if status == DivergenceStatus.HIGH_DIVERGENCE:
        return "Satellite-observed wind is significantly stronger than the forecast." if abs_diff > 0 else \
               "Satellite-observed wind is significantly weaker than the forecast."
    if status == DivergenceStatus.MODERATE_DIVERGENCE:
        return "Satellite observation differs moderately from the forecast wind."
    return "Satellite observation agrees with the forecast wind."


def analyze_wind_divergence(
    forecast_wind_kmh: float,
    location: Location,
    forecast_wind_direction_deg: Optional[float] = None,
    demo_scenario: Optional[str] = None,
) -> WindDivergenceResult:
    """Main entry: forecast wind (already computed by OceanStateAgent) vs.
    the (cached) satellite observation for the same point.

    Never blocks on network I/O for a real fetch (unactivated -> instant
    UNAVAILABLE); the demo path is deterministic and instant too.
    """
    obs = get_satellite_observation(location, demo_scenario=demo_scenario)

    if obs.status == WindObsStatus.UNAVAILABLE:
        return WindDivergenceResult(
            forecast_wind_kmh=forecast_wind_kmh, satellite_wind_kmh=None,
            abs_diff_kmh=None, pct_diff=None, direction_diff_deg=None,
            status=DivergenceStatus.UNAVAILABLE,
            warning="Satellite wind observation unavailable -- forecast used as-is.",
            satellite_status=obs.status, satellite_source=obs.source,
            satellite_dataset=obs.dataset, observation_age_minutes=None,
            spatial_offset_km=None, confidence_penalty=0.0,
            reasoning_note=obs.reason,
        )

    # Spatial check: the demo/real observation is generated AT the query
    # point today, but the field is here so a future adapter that snaps to
    # a satellite pixel grid (like chlorophyll.py) is handled correctly.
    spatial_km = _haversine_km(location.lat, location.lon, obs.latitude, obs.longitude)
    if spatial_km > MAX_SPATIAL_KM:
        return WindDivergenceResult(
            forecast_wind_kmh=forecast_wind_kmh, satellite_wind_kmh=obs.wind_speed_kmh,
            abs_diff_kmh=None, pct_diff=None, direction_diff_deg=None,
            status=DivergenceStatus.UNAVAILABLE,
            warning="Nearest satellite observation is too far from the query point to compare.",
            satellite_status=obs.status, satellite_source=obs.source,
            satellite_dataset=obs.dataset, observation_age_minutes=None,
            spatial_offset_km=round(spatial_km, 1), confidence_penalty=0.0,
            reasoning_note=f"Spatial mismatch: {spatial_km:.1f} km > {MAX_SPATIAL_KM:.0f} km tolerance.",
        )

    # Temporal (staleness) check.
    age_min: Optional[float] = None
    if obs.observation_timestamp is not None:
        age_min = (datetime.now(timezone.utc) - obs.observation_timestamp).total_seconds() / 60.0
        if age_min > MAX_AGE_MIN:
            return WindDivergenceResult(
                forecast_wind_kmh=forecast_wind_kmh, satellite_wind_kmh=obs.wind_speed_kmh,
                abs_diff_kmh=None, pct_diff=None, direction_diff_deg=None,
                status=DivergenceStatus.STALE,
                warning="Satellite observation is too old to compare against the current forecast.",
                satellite_status=obs.status, satellite_source=obs.source,
                satellite_dataset=obs.dataset, observation_age_minutes=round(age_min, 1),
                spatial_offset_km=round(spatial_km, 1), confidence_penalty=0.0,
                reasoning_note=f"Observation age {age_min:.0f} min > {MAX_AGE_MIN:.0f} min freshness limit.",
            )

    abs_diff = round(abs(obs.wind_speed_kmh - forecast_wind_kmh), 2)
    pct_diff = round((abs_diff / forecast_wind_kmh) * 100, 1) if forecast_wind_kmh > 0 else 0.0
    dir_diff = _direction_diff_deg(forecast_wind_direction_deg, obs.wind_direction_deg)

    status = _classify(abs_diff, pct_diff, dir_diff)
    signed_diff = round(obs.wind_speed_kmh - forecast_wind_kmh, 2)
    warning = _warning_for(status, signed_diff)
    penalty = HIGH_DIVERGENCE_CONFIDENCE_PENALTY if status == DivergenceStatus.HIGH_DIVERGENCE else 0.0

    note = (
        f"Forecast {forecast_wind_kmh:.1f} km/h ({forecast_wind_kmh/_KMH_PER_KNOT:.0f} kn) vs "
        f"satellite {obs.wind_speed_kmh:.1f} km/h ({obs.wind_speed_kmh/_KMH_PER_KNOT:.0f} kn): "
        f"diff {signed_diff:+.1f} km/h ({pct_diff:.0f}%)."
        + (f" Direction diff {dir_diff:.0f} deg." if dir_diff is not None else "")
        + (" Forecast confidence reduced -- treat this reading with extra caution."
           if status == DivergenceStatus.HIGH_DIVERGENCE else "")
    )

    return WindDivergenceResult(
        forecast_wind_kmh=forecast_wind_kmh, satellite_wind_kmh=obs.wind_speed_kmh,
        abs_diff_kmh=abs_diff, pct_diff=pct_diff, direction_diff_deg=dir_diff,
        status=status, warning=warning,
        satellite_status=obs.status, satellite_source=obs.source, satellite_dataset=obs.dataset,
        observation_age_minutes=round(age_min, 1) if age_min is not None else None,
        spatial_offset_km=round(spatial_km, 1),
        confidence_penalty=penalty, reasoning_note=note,
    )


def result_to_dict(result: WindDivergenceResult) -> dict:
    d = asdict(result)
    d["status"] = result.status.value
    d["satellite_status"] = result.satellite_status.value
    # Knots for the fisherman-facing UI ("Forecast: 18 kn / Satellite: 27 kn").
    d["forecast_wind_kn"] = round(result.forecast_wind_kmh / _KMH_PER_KNOT, 1)
    d["satellite_wind_kn"] = (
        round(result.satellite_wind_kmh / _KMH_PER_KNOT, 1)
        if result.satellite_wind_kmh is not None else None
    )
    d["diff_kn"] = (
        round(result.abs_diff_kmh / _KMH_PER_KNOT, 1)
        if result.abs_diff_kmh is not None else None
    )
    d["is_simulated"] = result.satellite_status == WindObsStatus.SIMULATED
    return d
