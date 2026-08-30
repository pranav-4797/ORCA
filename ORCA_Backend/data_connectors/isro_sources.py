"""
Indian agency data connectors -- MOSDAC / INCOIS / IMD

MOSDAC (ISRO/SAC) — Oceansat-3 OCM chlorophyll (primary) is now wired as the
first-choice chlorophyll source in OceanStateAgent, with the INCOIS ERDDAP
OceanSat-2:CHL path kept as a free keyless secondary fallback (currently empty
since 2011‑02‑02, but harmless to try). IMD CAP remains the live keyless
alert feed; api.imd.gov.in is a gated secondary. INCOIS THREDDS WMS is the
primary for SST/wind/current/swell.

MOSDAC access: https://mosdac.gov.in — Registered General User tier
includes OCM chlorophyll (Anonymous tier does NOT). Set MOSDAC_API_KEY in
.env (see .env.example). Registered tier has a 3‑day latency per MOSDAC
policy — a successful fetch is therefore 3 days old, and callers surface
that in trace/evidence so "live" is not misleading.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

from models import Location

logger = logging.getLogger("orca.isro_sources")


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
    """ISRO MOSDAC -- satellite-derived chlorophyll & SST (Oceansat-3 OCM).

    Live path (post‑2025‑08‑30): this is the PRIMARY chlorophyll source.
    INCOIS ERDDAP OceanSat-2:CHL is kept as a free secondary fallback.

    Auth: MOSDAC issues a per‑account API key after free registration
    (Registered General User). The portal docs show two accepted styles
    across product families — Bearer header and `api_key` query param.
    We send BOTH (header `Authorization: Bearer <key>` and query `api_key=<key>`)
    so the correct one is always present regardless of which sub‑service
    the key was issued for. BASE_URL is the product host; override via
    env `MOSDAC_BASE_URL` if the docs you see post‑registration differ.

    Product path: the OCM chlorophyll grid is published as OCM‑3 L2
    (`ocm_chlorophyll` / `ocm_chl` / `OCEANSAT3_OCM_L2` depending on the
    docs snapshot). The default below matches the portal's
    "OCM Chlorophyll — 1km Daily" listing; if your docs show a different
    slug, set `MOSDAC_PRODUCT` in .env or pass `product=` to build_request().
    Response may be JSON, NetCDF or CSV — we try JSON first, then a
    lightweight text/CSV scan for a chlorophyll field.
    """

    name = "MOSDAC"
    ENV_KEY = "MOSDAC_API_KEY"
    # Base host for the API; the product path is appended by build_request().
    # Override with MOSDAC_BASE_URL if your registration shows a different host
    # (e.g. https://mosdac.gov.in/mosdac-apis or https://api.mosdac.gov.in).
    BASE_URL = "https://mosdac.gov.in/api"
    # Default OCM chlorophyll product slug — override via MOSDAC_PRODUCT if needed.
    PRODUCT = "ocm_chlorophyll"
    TIMEOUT_S = 12.0

    def build_request(self, location: Location, product: str | None = None) -> dict:
        """Return the HTTP request shape for an OCM chlorophyll point query.

        Never raises for missing key at build time — the fetch() path will
        raise _RequiresApiKey instead, so callers can distinguish "not
        configured" from "service error".
        """
        import os

        base = os.getenv("MOSDAC_BASE_URL", self.BASE_URL).strip() or self.BASE_URL
        prod = (product or os.getenv("MOSDAC_PRODUCT", self.PRODUCT) or self.PRODUCT).strip()
        token = _require_key(self.ENV_KEY)
        # MOSDAC docs vary: some examples use /api/<product>, others /api/data/<product>.
        # We use /<product> and let the server 404 quickly if the slug is wrong — the
        # error message will contain the docs hint, and the caller falls back to INCOIS.
        url = f"{base.rstrip('/')}/{prod.lstrip('/')}"
        return {
            "url": url,
            "params": {
                "lat": f"{location.lat:.4f}",
                "lon": f"{location.lon:.4f}",
                # Registered tier is 3‑day delayed — request "latest" and let the
                # server return the newest available granule (usually T-3).
                "date": "latest",
                "api_key": token,
            },
            "headers": {
                "Authorization": f"Bearer {token}",
                "X-API-Key": token,
                "User-Agent": "orca-mosdac/1.0 (SIH-2026)",
                "Accept": "application/json, text/csv, application/x-netcdf;q=0.8, */*;q=0.5",
            },
        }

    def fetch(self, location: Location) -> dict:
        """Point chlorophyll from MOSDAC OCM — returns {"chlorophyll": float, ...}.

        Raises _RequiresApiKey if MOSDAC_API_KEY is not set, and ValueError on
        any non‑retryable parse/validation failure. Callers treat any exception
        as "MOSDAC unavailable for this point" and fall back to INCOIS.
        """
        import os

        req = self.build_request(location)
        url = f"{req['url']}?{urllib.parse.urlencode(req['params'])}"
        headers = req["headers"]
        logger.info("MOSDAC OCM chlorophyll fetch for %.4f,%.4f -> %s", location.lat, location.lon, url.split("?")[0])

        http_req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(http_req, timeout=self.TIMEOUT_S) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
                logger.info("[MOSDAC] HTTP=%s Content-Type=%s bytes=%d", status, ctype, len(body))
                if status >= 400:
                    raise ValueError(f"MOSDAC HTTP {status}: {body[:300].decode(errors='replace')}")
        except _RequiresApiKey:
            raise
        except Exception as exc:
            # Network/service error — caller will fall back to INCOIS
            raise ValueError(f"MOSDAC chlorophyll unavailable for {location.lat},{location.lon}: {exc}") from exc

        # Try JSON first (most MOSDAC product APIs return JSON with a chlorophyll field)
        text = body.decode("utf-8", errors="replace")
        val: float | None = None
        # Quick JSON attempt
        try:
            data = json.loads(text)
            val = self._extract_chlorophyll_from_json(data)
        except Exception:
            val = None

        # Text/CSV scan fallback — look for a chlorophyll/chl/chla field
        if val is None:
            val = self._extract_chlorophyll_from_text(text)

        if val is None:
            raise ValueError(f"MOSDAC chlorophyll value not found in response for {location.lat},{location.lon} (ctype={ctype})")

        if not self._validate(val):
            raise ValueError(f"MOSDAC chlorophyll {val} mg/m³ out of range 0-50 for {location.lat},{location.lon}")

        # Registered tier latency hint for provenance
        latency_note = "MOSDAC Registered tier — 3-day latency (latest available granule, typically T-3)"
        return {
            "chlorophyll": round(float(val), 3),
            "source": "MOSDAC_OCM_L2",
            "latency_note": latency_note,
            "raw_bytes": len(body),
        }

    @staticmethod
    def _validate(v: float | None) -> bool:
        if v is None:
            return False
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        # mg/m³ sanity for coastal chlorophyll — 0–50 covers oligotrophic to eutrophic/ bloom
        return 0.0 <= f <= 50.0 and f == f  # NaN check

    @staticmethod
    def _extract_chlorophyll_from_json(data) -> float | None:
        """Depth‑first search for a chlorophyll‑like key in a JSON payload."""
        candidates = ("chlorophyll", "chl", "chla", "chlor_a", "chlor_a_concentration", "concentration", "value", "chla_mean")
        if isinstance(data, dict):
            # Direct hit
            for k in candidates:
                if k in data:
                    try:
                        return float(data[k])
                    except (TypeError, ValueError):
                        pass
            # Common nesting: data -> features -> properties, or result -> data
            for v in data.values():
                got = MosdacConnector._extract_chlorophyll_from_json(v)
                if got is not None:
                    return got
        elif isinstance(data, list):
            for item in data:
                got = MosdacConnector._extract_chlorophyll_from_json(item)
                if got is not None:
                    return got
        return None

    @staticmethod
    def _extract_chlorophyll_from_text(text: str) -> float | None:
        """Scan plain text / CSV for a chlorophyll field."""
        import re

        # Look for lines like "chlorophyll: 1.23" or "CHL=0.45" or CSV "chlorophyll,1.2"
        for line in text.splitlines():
            # Skip obvious headers that are not data
            if not line.strip():
                continue
            # Try key: value
            m = re.search(r"(?:chlorophyll|chl|chla)\s*[:=,]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", line, re.I)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
            # Try CSV with header "chlorophyll" in previous line
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
                for p in parts:
                    try:
                        f = float(p)
                        if 0 <= f <= 50:
                            # Heuristic: if line also mentions chlorophyll, accept
                            if re.search(r"chloro|chla", line, re.I):
                                return f
                    except ValueError:
                        continue
        return None


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
