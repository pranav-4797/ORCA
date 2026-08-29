"""
INCOIS Marine WMS connector — single source for OceanStateAgent.

Replaces every Open-Meteo dependency. Uses official INCOIS THREDDS WMS
endpoints verified from GetCapabilities. All fetches use GetFeatureInfo
with text/plain and a small 0.05° bbox around the target coordinate,
matching INCOIS WebGIS (WIDTH=11 HEIGHT=11 X=5 Y=5 SRS=CRS:84).

Endpoints:
  SST:     https://incois.gov.in/thredds/wms/osf/winds/SST_NIO_{YYYYMMDD}.nc  LAYERS=SST
  WW3:     https://incois.gov.in/thredds/wms/osf/ww3/rsmc_combined_ww3_{YYYYMMDD}.nc  LAYERS=UWND:VWND-mag / UWND:VWND-group / PHS01
  CURRENTS:https://incois.gov.in/thredds/wms/osf/currents/CURRENTS_NIO_{YYYYMMDD}.nc  LAYERS=CURRENT
  CHL:     https://erddap.incois.gov.in/erddap/wms/incois_oceansat2_datasets/request  LAYERS=incois_oceansat2_datasets:CHL

Caching: 10 min per (lat,lon,forecast_time.date)
Concurrency: asyncio.gather (ThreadPool fallback via _run_async)
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
import socket
import urllib.parse
import urllib.request
from concurrent.futures import TimeoutError as ConcurrentTimeoutError
from datetime import datetime, timezone, timedelta

import logging

logger = logging.getLogger("orca.incois_marine")

CACHE_TTL_S = 600
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()

DELTA = 0.05
WIDTH = 11
HEIGHT = 11
X = 5
Y = 5

# Dataset URL templates
SST_URL_TMPL = "https://incois.gov.in/thredds/wms/osf/winds/SST_NIO_{yyyymmdd}.nc"
WW3_URL_TMPL = "https://incois.gov.in/thredds/wms/osf/ww3/rsmc_combined_ww3_{yyyymmdd}.nc"
CURRENT_URL_TMPL = "https://incois.gov.in/thredds/wms/osf/currents/CURRENTS_NIO_{yyyymmdd}.nc"

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

def _compass_from_deg(deg: float) -> str:
    return COMPASS[int((deg % 360) / 45 + 0.5) % 8]

def _cache_get(key):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() < hit[0]:
            return hit[1]
        if hit:
            del _cache[key]
        return None

def _cache_set(key, val):
    with _cache_lock:
        _cache[key] = (time.monotonic() + CACHE_TTL_S, val)

def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")

def _bbox(lon: float, lat: float):
    return (lon - DELTA, lat - DELTA, lon + DELTA, lat + DELTA)

def _wms_params(layer: str, bbox, time_iso: str | None = None) -> dict:
    minx, miny, maxx, maxy = bbox
    p = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": layer,
        "QUERY_LAYERS": layer,
        "STYLES": "",
        "SRS": "CRS:84",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": str(WIDTH),
        "HEIGHT": str(HEIGHT),
        "X": str(X),
        "Y": str(Y),
        "INFO_FORMAT": "text/plain",
        "FORMAT": "image/png",
    }
    if time_iso:
        p["TIME"] = time_iso
    return p

def _extract_field(text: str, keyword: str) -> float | None:
    """Field-specific parsing: find line containing the exact layer keyword and
    extract its numeric value. As a safe fallback for INCOIS THREDDS GetFeatureInfo
    format (which uses 'Value: <num>' on its own line without the layer name),
    also checks the explicit 'Value:' line — but never a generic last-number
    fallback that would leak lat/lon into SST/swell."""
    m = re.search(rf"\b{re.escape(keyword)}\b\s*[:=]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", text, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    for line in text.splitlines():
        if re.search(rf"\b{re.escape(keyword)}\b", line, re.I):
            after = line.split(keyword, 1)[1]
            m2 = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", after)
            if m2:
                try:
                    return float(m2.group())
                except ValueError:
                    pass
            m3 = re.search(rf"\b{re.escape(keyword)}\b[^\d-]*([-+]?\d*\.?\d+)", line, re.I)
            if m3:
                try:
                    return float(m3.group(1))
                except ValueError:
                    pass
    # INCOIS THREDDS GetFeatureInfo fallback: explicit 'Value:' line holds the data value
    for line in text.splitlines():
        if re.match(r"\s*Value\s*[:=]", line, re.I):
            after = line.split(":", 1)[1] if ":" in line else line.split("=", 1)[1]
            # Handle truncated '28.' -> '28.0'
            after = after.strip()
            if after.endswith("."):
                after += "0"
            m4 = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", after)
            if m4:
                try:
                    return float(m4.group())
                except ValueError:
                    pass
    return None

def _extract_sst(text: str) -> float | None:
    return _extract_field(text, "SST")

def _extract_wind_mag(text: str) -> float | None:
    # Try mag-specific
    v = _extract_field(text, "mag")
    if v is not None:
        return v
    v = _extract_field(text, "wind")
    if v is not None:
        return v
    # fallback to UWND
    v = _extract_field(text, "UWND")
    if v is not None:
        return v
    return None

def _extract_current(text: str) -> float | None:
    v = _extract_field(text, "CURRENT")
    if v is not None:
        return v
    v = _extract_field(text, "current")
    return v

def _extract_swell(text: str) -> float | None:
    v = _extract_field(text, "PHS01")
    if v is not None:
        return v
    v = _extract_field(text, "swell")
    return v

def _extract_chl(text: str) -> float | None:
    v = _extract_field(text, "CHL")
    if v is not None:
        return v
    v = _extract_field(text, "chlorophyll")
    return v

def _extract_uv(text: str) -> tuple[float | None, float | None]:
    """Extract real U (east) and V (north) wind components from the WMS text.
    Only accepts explicit UWND/VWND (or U/V) labelled values. NEVER guesses
    from arbitrary numbers in the response."""
    u = None
    v = None
    um = re.search(r"\bUWND\b\s*[:=]\s*([-+]?\d*\.?\d+)", text, re.I)
    vm = re.search(r"\bVWND\b\s*[:=]\s*([-+]?\d*\.?\d+)", text, re.I)
    if um and vm:
        try:
            return float(um.group(1)), float(vm.group(1))
        except ValueError:
            pass
    # Whole line that carries both U and V labels
    for line in text.splitlines():
        uu = re.search(r"\bU\b\s*[:=]\s*([-+]?\d*\.?\d+)", line, re.I)
        vv = re.search(r"\bV\b\s*[:=]\s*([-+]?\d*\.?\d+)", line, re.I)
        if uu and vv:
            try:
                return float(uu.group(1)), float(vv.group(1))
            except ValueError:
                pass
    return u, v

def _validate(field: str, value: float | None) -> bool:
    if value is None:
        return False
    ranges = {
        "sst": (20, 35),
        "wind_ms": (0, 40),
        "wind_kmh": (0, 144),
        "current": (0, 5),
        "swell": (0, 15),
        "chlorophyll": (0, 50),
    }
    lo, hi = ranges.get(field, (float("-inf"), float("inf")))
    return lo <= value <= hi

def _fetch_wms_text(base_url: str, layer: str, lon: float, lat: float, time_iso: str | None = None, timeout: float = 8) -> str:
    bbox = _bbox(lon, lat)
    params = _wms_params(layer, bbox, time_iso)
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "orca-incois-marine/1.0"})
    logger.info("WMS fetch %s layer=%s bbox=%.3f,%.3f", base_url.split("/")[-1], layer, lat, lon)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", resp.code if hasattr(resp, "code") else 200)
        logger.info("[%s] URL=%s", layer, url)
        logger.info("[%s] HTTP=%s", layer, status)
        return resp.read().decode("utf-8", errors="replace")

def _try_dates_text(base_tmpl: str, layer: str, lon: float, lat: float, forecast_time: datetime, timeout: float = 8) -> str | None:
    """Fetch the layer's raw WMS text for the requested forecast date.
    Coordinates are used exactly as given (map-tap / GPS / geocoded point) —
    no coordinate snapping or offshore projection is applied here.

    Date resolution (A5): the requested forecast date is tried FIRST. A
    different date is only used when the requested date's dataset does not
    exist yet (e.g. forecast for tomorrow when tomorrow's NC is unpublished),
    in which case we fall back to the latest available dataset (yesterday).
    The most recent published dataset is preferred over a far-future one.
    """
    def _dates():
        # requested forecast date -> previous -> next
        seen: set[str] = set()
        out: list[datetime] = []
        for delta in (0, -1, 1):
            d = forecast_time + timedelta(days=delta)
            k = _yyyymmdd(d)
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out

    for d in _dates():
        yyyymmdd = _yyyymmdd(d)
        base_url = base_tmpl.format(yyyymmdd=yyyymmdd)
        time_iso = d.strftime("%Y-%m-%dT00:00:00Z")
        # Try the exact forecast hour, then 00:00Z of that date
        times = [forecast_time.strftime("%Y-%m-%dT%H:%M:%SZ"), time_iso]
        for t in times:
            if not t:
                continue
            try:
                text = _fetch_wms_text(base_url, layer, lon, lat, t, timeout=timeout)
                # INCOIS returns "Clicked:\n Longitude: ..\n Latitude: .." with no
                # data value on land / outside the grid — reject before parsing.
                if "Clicked" in text and len(re.findall(r"[-+]?\d*\.?\d+", text)) <= 2:
                    continue
                if text and "no data" not in text.lower():
                    return text
            except Exception as e:
                logger.warning("WMS %s %s failed for %s: %s", base_url, layer, yyyymmdd, e)
                continue
    return None

def _try_dates(base_tmpl: str, layer: str, lon: float, lat: float, forecast_time: datetime, timeout: float = 8) -> tuple[str | None, float | None]:
    text = _try_dates_text(base_tmpl, layer, lon, lat, forecast_time, timeout)
    if text is None:
        return None, None
    # Field-specific parsing ONLY — never a generic last-number fallback.
    val = _extract_field(text, layer.split(":")[-1].split("_")[0])
    return text, val

def _fetch_sst(lon: float, lat: float, ft: datetime) -> dict:
    text = _try_dates_text(SST_URL_TMPL, "SST", lon, lat, ft)
    if text is None:
        logger.info("[SST] HTTP=FAIL")
        logger.info("[SST] Parsed=None")
        raise ValueError(f"SST unavailable for {lat},{lon}")
    val = _extract_sst(text)
    if val is None or not _validate("sst", val):
        logger.warning("SST sanity failed %s for %.3f,%.3f raw=%s", val, lat, lon, text[:120])
        # Retry once at next hour
        text2 = _try_dates_text(SST_URL_TMPL, "SST", lon, lat, (ft + timedelta(hours=1)) if ft else ft)
        if text2:
            v2 = _extract_sst(text2)
            if v2 is not None and _validate("sst", v2):
                logger.info("[SST] Parsed=%.2f", v2)
                return {"sst": round(float(v2), 2), "raw": text2}
        logger.info("[SST] Parsed=None")
        raise ValueError(f"SST value not found / out of range for {lat},{lon}")
    logger.info("[SST] Parsed=%.2f", val)
    return {"sst": round(float(val), 2), "raw": text}

def _fetch_wind_speed(lon: float, lat: float, ft: datetime) -> dict:
    text = _try_dates_text(WW3_URL_TMPL, "UWND:VWND-mag", lon, lat, ft)
    if text is None:
        logger.info("[Wind] HTTP=FAIL")
        logger.info("[Wind] Parsed=None")
        raise ValueError(f"Wind speed unavailable for {lat},{lon}")
    val = _extract_wind_mag(text)
    if val is None or not _validate("wind_ms", val):
        logger.warning("Wind sanity failed %s for %.3f,%.3f", val, lat, lon)
        text2 = _try_dates_text(WW3_URL_TMPL, "UWND:VWND-mag", lon, lat, (ft + timedelta(hours=1)) if ft else ft)
        if text2:
            v2 = _extract_wind_mag(text2)
            if v2 is not None and _validate("wind_ms", v2):
                kmh = float(v2) * 3.6
                logger.info("[Wind] Parsed=%.2f km/h", kmh)
                return {"wind_speed": round(kmh, 2), "raw": text2}
        logger.info("[Wind] Parsed=None")
        raise ValueError(f"Wind speed value not found / out of range for {lat},{lon}")
    kmh = float(val) * 3.6
    logger.info("[Wind] Parsed=%.2f km/h", kmh)
    return {"wind_speed": round(kmh, 2), "raw": text}

def _fetch_wind_vector(lon: float, lat: float, ft: datetime) -> dict:
    text = _try_dates_text(WW3_URL_TMPL, "UWND:VWND-group", lon, lat, ft)
    if text is None:
        logger.info("[Wind Direction] HTTP=FAIL")
        raise ValueError(f"Wind vector unavailable for {lat},{lon}")
    u, v = _extract_uv(text or "")
    if u is None or v is None:
        logger.info("[Wind Direction] Parser failed")
        raise ValueError(f"Wind vector value not found for {lat},{lon}")
    mag = (u*u + v*v) ** 0.5
    if not _validate("wind_ms", mag):
        logger.warning("Wind vector sanity failed mag %s", mag)
        logger.info("[Wind Direction] Parser failed")
        raise ValueError(f"Wind vector sanity failed mag {mag}")
    import math
    deg = (math.degrees(math.atan2(u, v)) + 360) % 360
    direction = _compass_from_deg(deg)
    logger.info("[Wind Direction] Parsed=%s (%s°)", direction, round(deg, 1))
    return {"wind_direction": direction, "u": u, "v": v, "wind_direction_deg": round(deg, 1), "raw": text}

def _fetch_current(lon: float, lat: float, ft: datetime) -> dict:
    text = _try_dates_text(CURRENT_URL_TMPL, "CURRENT", lon, lat, ft)
    if text is None:
        logger.info("[Current] HTTP=FAIL")
        logger.info("[Current] Parsed=None")
        raise ValueError(f"Current unavailable for {lat},{lon}")
    val = _extract_current(text)
    if val is None or not _validate("current", val):
        logger.warning("Current sanity failed %s", val)
        logger.info("[Current] Parsed=None")
        raise ValueError(f"Current value not found / out of range for {lat},{lon}")
    logger.info("[Current] Parsed=%.3f", val)
    return {"surface_current": round(float(val), 3), "raw": text}

def _fetch_swell(lon: float, lat: float, ft: datetime) -> dict:
    text = _try_dates_text(WW3_URL_TMPL, "PHS01", lon, lat, ft)
    if text is None:
        logger.info("[Swell] HTTP=FAIL")
        logger.info("[Swell] Parsed=None")
        raise ValueError(f"Swell unavailable for {lat},{lon}")
    val = _extract_swell(text)
    if val is None or not _validate("swell", val):
        logger.warning("Swell sanity failed %s", val)
        logger.info("[Swell] Parser failed")
        raise ValueError(f"Swell value not found / out of range for {lat},{lon}")
    logger.info("[Swell] Parsed=%.2f", val)
    return {"primary_swell_height": round(float(val), 2), "raw": text}

# --- Dedicated ERDDAP chlorophyll client (Part A3) -------------------------
# Uses the official INCOIS OceanSat-2 service with its own request builder.
# Supports GetFeatureInfo (numeric value) and exposes GetMap for heatmaps.
ERDDAP_CHL_BASE = "https://erddap.incois.gov.in/erddap/wms/incois_oceansat2_datasets/request"
ERDDAP_CHL_LAYER = "incois_oceansat2_datasets:CHL"


def _erddap_chl_params(bbox, time_iso: str | None, request: str = "GetFeatureInfo", width: int = WIDTH, height: int = HEIGHT, x: int = X, y: int = Y) -> dict:
    minx, miny, maxx, maxy = bbox
    p = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": request,
        "LAYERS": ERDDAP_CHL_LAYER,
        "QUERY_LAYERS": ERDDAP_CHL_LAYER,
        "STYLES": "",
        "SRS": "CRS:84",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "FORMAT": "image/png",
    }
    if request == "GetFeatureInfo":
        p.update({"WIDTH": str(width), "HEIGHT": str(height), "X": str(x), "Y": str(y), "INFO_FORMAT": "text/plain"})
    if time_iso:
        p["TIME"] = time_iso
    return p


def _fetch_chlorophyll(lon: float, lat: float, ft: datetime) -> dict:
    """Real OceanSat-2 chlorophyll — GetFeatureInfo on the dedicated client.
    Uses exactly the given coordinate (map-tap / GPS / geocoded). Never
    simulated, never a generic number fallback."""
    import ssl
    bbox = _bbox(lon, lat)
    time_iso = ft.strftime("%Y-%m-%dT%H:%M:%SZ") if ft else None
    params = _erddap_chl_params(bbox, time_iso)
    url = f"{ERDDAP_CHL_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "orca-incois-marine/1.0"})
    logger.info("WMS fetch chlorophyll bbox=%.3f,%.3f", lat, lon)
    ctx = ssl._create_unverified_context()  # ERDDAP self-signed cert on some networks
    try:
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            logger.info("[Chlorophyll] URL=%s", url)
            logger.info("[Chlorophyll] HTTP=%s", getattr(resp, "status", getattr(resp, "code", 200)))
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        logger.info("[Chlorophyll] URL=%s", url)
        logger.info("[Chlorophyll] HTTP=FAIL")
        raise
    val = _extract_chl(text)
    if val is None or not _validate("chlorophyll", val):
        logger.info("[Chlorophyll] Parser failed")
        raise ValueError(f"Chlorophyll value not found / out of range for {lat},{lon}")
    logger.info("[Chlorophyll] Parsed=%.2f", val)
    return {"chlorophyll": round(float(val), 2), "raw": text}

async def _async_fetch(coro_func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: coro_func(*args))

async def get_marine_snapshot_async(latitude: float, longitude: float, forecast_time: datetime | None = None) -> dict:
    if forecast_time is None:
        forecast_time = datetime.now(timezone.utc)
    if forecast_time.tzinfo is None:
        forecast_time = forecast_time.replace(tzinfo=timezone.utc)
    key = (round(latitude, 3), round(longitude, 3), forecast_time.strftime("%Y-%m-%d"))
    cached = _cache_get(key)
    if cached:
        logger.info("Cache hit for marine snapshot %.3f,%.3f %s", latitude, longitude, key[2])
        return cached
    logger.info("Cache miss for marine snapshot %.3f,%.3f %s", latitude, longitude, key[2])
    # Fetch concurrently
    results = await asyncio.gather(
        _async_fetch(_fetch_sst, longitude, latitude, forecast_time),
        _async_fetch(_fetch_wind_speed, longitude, latitude, forecast_time),
        _async_fetch(_fetch_wind_vector, longitude, latitude, forecast_time),
        _async_fetch(_fetch_current, longitude, latitude, forecast_time),
        _async_fetch(_fetch_swell, longitude, latitude, forecast_time),
        _async_fetch(_fetch_chlorophyll, longitude, latitude, forecast_time),
        return_exceptions=True,
    )
    # Map results, handle partial failures
    keys = ["sst", "wind_speed", "wind_vector", "current", "swell", "chl"]
    out: dict = {}
    errors = []
    last_timeout: list[str] = []
    for k, r in zip(keys, results):
        if isinstance(r, Exception):
            # Detect timeout distinctly for the INCOIS-timeout log (Part D)
            etype = type(r).__name__
            if isinstance(r, (ConcurrentTimeoutError, socket.timeout, TimeoutError)):
                last_timeout.append(etype)
            logger.warning("Marine fetch %s failed: %s", k, r)
            errors.append(f"{k}: {r}")
            continue
        out.update(r)
        logger.info("INCOIS fetch OK: %s = %s", k, r)
    if last_timeout:
        logger.warning("INCOIS timeout on fields %s for %.3f,%.3f", last_timeout, latitude, longitude)
    # Debug status per field (ORCA_DEBUG_INCOIS=true renders these on the client).
    debug: dict[str, str] = {}
    for k, r in zip(keys, results):
        name = {
            "sst": "SST", "wind_speed": "Wind", "wind_vector": "Wind Direction",
            "current": "Current", "swell": "Swell", "chl": "Chlorophyll",
        }.get(k, k)
        if isinstance(r, Exception):
            if isinstance(r, (ConcurrentTimeoutError, socket.timeout, TimeoutError)):
                debug[name] = "HTTP failed ✗ (timeout)"
            elif "not found" in str(r).lower() or "parser" in str(r).lower():
                debug[name] = "Parser failed ✗"
            elif "range" in str(r).lower():
                debug[name] = "Value out of range ✗"
            else:
                debug[name] = "HTTP failed ✗"
        else:
            debug[name] = "HTTP 200 ✓"
    # Normalize output
    snapshot = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_time": forecast_time.isoformat(),
        "sst": out.get("sst"),
        "wind_speed": out.get("wind_speed"),
        "wind_direction": out.get("wind_direction"),
        "wind_direction_deg": out.get("wind_direction_deg"),
        "surface_current": out.get("surface_current"),
        "primary_swell_height": out.get("primary_swell_height"),
        "chlorophyll": out.get("chlorophyll"),
        "source": "INCOIS_THREDDS_WMS+ERDDAP",
        "debug": debug,
    }
    # Fail field-by-field: never raise for a per-layer outage. Return the
    # snapshot with None placeholders for whichever layers failed; the agent
    # labels each unavailable field individually instead of dropping the rest.
    if snapshot["sst"] is None and snapshot["wind_speed"] is None:
        logger.warning("All INCOIS marine fetches failed for %.3f,%.3f: %s", latitude, longitude, "; ".join(errors))
    # Cache partial once at least one layer succeeded (a total failure is not
    # cached so the next query can retry the live endpoint).
    if snapshot["sst"] is not None or snapshot["wind_speed"] is not None \
            or snapshot["surface_current"] is not None or snapshot["chlorophyll"] is not None \
            or snapshot["primary_swell_height"] is not None:
        _cache_set(key, snapshot)
    return snapshot

def get_marine_snapshot(latitude: float, longitude: float, forecast_time: datetime | None = None) -> dict:
    """Synchronous wrapper for OceanStateAgent (runs in ThreadPool)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(get_marine_snapshot_async(latitude, longitude, forecast_time))
    finally:
        try:
            loop.close()
        except:
            pass

def clear_cache():
    with _cache_lock:
        _cache.clear()
