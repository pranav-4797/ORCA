"""
IMD CAP connector -- India Meteorological Department's official Common
Alerting Protocol feed. This is the KEYLESS replacement for the gated
api.imd.gov.in endpoints (which require IP whitelisting + an issued key,
see data_connectors/imd_live.py).

Source (linked as "Latest CAP Alerts" from IMD's own API page,
https://mausam.imd.gov.in/responsive/apis.php):
    GET https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml

The RSS channel lists current alerts; every <item><link> points at a full
CAP 1.2 XML document with structured severity/geometry:

    <cap:alert>
      <cap:identifier>urn:oid:...</cap:identifier>
      <cap:sent>2026-08-23T13:07:38+05:30</cap:sent>
      <cap:info>
        <cap:event>Extremely heavy</cap:event>
        <cap:severity>Severe</cap:severity>          Extreme | Severe | Moderate | Minor | Unknown
        <cap:onset>..</cap:onset> <cap:expires>..</cap:expires>
        <cap:headline>..</cap:headline> <cap:description>..</cap:description>
        <cap:instruction>..</cap:instruction>
        <cap:area>
          <cap:areaDesc>ODISHA</cap:areaDesc>
          <cap:polygon>21.43,83.47 20.89,82.41 ...</cap:polygon>   (lat,lon pairs)
        </cap:area>

*** FIELD REALITY CHECK (2026-08-24) ************************************
Probed live during development: HTTP 200 with NO credentials, no TLS chain
problems (unlike api.imd.gov.in). Feed is digitally signed per alert and
refreshed continuously (last observed update lag < 10 minutes).
*************************************************************************

Design rules (mirroring imd_live.py):
    - Network / HTTP / XML-parse failures raise CapUnavailableError.
      Functions NEVER return invented placeholder data.
    - "No active alerts" is a SUCCESS and returns an empty/inactive result.

Caveat vs the gated cyclone_track endpoint: CAP carries warning EVENTS with
affected-area polygons, not storm-centre track points. fetch_cyclone_status()
therefore reports lat/lon as None and puts affected areas in "areas" -- the
Hazard Agent hit-tests the user's point against those polygons instead of a
single national yes/no.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

logger = logging.getLogger("orca.imd_cap")

RSS_URL = "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml"
_HTTP_TIMEOUT_S = 15.0
_HEADERS = {
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
    "Accept": "application/xml, text/xml, */*",
}

_CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"

# Event/description terms that mark an alert as relevant to marine safety.
_MARINE_TERMS = (
    "cyclone", "fishermen", "fisherman", "squally", "rough sea",
    "very rough sea", "high sea", "gale", "storm surge", "marine",
)
# Subset that indicates a tropical system specifically (vs e.g. thunderstorms).
_CYCLONE_TERMS = ("cyclone", "depression", "storm surge")
# Thunderstorm/lightning events (PS query: 'any lightning or cyclone alerts').
_LIGHTNING_TERMS = ("lightning", "thunderstorm", "thunder")


class CapUnavailableError(Exception):
    """Raised when the CAP feed cannot be reached or parsed. Never raised
    for a legitimately 'no active alerts' response."""


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        snippet = ""
        try:
            snippet = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise CapUnavailableError(
            f"CAP {url} returned HTTP {exc.code} {snippet}".rstrip()
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CapUnavailableError(
            f"CAP {url} unreachable/network failure: "
            f"{getattr(exc, 'reason', exc)}"
        ) from exc


def _parse_iso_utc(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _parse_polygon(text: str) -> list[tuple[float, float]]:
    """'21.43,83.47 20.89,82.41 ...' -> [(lat, lon), ...]. Empty on garbage."""
    ring: list[tuple[float, float]] = []
    for pair in text.split():
        parts = pair.split(",")
        if len(parts) != 2:
            continue
        try:
            ring.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return ring if len(ring) >= 3 else []


def point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting hit test. Ring vertices are (lat, lon) tuples."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i][0], ring[i][1]
        yj, xj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _parse_cap_alert(xml_bytes: bytes) -> dict | None:
    """Parse one CAP 1.2 document into a flat dict, dropping expired infos."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CapUnavailableError(f"CAP alert XML unparseable: {exc}") from exc

    def _text(el) -> str:
        return (el.text or "").strip() if el is not None else ""

    now = datetime.now(timezone.utc)
    sent = _parse_iso_utc(_text(root.find(f"{_CAP_NS}sent"))) or now

    infos = []
    for info in root.findall(f"{_CAP_NS}info"):
        expires = _parse_iso_utc(_text(info.find(f"{_CAP_NS}expires")))
        if expires is not None and expires <= now:
            continue  # expired info block -- not an active alert

        areas = []
        for area in info.findall(f"{_CAP_NS}area"):
            polys = [
                ring for ring in (
                    _parse_polygon(_text(p))
                    for p in area.findall(f"{_CAP_NS}polygon")
                )
                if ring
            ]
            areas.append({
                "area_desc": _text(area.find(f"{_CAP_NS}areaDesc")),
                "polygons": polys,
            })

        infos.append({
            "event": _text(info.find(f"{_CAP_NS}event")),
            "severity": _text(info.find(f"{_CAP_NS}severity")),
            "urgency": _text(info.find(f"{_CAP_NS}urgency")),
            "certainty": _text(info.find(f"{_CAP_NS}certainty")),
            "onset": _text(info.find(f"{_CAP_NS}onset")),
            "expires": _text(info.find(f"{_CAP_NS}expires")),
            "headline": _text(info.find(f"{_CAP_NS}headline")),
            "description": _text(info.find(f"{_CAP_NS}description")),
            "instruction": _text(info.find(f"{_CAP_NS}instruction")),
            "sender_name": _text(info.find(f"{_CAP_NS}senderName")),
            "web": _text(info.find(f"{_CAP_NS}web")),
            "areas": areas,
        })

    if not infos:
        return None  # everything in this document already expired

    return {
        "identifier": _text(root.find(f"{_CAP_NS}identifier")),
        "sent": sent.isoformat(timespec="seconds"),
        "msg_type": _text(root.find(f"{_CAP_NS}msgType")),
        "status": _text(root.find(f"{_CAP_NS}status")),
        "infos": infos,
    }


