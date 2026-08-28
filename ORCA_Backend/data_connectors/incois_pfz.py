"""
INCOIS PFZ data connector -- the ONLY module that talks to INCOIS/SAMUDRA
for Potential Fishing Zone products (replaces the unverified Bhuvan WMS path,
see agents/pfz_agent.py). The same endpoints power the official SAMUDRA
mobile app and the PFZ WebGIS.

Endpoints (public, no API key required):
    PFZ geometry      GET https://gemini.incois.gov.in/api/ws/pfzLines
    Landing centres   GET https://gemini.incois.gov.in/api/ws/pfzMobile
    Advisory text     GET https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1&request_locale=en
    Sector text[opt]  POST https://incois.gov.in/MarineFisheries/TextData?secid=SEC001
                      (session cookie from the home page + form POST; the GET
                      variant alone returns only a generic query page)

Response shapes (verified live 2026-08-28):
    pfzLines   -> GeoJSON FeatureCollection of LineStrings. Each feature is one
                  digitized PFZ zone line; properties carry UID (year+julian+seq),
                  Year, Julian_day, Sno, Length, SECTORBOUN/.., SECTORNAME(ptr).
    pfzMobile  -> GeoJSON FeatureCollection of Points (~1,223 landing centres).
                  properties: LANDINGNAM, STATENAME, SECTOR_ID, X1(deg lon),
                  Y1(deg lat), plus the daily advisory fields only when a zone
                  is issued for that centre: Direction, Angle, Distance (km),
                  Depth (m), PLatitude, PLongitude (DMS, space separated,
                  e.g. "19 19 15 N"), forecast ("Y"/"N"). X1/Y1 also appear in
                  geometry.coordinates as [lon, lat].
    TextDataHome -> HTML page with forecast/valid-upto dates and a per-sector
                  HTML image map clickable through /MarineFisheries/TextData?secid=SECXXX.

Design rules:
    - Asynchronous httpx with a 30 s timeout, retried twice.
    - pfzLines + pfzMobile are fetched in PARALLEL (single asyncio.gather).
    - Results cached in memory for 10 minutes (module-level, thread-safe so
      the sync agent threads and the async FastAPI endpoint share one cache).
    - Failures raise IncoisUnavailableError. get_live_pfz() is best-effort: it
      returns whatever subset is reachable and only raises when the geometric
      sources are entirely unreachable (callers then fall back to derived data).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("orca.incois_pfz")

PFZ_LINES_URL = "https://gemini.incois.gov.in/api/ws/pfzLines"
PFZ_MOBILE_URL = "https://gemini.incois.gov.in/api/ws/pfzMobile"
ADVISORY_HOME_URL = (
    "https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1&request_locale=en"
)
SECTOR_TEXT_URL = "https://incois.gov.in/MarineFisheries/TextData?secid={secid}"
# The sector text is a session-protected query form: POST {"secid", ..} to the
# bare path (a secid in the GET query string yields "Invalid Request").
SECTOR_FORM_URL = "https://incois.gov.in/MarineFisheries/TextData"

HTTP_TIMEOUT_S = float(os.getenv("INCOIS_PFZ_TIMEOUT", "30"))
# The 30 s default matches the integration spec. Very slow links (this dev
# machine transfers the ~500 KB feeds at ~12 KB/s, ~40 s a payload) can raise
# it with INCOIS_PFZ_TIMEOUT=70 without changing agent behaviour.
RETRY_ATTEMPTS = 2                     # initial attempt + one retry
RETRY_DELAY_S = 1.0
CACHE_TTL_S = 600                      # 10-minute in-memory cache
_MAX_SECTOR_TEXT_CHARS = 4000

_HEADERS = {
    "User-Agent": "orca-backend/0.3 (SIH-2026 marine intelligence proto)",
    "Accept": "application/json, text/html, */*",
}

# ---------------------------------------------------------------------------
# In-memory TTL cache (thread-safe; shared by async + sync callers)
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if time.monotonic() > expires_at:
            del _cache[key]
            return None
        return value


def _cache_set(key: str, value: object, ttl_s: float = CACHE_TTL_S) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl_s, value)


class IncoisUnavailableError(Exception):
    """Raised when the INCOIS feeds cannot be reached or parsed."""


def _run_async(coro) -> object:
    """Run a coroutine from a synchronous context (agent thread pool).

    A fresh event loop per call avoids clashes with the FastAPI loop when the
    agent runs inside a ThreadPoolExecutor worker.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Low-level fetching with retry
