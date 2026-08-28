"""
IMD live connector -- India Meteorological Department public REST API.

Endpoints (documented at https://api.imd.gov.in/public/api_reference.html):
    GET {BASE_URL}/cyclone_track          active cyclone system nationwide
    GET {BASE_URL}/cyclone_wind           GeoJSON wind warning zones
    GET {BASE_URL}/cyclone_cou            GeoJSON cone of uncertainty
    GET {BASE_URL}/coastalbulletin        current coastal bulletins
    GET {BASE_URL}/districtwarning?id=..  district day-wise warning codes
    GET {BASE_URL}/portwarning?id=..      port warning            (path TODO verify)
    GET {BASE_URL}/seaareabulletin?id=..  sea area bulletin       (path TODO verify)

*** FIELD REALITY CHECK (2026-08-24) ************************************
Probed live during development: WITHOUT a key, every endpoint answers
    HTTP 401  {"error": "API key missing"}
(the TLS certificate chain is also incomplete, which urllib rejects by
default -- see _get_json's fallback below). So despite the "public" label,
an IMD_API_KEY appears to be required. If IMD_API_KEY is set it is sent as
an 'api-key' query parameter plus a Bearer header (both common IMD/data.gov.in
conventions -- confirm the exact scheme when a real key is issued). Until a
working key exists, callers will receive ImdUnavailableError, which the
Hazard Agent surfaces honestly as "cyclone status could NOT be verified".
*************************************************************************

Design rules:
    - Network / timeout / HTTP-error / JSON-parse failures raise
      ImdUnavailableError. Functions NEVER return invented placeholder data.
    - An "inactive" condition (e.g. no observed cyclone) is a SUCCESS and
      returns a structured inactive result -- it is not an error.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("orca.imd_live")

BASE_URL = "https://api.imd.gov.in/api/v1"
_HTTP_TIMEOUT_S = 15.0
_HEADERS = {
    # Identifies the project honestly; IMD asks for a descriptive UA.
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
    "Accept": "application/json",
}


class ImdUnavailableError(Exception):
    """Raised when the IMD API cannot be reached, refuses the request,
    or returns unparseable output. Never raised for a legitimately
    'inactive/no-alert' response."""


# ---------------------------------------------------------------------------
# District/port/region object IDs are NOT published anywhere in IMD's docs.
# They must be discovered manually: open the page below, select a district /
# port / sea area in the UI, and read the `id` query parameter of the XHR the
# page sends to api.imd.gov.in. Populate the mapping(s) once discovered.
#
#   https://mausam.imd.gov.in/responsive/districtWiseWarningGIS.php   (districts)
#   https://rsmcnewdelhi.imd.gov.in/port-warning.php                  (ports)
#   https://mausam.imd.gov.in/responsive/marine_forecast.php          (sea areas)
# ---------------------------------------------------------------------------
DISTRICT_IDS: dict[str, int] = {}  # TODO: discover ids via devtools (see block above)


def _is_cert_failure(exc: Exception) -> bool:
    """urllib wraps TLS errors in URLError; inspect the wrapped reason."""
    reason = getattr(exc, "reason", None)
    return (
        isinstance(reason, ssl.SSLCertVerificationError)
        or "CERTIFICATE_VERIFY_FAILED" in str(reason)
    )


def _get_json(path: str, params: dict | None = None):
    """GET {BASE_URL}{path} and return the parsed JSON body.

    Tries certificate-verifying TLS first; IMD's chain is incomplete, so if
    verification fails the request is retried ONCE with verification relaxed
    and a loud warning is logged (accepted hackathon trade-off, documented
    here). Any network, HTTP, or parse failure becomes ImdUnavailableError.
    """
    query = dict(params or {})
    api_key = os.getenv("IMD_API_KEY", "").strip()
    if api_key:
        query["api-key"] = api_key

    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    headers = dict(_HEADERS)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for attempt in (1, 2):
        relaxed_ctx = ssl._create_unverified_context() if attempt == 2 else None
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                req, timeout=_HTTP_TIMEOUT_S, context=relaxed_ctx
            ) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as exc:
            # Definitive server answer (e.g. 401 API key missing) -- no retry.
            snippet = ""
            try:
                snippet = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            raise ImdUnavailableError(
                f"IMD {path} returned HTTP {exc.code} {snippet}".rstrip()
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 1 and _is_cert_failure(exc):
                logger.warning(
                    "IMD TLS certificate verification failed (%s); retrying ONCE "
                    "with verification relaxed -- accepted prototype trade-off, "
                    "documented in data_connectors/imd_live.py",
                    getattr(exc, "reason", exc),
                )
                continue
            raise ImdUnavailableError(
                f"IMD {path} unreachable/network failure: "
                f"{getattr(exc, 'reason', exc)}"
            ) from exc
    else:
        raise ImdUnavailableError(f"IMD {path}: retries exhausted")

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ImdUnavailableError(
            f"IMD {path} returned non-JSON content ({len(raw)} bytes)"
        ) from exc


# ---------------------------------------------------------------------------
# Public fetchers
# ---------------------------------------------------------------------------

def fetch_cyclone_status() -> dict:
    """Current nationwide cyclone situation from IMD's cyclone track feed.

    Returns:
        {
            "active": bool,
            "name": str | None,          # CYCLONE_NAME of latest observed fix
            "category": str | None,      # e.g. "Severe Cyclonic Storm"
            "lat": float | None, "lon": float | None,
            "forecast_track": list,      # forecast points, verbatim from IMD
            "checked_at_utc": str,       # ISO timestamp of this check
        }
        active=False (with None fields) means IMD reports NO current system --
        that is a clean result, never an error.
    """
    payload = _get_json("/cyclone_track")
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    observed = data.get("observed") or []
    forecast = data.get("forecast") or []

    if not observed:
        return {
            "active": False,
            "name": None,
            "category": None,
            "lat": None,
            "lon": None,
            "forecast_track": [],
            "checked_at_utc": _utc_now_iso(),
        }

    latest = observed[-1] if isinstance(observed[-1], dict) else {}
    return {
        "active": True,
        "name": latest.get("CYCLONE_NAME"),
        "category": latest.get("Category"),
        "lat": latest.get("lat"),
        "lon": latest.get("lon"),
        "forecast_track": forecast,
        "checked_at_utc": _utc_now_iso(),
    }


def fetch_cyclone_wind_warning():
    """GeoJSON MultiPolygon wind warning zones, or None when inactive."""
    payload = _get_json("/cyclone_wind")
    features = payload.get("features") if isinstance(payload, dict) else None
    if not features:
        return None
    return payload


def fetch_cyclone_cone_of_uncertainty():
    """GeoJSON cone-of-uncertainty zones, or None when inactive."""
    payload = _get_json("/cyclone_cou")
    features = payload.get("features") if isinstance(payload, dict) else None
    if not features:
        return None
    return payload


def fetch_coastal_bulletin() -> list[dict]:
    """Current coastal bulletins (Layer, Wind, Sea Condition, Visibility,
    Weather, Update Time). Returns a list -- possibly empty."""
    payload = _get_json("/coastalbulletin")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        inner = payload.get("data")
        return inner if isinstance(inner, list) else []
    return []


def fetch_district_warning(obj_id: int) -> dict:
    """Day-wise district warning codes for one district object id.

    Colour-code severity per the live API (Day1_Color..Day5_Color):
        1 = red (most severe), 2 = orange, 3 = yellow, 4 = green (mildest)
    NOTE: an earlier version of this project's documentation had this
    mapping reversed; trust the values observed in real responses over any
    doc, and re-verify on first successful authenticated call.

    Requires an entry in DISTRICT_IDS (ids are unpublished -- see the
    discovery instructions above).
    """
    if obj_id is None:
        raise ImdUnavailableError(
            "district warning needs an obj_id; DISTRICT_IDS is empty -- "
            "discover ids via devtools on "
            "https://mausam.imd.gov.in/responsive/districtWiseWarningGIS.php"
        )
    return _get_json("/districtwarning", params={"id": obj_id})


def fetch_port_warning(port_id: int | str) -> dict:
    """Port warning for one port id.

    Ids are unpublished: discover via devtools on
    https://rsmcnewdelhi.imd.gov.in/port-warning.php (select a port, watch
    the request). Endpoint path below follows the api.imd.gov.in naming
    pattern -- TODO verify against the official api_reference.html.
    """
    if port_id is None:
        raise ImdUnavailableError(
            "port warning needs a port_id; discover ids via devtools on "
            "https://rsmcnewdelhi.imd.gov.in/port-warning.php"
        )
    return _get_json("/portwarning", params={"id": port_id})


def fetch_sea_area_bulletin(region_id: int | str) -> dict:
    """Sea area bulletin for one region id.

    Ids are unpublished: discover via devtools on
    https://mausam.imd.gov.in/responsive/marine_forecast.php (select a sea
    area, watch the request). Endpoint path follows the api.imd.gov.in
    naming pattern -- TODO verify against the official api_reference.html.
    """
    if region_id is None:
        raise ImdUnavailableError(
            "sea area bulletin needs a region_id; discover ids via devtools "
            "on https://mausam.imd.gov.in/responsive/marine_forecast.php"
        )
    return _get_json("/seaareabulletin", params={"id": region_id})


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