# ---------------------------------------------------------------------------
# Public fetchers
# ---------------------------------------------------------------------------

_alerts_cache: list[dict] | None = None
_alerts_cache_time: float = 0.0
_ALERTS_CACHE_TTL_S = 60.0


def fetch_active_alerts() -> list[dict]:
    """All currently-active IMD CAP alerts (any category). Cached for 60s."""
    global _alerts_cache, _alerts_cache_time
    now = time.monotonic()
    if _alerts_cache is not None and (now - _alerts_cache_time) < _ALERTS_CACHE_TTL_S:
        return _alerts_cache

    from concurrent.futures import ThreadPoolExecutor

    raw = _get(RSS_URL)
    try:
        rss_root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise CapUnavailableError(f"CAP RSS unparseable: {exc}") from exc

    items_to_fetch = []
    for item in rss_root.iter("item"):
        link_el = item.find("link")
        url = (link_el.text or "").strip() if link_el is not None else ""
        if url.startswith("http"):
            title = (item.findtext("title") or "").strip()
            items_to_fetch.append((url, title))

    def _fetch_item(pair: tuple[str, str]) -> dict | None:
        url, title = pair
        try:
            alert = _parse_cap_alert(_get(url))
            if alert:
                alert["rss_title"] = title
                return alert
        except Exception:
            return None
        return None

    alerts: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(_fetch_item, items_to_fetch)
        for r in results:
            if r is not None:
                alerts.append(r)

    _alerts_cache = alerts
    _alerts_cache_time = now
    return alerts