# ---------------------------------------------------------------------------

async def _get_json(client: httpx.AsyncClient, url: str) -> object:
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = await client.get(url, timeout=HTTP_TIMEOUT_S)
            if resp.status_code >= 400:
                raise IncoisUnavailableError(
                    f"{url} returned HTTP {resp.status_code}"
                )
            return resp.json()
        except (httpx.HTTPError, IncoisUnavailableError, ValueError) as exc:
            last_error = exc
            logger.warning("INCOIS GET %s failed (attempt %d): %s",
                           url, attempt + 1, exc)
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY_S)
    raise IncoisUnavailableError(f"INCOIS {url} unreachable after "
                                 f"{RETRY_ATTEMPTS} attempt(s): {last_error}")


async def _get_text(client: httpx.AsyncClient, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = await client.get(url, timeout=HTTP_TIMEOUT_S)
            if resp.status_code >= 400:
                raise IncoisUnavailableError(
                    f"{url} returned HTTP {resp.status_code}"
                )
            return resp.text
        except (httpx.HTTPError, IncoisUnavailableError) as exc:
            last_error = exc
            logger.warning("INCOIS GET %s failed (attempt %d): %s",
                           url, attempt + 1, exc)
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY_S)
    raise IncoisUnavailableError(f"INCOIS {url} unreachable after "
                                 f"{RETRY_ATTEMPTS} attempt(s): {last_error}")


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_DMS_RE = re.compile(
    r"\s*(\d+)\s+(\d+)\s+([\d.]+)\s*([NSEW])\s*$", re.IGNORECASE
)


def dms_to_decimal(text: str) -> float | None:
    """'19 19 15 N' or '71 50 18 E' -> signed decimal degrees (None on garbage)."""
    if not text or not isinstance(text, str):
        return None
    m = _DMS_RE.fullmatch(text.strip())
    if not m:
        return None
    deg, mint, sec, hem = float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4).upper()
    value = deg + mint / 60.0 + sec / 3600.0
    return -value if hem in ("S", "W") else value


def _enrich_landing_centre(feature: dict) -> dict:
    """Copy a pfzMobile feature and add parsed decimal fields for each centre.

    geometry.coordinates is [lon, lat] (verified: X1/Y1 match). When a zone
    is issued (forecast == "Y") the PFZ point is parsed from PLatitude/
    PLongitude so downstream agents get a float point, not DMS text.
    """
    props = dict(feature.get("properties") or {})
    coords = feature.get("geometry", {}).get("coordinates") or [None, None]
    props["lon"] = float(coords[0]) if coords[0] is not None else None
    props["lat"] = float(coords[1]) if coords[1] is not None else None

    is_issued = str(props.get("forecast", "")).strip().upper() == "Y"
    plat, plon = dms_to_decimal(props.get("PLatitude")), \
        dms_to_decimal(props.get("PLongitude"))
    props["pfz_lat"] = plat
    props["pfz_lon"] = plon
    props["pfz_issued"] = bool(is_issued and plat is not None and plon is not None)

    # Guard against unharmonised raw fields reaching agents.
    props.setdefault("Direction", "-")
    props.setdefault("Distance", "-")
    props.setdefault("Depth", "-")
    props.setdefault("SECTOR_ID", "SEC001")
    props.setdefault("STATENAME", "")
    props.setdefault("LANDINGNAM", "Unknown")

    cleaned = {
        "type": feature.get("type", "Feature"),
        "properties": props,
        "geometry": feature.get("geometry", {}),
    }
    return cleaned


