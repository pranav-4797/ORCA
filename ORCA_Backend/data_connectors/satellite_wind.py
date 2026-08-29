"""
Satellite ocean-wind connectors (ORCA Innovation #4).

*** REAL PROVIDER: NOT YET ACTIVATED ***

Preferred official source per project brief: an ISRO scatterometer product
via MOSDAC. IMPORTANT FIELD-REALITY CORRECTION -- the brief names
"SCATSAT-1", but SCATSAT-1 ended its mission on 28 Feb 2021 (satellite
lost, per ISRO); it is not live. Its operational successor is the
scatterometer on Oceansat-3/EOS-06 (launched Nov 2022, OSCAT-3), also
distributed via MOSDAC. This module targets that current instrument and
never claims SCATSAT-1 is live.

Like data_connectors/isro_sources.py, MOSDAC requires a registered
credential and does not publish a documented simple lat/lon REST endpoint
the way Open-Meteo does -- so, exactly as isro_sources.py does for
chlorophyll/SST/IMD, this connector is scaffolding: build_request() shows
the intended shape, fetch() raises NotImplementedError even when a key is
configured, and callers must treat that as UNAVAILABLE. Nothing in this
module invents or guesses an observation.

DEMO PROVIDER: deterministic, seeded, always tagged SIMULATED. Used only
when explicitly requested (wind_demo_scenario) -- never silently blended
into a real fisherman query, matching how Fleet Convergence keeps
simulated fleet activity opt-in (fleet_convergence.py).
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from models import Location, WindObsStatus, WindObservation

MOSDAC_ENV_KEY = "MOSDAC_API_KEY"


class SatelliteWindProvider(ABC):
    """Common interface every satellite wind source implements."""

    name: str

    @abstractmethod
    def get_observation(self, location: Location, target_time: datetime) -> WindObservation:
        ...


class MosdacScatWindConnector(SatelliteWindProvider):
    """ISRO Oceansat-3 (OSCAT-3) scatterometer ocean-surface wind, via MOSDAC.

    NOT ACTIVATED: MOSDAC access requires a registered credential and its
    product-download API is not a simple keyless lat/lon GET the way
    Open-Meteo/NOAA-ERDDAP are, so this connector cannot honestly claim to
    serve live data yet. It always returns UNAVAILABLE. The moment a real,
    documented programmatic endpoint + MOSDAC_API_KEY are available, only
    `fetch()` below needs a real implementation -- get_observation()'s
    contract does not change.
    """

    name = "MOSDAC_OSCAT3"
    DATASET = "Oceansat-3 OSCAT-3 L2B ocean surface wind vector"
    BASE_URL = "https://mosdac.gov.in/api"  # placeholder base; confirm at registration

    def build_request(self, location: Location) -> dict:
        key = os.getenv(MOSDAC_ENV_KEY, "").strip()
        if not key:
            raise RuntimeError(
                f"{MOSDAC_ENV_KEY} is not set. Register at mosdac.gov.in and add it "
                "to .env. Until then this connector must not be used."
            )
        return {
            "url": f"{self.BASE_URL}/oscat3_wind",
            "params": {"lat": location.lat, "lon": location.lon},
            "headers": {"Authorization": f"Bearer {key}"},
        }

    def fetch(self, location: Location) -> dict:
        raise NotImplementedError(
            "MOSDAC OSCAT-3 wind connector is NOT ACTIVATED: requires a registered "
            "API key and a confirmed product-download endpoint."
        )

    def get_observation(self, location: Location, target_time: datetime) -> WindObservation:
        key = os.getenv(MOSDAC_ENV_KEY, "").strip()
        if not key:
            return WindObservation(
                latitude=location.lat, longitude=location.lon,
                wind_speed_kmh=0.0, wind_direction_deg=None,
                observation_timestamp=None, source=self.name, dataset="",
                status=WindObsStatus.UNAVAILABLE,
                reason=f"{MOSDAC_ENV_KEY} not configured -- real satellite wind not activated.",
            )
        try:
            self.fetch(location)
        except NotImplementedError as exc:
            return WindObservation(
                latitude=location.lat, longitude=location.lon,
                wind_speed_kmh=0.0, wind_direction_deg=None,
                observation_timestamp=None, source=self.name, dataset="",
                status=WindObsStatus.UNAVAILABLE, reason=str(exc),
            )


class DemoSatelliteWindProvider(SatelliteWindProvider):
    """Deterministic, clearly-labelled SIMULATED satellite wind.

    Two ways to use it:
      - scenario="match" / "moderate" / "high_divergence": fixed demo
        numbers matching the brief's worked examples, independent of
        location (for reliable end-to-end demos).
      - scenario=None: deterministic per-location pseudo-random value,
        seeded off (lat, lon) like every other _simulate_* helper in this
        codebase (see ocean_state_agent._fetch_simulated_fallback).
    """

    name = "orca_demo_scatterometer"
    DATASET = "ORCA demo scatterometer (deterministic, not a real sensor)"

    _SCENARIOS = {
        # forecast_kmh is informational only -- the divergence engine
        # supplies the real forecast; these are the SATELLITE-side numbers.
        "match": {"wind_speed_kmh": 35.0, "wind_direction_deg": 210.0},
        "moderate": {"wind_speed_kmh": 42.0, "wind_direction_deg": 230.0},
        "high_divergence": {"wind_speed_kmh": 50.0, "wind_direction_deg": 260.0},
    }

    def get_observation(self, location: Location, target_time: datetime,
                        scenario: Optional[str] = None) -> WindObservation:
        if scenario and scenario in self._SCENARIOS:
            vals = self._SCENARIOS[scenario]
            speed, direction = vals["wind_speed_kmh"], vals["wind_direction_deg"]
        else:
            speed, direction = self._pseudo_random_wind(location)
        return WindObservation(
            latitude=location.lat, longitude=location.lon,
            wind_speed_kmh=round(speed, 2), wind_direction_deg=round(direction, 1),
            observation_timestamp=datetime.now(timezone.utc),
            source=self.name, dataset=self.DATASET,
            status=WindObsStatus.SIMULATED,
            reason="Demo/simulated satellite observation -- not a real sensor reading.",
        )

    @staticmethod
    def _pseudo_random_wind(location: Location) -> tuple[float, float]:
        seed = int(hashlib.sha256(f"satwind|{location.lat:.3f}|{location.lon:.3f}".encode()).hexdigest(), 16)
        speed_fraction = (seed >> 8) % 10_000 / 10_000
        dir_fraction = (seed >> 32) % 10_000 / 10_000
        speed = 8.0 + speed_fraction * (55.0 - 8.0)
        direction = dir_fraction * 360.0
        return speed, direction
