"""
Indian agency data connectors -- MOSDAC / INCOIS / IMD

*** NOT YET ACTIVATED ***

These connectors are scaffolding for India's official ocean/weather feeds.
They are built against each agency's publicly documented request formats
where available, but NONE of them can run today because all three require
registered credentials:

    MOSDAC  -> https://mosdac.gov.in  (ISRO; Oceansat-3 OCM/SAMUDRA:
               chlorophyll, SST)
    INCOIS  -> https://oos.incois.org (Ocean State Forecast, PFZ advisories,
               tides/ currents)
    IMD     -> https://mausam.imd.gov.in / data.gov.in (AWS station weather:
               wind, gusts, rainfall)

Nothing in the running system imports or calls this module. The production
live path is Open-Meteo (see agents/ocean_state_agent.py). These classes
exist so that the moment real API keys are added to .env, wiring one in is
an import + a call -- not a research project.

Do NOT claim any of these sources are live anywhere in responses or logs
until their fetch() methods actually return data in production.
"""

from __future__ import annotations

from models import Location


class _RequiresApiKey(RuntimeError):
    """Raised when a connector is invoked without its configured credential."""


def _require_key(env_name: str) -> str:
    import os
    key = os.getenv(env_name, "").strip()
    if not key:
        raise _RequiresApiKey(
            f"{env_name} is not set. Register at the agency portal and add it to .env "
            f"(see .env.example). Until then this connector must not be used."
        )
    return key


class MosdacConnector:
    """ISRO MOSDAC -- satellite-derived chlorophyll & SST (Oceansat-3).

    Request format per MOSDAC's published API service style: HTTPS GET with
    a Bearer token header against their product/API endpoints.
    """
    name = "MOSDAC"
    ENV_KEY = "MOSDAC_API_KEY"
    BASE_URL = "https://mosdac.gov.in/api"  # placeholder base; confirm exact product path at registration

    def build_request(self, location: Location, product: str = "ocm_chlorophyll") -> dict:
        """Return the HTTP request shape (never executed by default)."""
        token = _require_key(self.ENV_KEY)
        return {
            "url": f"{self.BASE_URL}/{product}",
            "params": {
                "lat": location.lat,
                "lon": location.lon,
            },
            "headers": {"Authorization": f"Bearer {token}"},
        }

    def fetch(self, location: Location) -> dict:
        raise NotImplementedError(
            "MOSDAC connector is NOT ACTIVATED: # TODO: requires registered API key."
        )


class IncoisConnector:
    """INCOIS Ocean State Forecast / PFZ / tide-current services.

    INCOIS publishes OSF parameters (waves, currents, SST) for Indian coastal
    grids; programmatic access requires registering with their data services.
    """
    name = "INCOIS"
    ENV_KEY = "INCOIS_API_KEY"
    BASE_URL = "https://oos.incois.org/api"  # placeholder base; confirm exact endpoint at registration

    def build_request(self, location: Location) -> dict:
        key = _require_key(self.ENV_KEY)
        return {
            "url": f"{self.BASE_URL}/osf",
            "params": {"lat": location.lat, "lon": location.lon, "key": key},
            "headers": {},
        }

    def fetch(self, location: Location) -> dict:
        raise NotImplementedError(
            "INCOIS connector is NOT ACTIVATED: # TODO: requires registered API key."
        )


class ImdConnector:
    """IMD automatic weather stations (wind, gusts, pressure, rainfall).

    IMD current-weather data is commonly served through data.gov.in's
    documented REST pattern: GET with an 'api-key' query parameter against
    a published IMD AWS resource id.
    """
    name = "IMD"
    ENV_KEY = "IMD_API_KEY"
    RESOURCE_ID = "imd_aws_current_weather"  # replace with the real resource id at registration
    BASE_URL = "https://api.data.gov.in/resource"

    def build_request(self, location_hint: str) -> dict:
        key = _require_key(self.ENV_KEY)
        return {
            "url": f"{self.BASE_URL}/{self.RESOURCE_ID}",
            "params": {"api-key": key, "format": "json", "station": location_hint},
            "headers": {},
        }

    def fetch(self, location_hint: str) -> dict:
        raise NotImplementedError(
            "IMD connector is NOT ACTIVATED: # TODO: requires registered API key."
        )