# ---------------------------------------------------------------------------
# Public fetch helpers (each cached independently)
# ---------------------------------------------------------------------------

async def get_pfz_lines() -> dict:
    """Official PFZ zone LineStrings (GeoJSON FeatureCollection)."""
    cached = _cache_get("pfz_lines")
    if cached is not None:
        return cached
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        fc = await _get_json(client, PFZ_LINES_URL)
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        raise IncoisUnavailableError("pfzLines did not return a FeatureCollection")
    _cache_set("pfz_lines", fc)
    return fc


async def get_pfz_mobile() -> dict:
    """Landing centres + per-centre daily advisory (GeoJSON FeatureCollection)."""
    cached = _cache_get("pfz_mobile")
    if cached is not None:
        return cached
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        fc = await _get_json(client, PFZ_MOBILE_URL)
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        raise IncoisUnavailableError("pfzMobile did not return a FeatureCollection")
    fc["features"] = [_enrich_landing_centre(f) for f in fc.get("features", [])]
    _cache_set("pfz_mobile", fc)
    return fc


async def _parse_advisory_home(html: str) -> dict:
    """Pull forecast/valid-upto dates and the sector link table from the page."""
    advisory: dict = {
        "forecast_date": None,
        "valid_upto": None,
        "source_url": ADVISORY_HOME_URL,
        "sectors": {},
    }

    # Dates: the header row reads "Forecast Date | Valid upto"; the following
    # row holds the two dates in that same order.
    idx = html.lower().find("forecast date")
    if idx >= 0:
        dates = re.findall(
            r">\s*(\d{1,2}\s+[A-Z]{3}\s+\d{4})\s*<", html[idx: idx + 800], re.I
        )
        if dates:
            advisory["forecast_date"] = dates[0]
        if len(dates) >= 2:
            advisory["valid_upto"] = dates[1]

    # Sector name table: the sector dropdown (<option ...>NAME</option>).
    for m in re.finditer(
        r"value='TextData.*?\?secid=(SEC\d+)'[^>]*>([^<]+)</option>", html, re.I
    ):
        advisory["sectors"].setdefault(m.group(1), {"name": m.group(2).strip()})
    # The image-map areas also carry the sector -> coast mapping.
    for m in re.finditer(
        r'TextData\?secid=(SEC\d+)"[^>]*alt="([^"]+)"', html, re.I
    ):
        advisory["sectors"].setdefault(m.group(1), {"name": m.group(2)})
    return advisory