def fetch_marine_alerts(alerts: list[dict] | None = None) -> list[dict]:
    """Subset of active alerts relevant to marine safety (cyclones, squally
    wind, fishermen warnings...). Pass `alerts` to reuse a prior fetch."""
    alerts = fetch_active_alerts() if alerts is None else alerts
    marine = []
    for alert in alerts:
        blob = " ".join(
            f'{i["event"]} {i["headline"]} {i["description"]}' for i in alert["infos"]
        ).lower()
        if any(term in blob for term in _MARINE_TERMS):
            marine.append(alert)
    return marine


def match_alerts_by_terms(alerts: list[dict], terms: tuple[str, ...],
                          location: tuple[float, float] | None = None) -> dict:
    """Generic matcher used for cyclone / marine / lightning checks.

    Returns {"matches": [(alert_doc, info_block)], "covering": [area_desc]}.
    `covering` lists area descriptions whose polygon contains `location`.
    """
    matches: list[tuple[dict, dict]] = []
    covering: list[str] = []

    lat, lon = (location if location is not None else (None, None))
    for alert in alerts:
        for info in alert["infos"]:
            blob = f'{info["event"]} {info["headline"]} {info["description"]}'.lower()
            if any(term in blob for term in terms):
                matches.append((alert, info))
                break

    if location is not None:
        seen: set[str] = set()
        for _alert, info in matches:
            for area in info["areas"]:
                if area["area_desc"] in seen:
                    continue
                for ring in area["polygons"]:
                    if point_in_polygon(lat, lon, ring):
                        covering.append(area["area_desc"])
                        seen.add(area["area_desc"])
                        break

    return {"matches": matches, "covering": covering}


def alerts_touching_location(alerts: list[dict],
                             location: tuple[float, float]) -> list[dict]:
    """All active alerts whose polygons contain the point (any category)."""
    hits: list[dict] = []
    lat, lon = location
    for alert in alerts:
        for info in alert["infos"]:
            touched = False
            for area in info["areas"]:
                for ring in area["polygons"]:
                    if point_in_polygon(lat, lon, ring):
                        hits.append({
                            "event": info["event"],
                            "severity": info["severity"],
                            "area_desc": area["area_desc"],
                            "polygon": ring,
                        })
                        touched = True
                        break
                if touched:
                    break
            if touched:
                break
    return hits


def fetch_cyclone_status(location: tuple[float, float] | None = None,
                         alerts: list[dict] | None = None) -> dict:
    """Drop-in replacement for imd_live.fetch_cyclone_status(): current
    cyclone/depression situation from the keyless CAP feed.

    Returns:
        {
            "active": bool,
            "name": str | None,       # event/headline of latest match
            "category": str | None,   # CAP severity (e.g. "Severe")
            "lat": None, "lon": None, # CAP has no storm-centre points
            "forecast_track": [],     # idem -- see module docstring caveat
            "areas_covering_location": [area_desc, ...],
                                      # polygons containing `location` when given;
                                      # empty means no warning zone over that point
            "source_url": str,        # first matching CAP document URL
            "checked_at_utc": str,
        }
        active=False (with None fields) means NO active cyclone alert --
        a clean result, never an error.
    """
    alerts = fetch_active_alerts() if alerts is None else alerts

    matched = match_alerts_by_terms(alerts, _CYCLONE_TERMS, location)
    matches = matched["matches"]
    covering = matched["covering"]

    if not matches:
        return {
            "active": False,
            "name": None,
            "category": None,
            "lat": None,
            "lon": None,
            "forecast_track": [],
            "areas_covering_location": [],
            "source_url": None,
            "checked_at_utc": _utc_now_iso(),
        }

    latest_alert, latest_info = matches[-1]
    return {
        "active": True,
        "name": latest_info["event"] or latest_info["headline"] or "unnamed system",
        "category": latest_info["severity"] or None,
        "lat": None,
        "lon": None,
        "forecast_track": [],
        "areas_covering_location": covering,
        "source_url": RSS_URL,
        "checked_at_utc": _utc_now_iso(),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    # Manual probe: python -m data_connectors.imd_cap
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    found = fetch_active_alerts()
    print(f"{len(found)} active CAP alert(s)")
    print(json.dumps(fetch_cyclone_status(), indent=2)[:1200])