def _strip_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _fetch_sector_text(client: httpx.AsyncClient, secid: str) -> str:
    # The per-sector page is a session-protected query form: get the app
    # JSESSIONID cookie from the advisory home page, then POST the query (with
    # km/meters units) exactly like the WebGIS does. A naked GET just returns
    # the generic query page. Response carries the raw advisory bulb, e.g.
    # "SATELLITE DATA SHOWS LIKELY AVAILABILITY OF FISH STOCK TILL 29 AUG 2026"
    # plus the per-centre Direction/Bearing/Distance/Depth/DMS table.
    await _get_text(client, ADVISORY_HOME_URL)
    try:
        resp = await client.post(
            SECTOR_FORM_URL,
            data={"secid": secid, "distance": "km", "depth": "meters"},
            headers={**_HEADERS, "Referer": ADVISORY_HOME_URL},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IncoisUnavailableError(f"sector text {secid}: {exc}") from exc
    text = _strip_html(resp.text).replace("\u00a0", " ")
    marker = text.find("SATELLITE DATA")
    return (text[marker:] if marker >= 0 else text)[:_MAX_SECTOR_TEXT_CHARS]


async def get_pfz_advisory(sector_ids: list[str] | None = None) -> dict:
    """Today's advisory metadata + optional per-sector narrative text.

    Always fetches the advisory home page (forecast date, valid-upto date and
    the sector->name table). When `sector_ids` is given, the official text for
    each of those sectors is fetched too and cached under the sector id.
    """
    key = "advisory_home"
    cached = _cache_get(key)
    if cached is None:
        async with httpx.AsyncClient(headers=_HEADERS) as client:
            home = await _get_text(client, ADVISORY_HOME_URL)
        advisory = await _parse_advisory_home(home)
        _cache_set(key, advisory)
    else:
        advisory = cached

    wanted = [s for s in (sector_ids or []) if s]
    if not wanted:
        return advisory

    async with httpx.AsyncClient(headers=_HEADERS) as client:
        for secid in wanted:
            text_key = f"advisory_sector:{secid}"
            cached_text = _cache_get(text_key)
            if cached_text is not None:
                advisory["sectors"].setdefault(secid, {})["text"] = cached_text
                continue
            try:
                text = await _fetch_sector_text(client, secid)
            except IncoisUnavailableError as exc:
                logger.warning("sector text %s unavailable: %s", secid, exc)
                continue
            _cache_set(text_key, text)
            advisory["sectors"].setdefault(secid, {})["text"] = text
    return advisory


async def get_live_pfz(sector_ids: list[str] | None = None) -> dict:
    """Combined live PFZ payload: zone lines + landing centres (parallel) +
    advisory (best-effort). Raises IncoisUnavailableError only when BOTH
    geometric sources fail.

    Returns:
        {
            "pfz_lines": FeatureCollection | None,
            "landing_centres": FeatureCollection | None,
            "advisory": dict,
            "fetched_at": ISO-8601 UTC,
            "cache_ttl_s": 600,
            "available": ["lines", "mobile", "advisory"],
        }
    """
    available: list[str] = []
    lines = None
    mobile = None
    try:
        lines, mobile = await asyncio.gather(
            get_pfz_lines(), get_pfz_mobile(), return_exceptions=True,
        )
    except IncoisUnavailableError:
        lines = None
    # asyncio.gather with return_exceptions=True never raises; unwrap.
    for label, value in (("lines", lines), ("mobile", mobile)):
        if isinstance(value, BaseException):
            logger.warning("INCOIS %s failed: %s", label, value)
            if label == "lines":
                lines = None
            else:
                mobile = None
    if lines is not None:
        available.append("lines")
    if mobile is not None:
        available.append("mobile")

    advisory = {}
    try:
        advisory = await get_pfz_advisory(sector_ids=sector_ids)
        available.append("advisory")
    except IncoisUnavailableError as exc:
        logger.warning("INCOIS advisory unavailable (continuing with geometry): %s", exc)

    if not available:
        raise IncoisUnavailableError(
            "Both pfzLines and pfzMobile unreachable -- live PFZ unavailable"
        )

    return {
        "pfz_lines": lines,
        "landing_centres": mobile,
        "advisory": advisory,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cache_ttl_s": CACHE_TTL_S,
        "available": available,
    }


def get_live_pfz_sync(sector_ids: list[str] | None = None) -> dict:
    """Synchronous wrapper for agent threads that cannot await."""
    return _run_async(get_live_pfz(sector_ids=sector_ids))


def invalidate_cache() -> None:
    """Drop every cached INCOIS payload (useful for tests/reload)."""
    with _cache_lock:
        _cache.clear()


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Probing INCOIS PFZ feeds (network) ...")
    data = get_live_pfz_sync()
    lines = data.get("pfz_lines") or {}
    mobile = data.get("landing_centres") or {}
    centres = mobile.get("features", []) or []
    issued = [c for c in centres if c["properties"].get("pfz_issued")]
    print(f"lines: {len(lines.get('features', []))}")
    print(f"centres: {len(centres)}, issued zones: {len(issued)}")
    print("advisory:", data.get("advisory", {}).get("forecast_date"),
          "valid", data.get("advisory", {}).get("valid_upto"))
    if issued:
        p = issued[0]["properties"]
        print("sample issued centre:",
              p["LANDINGNAM"], p["STATENAME"], p["SECTOR_ID"],
              f"({p['pfz_lat']}, {p['pfz_lon']})",
              f"dir={p['Direction']} dist={p['Distance']}km depth={p['Depth']}m")