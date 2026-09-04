"""
ORCA Agent Backend -- FastAPI entrypoint.

Run with:
    uvicorn main:app --reload --port 8000

Then POST to /query:
    curl -X POST http://localhost:8000/query \
         -H "Content-Type: application/json" \
         -d '{"query": "Is it safe to go fishing near Ratnagiri tomorrow morning?"}'

Proactive alerts (PS component #10):
    POST /users/register  {"user_id","lat","lon","phone"?,"language"?}
    GET  /alerts/<user_id>            (poll)
    GET  /alerts/stream/<user_id>     (Server-Sent Events)

Visualisation payloads (P1 #13):
    GET /viz/{session_id}             -> consolidated GeoJSON FeatureCollection
    GET /viz/{session_id}/series      -> hourly chart series for that query
"""

from __future__ import annotations
import asyncio
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import alerts as alert_bus
import sessions as session_store
import storage
from agents.proactive_monitor import (
    ProactiveMonitorAgent,
    get_user,
    list_users,
    register_user,
    unregister_user,
    update_position,
)
from data_connectors.incois_pfz import IncoisUnavailableError, get_live_pfz
from orchestrator import Orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the Proactive Monitor Agent (#10) with the app loop.
    monitor = ProactiveMonitorAgent()
    app.state.monitor = monitor
    monitor.start()
    yield
    await monitor.stop()


app = FastAPI(title="ORCA Agent Backend", version="0.3.0", lifespan=lifespan)

logger = logging.getLogger("orca.main")

# --- CORS / API-key hardening (NFR security) ------------------------------
# CORS_ORIGINS=https://your.domain,https://demo.domain   (default: * for dev)
# ORCA_API_KEY=secret                    (set to require X-API-Key on all
#                                         routes except /health; unset keeps
#                                         the demo open)
_origins_env = os.getenv("CORS_ORIGINS", "").strip()
_allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

_API_KEY = os.getenv("ORCA_API_KEY", "").strip()


@app.middleware("http")
async def _api_key_guard(request, call_next):
    if _API_KEY and request.url.path != "/health":
        if request.headers.get("X-API-Key") != _API_KEY:
            return JSONResponse({"error": "invalid or missing X-API-Key"}, status_code=401)
    return await call_next(request)

orchestrator = Orchestrator()

# Latest response per session, for /viz payloads.
_last_responses: dict[str, object] = {}


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    # Optional live inputs from the client's own device (Tier 1 data).
    device_gps: list[float] | None = None            # [lat, lon]
    # Explicit map-tap coordinate selection (Part A2) — highest priority and
    # never snapped; distinct from device_gps so GPS is only auto-used for
    # "near me" queries.
    map_point: list[float] | None = None             # [lat, lon]
    destination: dict | None = None                  # {"lat": .., "lon": .., "name": optional}
    # "auto"  -> fast intelligent routing, only needed specialists, no round-table unless complex (default).
    # "panel" -> full pipeline: specialists run, hold a round-table discussion, then reconcile (demo).
    # "agent" -> one specialist answers directly (see GET /agents), no discussion round.
    mode: str = "auto"
    agent: str | None = None                         # specialist key for mode="agent"
    # Vessel class selects the safety-threshold envelope (hazard agent):
    # small_fishing_boat (default) | mechanized_trawler | coastal_cargo
    vessel_class: str | None = None
    # Query depth policy for auto mode: auto | fast | standard | deep (overrides ORCA_QUERY_DEPTH)
    query_depth: str | None = None
    # Fleet Convergence demo: low/medium/high/severe — injects SIMULATED fleet activity for demo
    fleet_demo_level: str | None = None
    # Wind Divergence demo: match/moderate/high_divergence — forces a SIMULATED
    # satellite wind observation for the query location (Innovation #4)
    wind_demo_scenario: str | None = None


class RegisterRequest(BaseModel):
    user_id: str
    lat: float
    lon: float
    name: str = ""
    phone: str = ""
    location_name: str = ""
    language: str = "en"
    sms_critical_only: bool = True


class PositionRequest(BaseModel):
    lat: float
    lon: float
    location_name: str = ""


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Lightweight keep-alive health check for Render & external monitors (e.g. UptimeRobot)."""
    return {"status": "ok"}


@app.get("/debug/telemetry")
def debug_telemetry():
    """Lightweight routing telemetry — counters for routing_mode and LLM usage (Task 6)."""
    import routing_telemetry
    return routing_telemetry.get_stats()


@app.get("/debug/telemetry/summary")
def debug_telemetry_summary():
    import routing_telemetry
    return {"summary": routing_telemetry.summary_text()}


@app.get("/agents")
def agents_registry():
    """Addressable specialists for mode='agent' queries. Also describes auto/panel semantics."""
    from orchestrator import SPECIALIST_REGISTRY

    return {
        "default_mode": "auto",
        "modes": {
            "auto": "Fast intelligent routing — ORCA picks needed specialists, skips round-table unless complex",
            "panel": "Full multi-agent deliberation — discussion + synthesis (demo/deep analysis)",
            "agent": "One specialist answers directly, no discussion",
        },
        "agents": [
            {
                "key": key,
                "name": spec["name"],
                "description": spec["description"],
                "requires": spec["requires"],
            }
            for key, spec in SPECIALIST_REGISTRY.items()
        ],
    }


@app.get("/api/pfz/live")
async def pfz_live():
    """Official INCOIS / SAMUDRA PFZ feeds for the map layer:
    - `pfz_lines`     : today's digitized PFZ zone geometry (LineStrings)
    - `landing_centres`: all landing centres; those with `forecast=Y` carry
                        the issued advisory (Direction/Distance/Depth/zone latlon)
    - `advisory`      : forecast/valid dates + per-sector names
    Result is cached server-side for 10 minutes; a failed live refresh keeps
    serving the previous good snapshot until it expires.
    """
    try:
        live = await get_live_pfz()
    except IncoisUnavailableError as exc:
        raise HTTPException(
            503, f"Live PFZ data is temporarily unavailable. ({exc})"
        )
    return {
        "available": live.get("available"),
        "fetched_at": live.get("fetched_at"),
        "forecast_date": (live.get("advisory") or {}).get("forecast_date"),
        "valid_upto": (live.get("advisory") or {}).get("valid_upto"),
        "pfz_lines": live.get("pfz_lines"),
        "landing_centres": live.get("landing_centres"),
        "sectors": (live.get("advisory") or {}).get("sectors", {}),
    }


@app.post("/query")
def query(request: QueryRequest):
    destination = (
        Location(
            name=request.destination.get("name", "Requested Destination"),
            lat=float(request.destination["lat"]),
            lon=float(request.destination["lon"]),
        )
        if request.destination and "lat" in request.destination and "lon" in request.destination
        else None
    )
    device_gps = (
        tuple(float(x) for x in request.device_gps[:2])
        if request.device_gps and len(request.device_gps) >= 2
        else None
    )
    map_point = (
        tuple(float(x) for x in request.map_point[:2])
        if request.map_point and len(request.map_point) >= 2
        else None
    )
    session_id = request.session_id or orchestrator_new_session()

    # Short-TTL cache of identical repeat requests (UI retries / double
    # taps): same query+params within the TTL returns the stored payload.
    # TTL from env ORCA_RESPONSE_CACHE_TTL_S (default 60s for live safety, shorter than session).
    import os as _os
    _ttl = int(_os.getenv("ORCA_RESPONSE_CACHE_TTL_S", "60").strip() or 60)
    cache_key_src = "|".join([
        request.query.strip().lower(), request.mode, request.agent or "",
        request.vessel_class or "", str(device_gps), str(map_point), str(destination),
        session_id, request.query_depth or "", request.fleet_demo_level or "",
        request.wind_demo_scenario or "",
    ])
    cache_key = hashlib.sha256(cache_key_src.encode()).hexdigest()
    # Don't cache demo fleet/wind queries — they are meant to change with simulated levels
    use_cache = not request.fleet_demo_level and not request.wind_demo_scenario
    cached = storage.response_cache.get(cache_key) if use_cache else None
    if cached is not None:
        return cached

    response = orchestrator.handle_query(
        request.query,
        session_id,
        device_gps=device_gps,
        map_point=map_point,
        destination=destination,
        mode=request.mode,
        target_agent=request.agent,
        vessel_class=request.vessel_class,
        query_depth=request.query_depth,
        fleet_demo_level=request.fleet_demo_level,
        wind_demo_scenario=request.wind_demo_scenario,
    )
    _last_responses[session_id] = response
    payload = _serialize(response)
    if isinstance(payload, dict):
        payload["session_id"] = session_id
        storage.response_cache.set(cache_key, payload, ttl_s=_ttl)
    return payload


def orchestrator_new_session() -> str:
    import uuid
    return str(uuid.uuid4())


@app.post("/query/voice")
async def query_voice(
    audio: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    mode: str = Form(default="panel"),
    agent: str | None = Form(default=None),
    device_gps: str | None = Form(default=None),
    map_point: str | None = Form(default=None),
):
    """Voice query path (PS Sec 17): uploaded mic audio -> hosted Whisper STT
    -> the exact same multi-agent graph -> JSON answer (client speaks it)."""
    import llm_client

    try:
        transcript = llm_client.transcribe_audio(
            await audio.read(),
            filename=audio.filename or "speech.webm",
            mime_type=audio.content_type or "audio/webm",
        )
    except llm_client.LLMUnavailableError as exc:
        raise HTTPException(503, f"Speech-to-text unavailable: {exc}")

    sid = session_id or orchestrator_new_session()

    def _pair(s: str | None):
        if not s:
            return None
        parts = s.split(",")
        if len(parts) >= 2:
            try:
                return (float(parts[0]), float(parts[1]))
            except ValueError:
                return None
        return None

    response = await asyncio.to_thread(
        orchestrator.handle_query,
        transcript, sid, mode=mode, target_agent=agent,
        device_gps=_pair(device_gps), map_point=_pair(map_point),
    )
    _last_responses[sid] = response
    payload = _serialize(response)
    if isinstance(payload, dict):
        payload["session_id"] = sid
        payload["transcribed_text"] = transcript
    return payload


# ---------------------------------------------------------------------------
# User registry + proactive alerts (PS component #10 delivery channels)
# ---------------------------------------------------------------------------

# Cached dashboard entries per user/location, with short TTL so subsequent
# card taps don't re-fetch INCOIS / Bhuvan every time. ORCA_DASHBOARD_TTL_S
# default 120s matches the ocean-state agent TTL.
_DASHBOARD_TTL_S = int(os.getenv("ORCA_DASHBOARD_TTL_S", "120").strip() or 120)


def _dashboard_cache_key(user_key: str, lat: float, lon: float) -> str:
    return f"{user_key or 'anon'}|{round(lat, 3):.3f}|{round(lon, 3):.3f}"


async def _gather_dashboard_inputs(location: "Location", time_window: str,
                                 vessel_class: str = "small_fishing_boat"):
    """Run OceanState / PFZ / Hazard in parallel; never raise.

    Each agent has its own 2-minute in-process cache, so a back-to-back
    /dashboard call is essentially free. The four-thread pool limit on
    OceanState's INCOIS fetch is the latency ceiling, not the LLM.

    The three specialist calls run in parallel via asyncio.gather. PFZ
    depends on OceanState, so it is sequenced after, but Hazard also reads
    OceanState and is run in parallel with PFZ.
    """
    from agents.dashboard_agent import build_dashboard
    from agents.hazard_agent import HazardAgent
    from agents.ocean_state_agent import OceanStateAgent
    from agents.pfz_agent import PFZAgent
    from agents.narrative import compose_briefing
    from data_connectors.geocode import reverse_geocode
    import memory as memory_pkg
    import memory.memory_service as memory_service

    ocean_agent = OceanStateAgent()
    pfz_agent = PFZAgent()
    hazard_agent = HazardAgent()

    try:
        ocean, _ = await asyncio.to_thread(ocean_agent.run, location, time_window)
    except Exception as exc:
        logger.warning("dashboard ocean fetch failed: %s", exc)
        ocean = None

    async def _pfz():
        try:
            return await asyncio.to_thread(
                pfz_agent.run, location, ocean, time_window
            )
        except Exception as exc:
            logger.warning("dashboard pfz fetch failed: %s", exc)
            return None

    async def _hazard():
        try:
            return await asyncio.to_thread(
                hazard_agent.run, ocean, vessel_class
            )
        except Exception as exc:
            logger.warning("dashboard hazard fetch failed: %s", exc)
            return None

    pfz, risk = await asyncio.gather(_pfz(), _hazard())

    return {
        "ocean": ocean,
        "pfz": pfz,
        "risk": risk,
        "build_dashboard": build_dashboard,
        "compose_briefing": compose_briefing,
        "reverse_geocode": reverse_geocode,
        "memory_pkg": memory_pkg,
        "memory_service": memory_service,
    }


def _ocean_summary(ocean) -> dict:
    """Flat dict of live ocean fields, only ones that are actually populated.

    Used by the dashboard so the briefing LLM can quote the figures without
    being handed internal agent objects.
    """
    if ocean is None:
        return {}
    out: dict = {}
    fs = getattr(ocean, "field_sources", {}) or {}
    for f in ("sst_celsius", "wave_height_m", "primary_swell_height_m",
              "wind_speed_kmh", "wind_gust_kmh", "wind_direction",
              "wind_direction_deg", "surface_current_mps", "tide_level_m",
              "visibility_km", "chlorophyll_mg_m3"):
        v = getattr(ocean, f, None)
        if v is None or str(fs.get(f, "")) == "unavailable":
            continue
        out[f] = v
    return out


def _pfz_summary(pfz) -> dict:
    if pfz is None:
        return {}
    out: dict = {}
    for f in ("distance_from_reference_km", "bearing_deg", "sst_at_zone_celsius"):
        v = getattr(pfz, f, None)
        if v is not None:
            out[f] = v
    return out


def _hazard_summary(risk) -> tuple[str | None, dict]:
    if risk is None:
        return None, {}
    status = str(getattr(getattr(risk, "status", None), "value",
                         getattr(risk, "status", "")) or "")
    out: dict = {"status": status}
    flags = []
    for flag in (getattr(risk, "flags", None) or []):
        label = getattr(flag, "label", None) or (flag.get("label") if isinstance(flag, dict) else None)
        detail = getattr(flag, "detail", None) or (flag.get("detail") if isinstance(flag, dict) else None)
        if label:
            flags.append({"label": str(label), "detail": str(detail or "")})
    if flags:
        out["flags"] = flags
    if getattr(risk, "cap_polygons", None):
        out["cap_alerts"] = len(risk.cap_polygons)
    return status, out


@app.post("/users/register")
async def users_register(req: RegisterRequest):
    user = await register_user(
        req.user_id, req.lat, req.lon, name=req.name, phone=req.phone,
        location_name=req.location_name, language=req.language,
        sms_critical_only=req.sms_critical_only,
    )
    # Immediate first evaluation so registration itself surfaces any active danger.
    pushed = []
    try:
        pushed = [a.as_dict() for a in await app.state.monitor.check_now(req.user_id)]
    except Exception as exc:  # never block registration on a failed check
        pushed = [{"error": str(exc)[:200]}]
    return {"registered": True, "user": user, "immediate_alerts": pushed}


@app.get("/users")
def users_list():
    return {"users": list_users(), "sms_enabled": alert_bus.sms_enabled()}


@app.delete("/users/{user_id}")
async def users_delete(user_id: str):
    ok = await unregister_user(user_id)
    if not ok:
        raise HTTPException(404, "unknown user")
    return {"removed": ok}


@app.post("/users/{user_id}/position")
async def users_position(user_id: str, req: PositionRequest):
    if not update_position(user_id, req.lat, req.lon, req.location_name):
        raise HTTPException(404, "unknown user")
    return {"updated": True}


# ---------------------------------------------------------------------------
# "Before You Sail" Dashboard (P0 #14 from gap analysis)
# ---------------------------------------------------------------------------
# The dashboard is what the fisher sees on app open. It serves:
#   * A ranked list of live cards (PFZ, SST, Wind, Current, Tide, Hazard)
#   * The Today's Fishing Readiness score (0-100) with per-factor breakdown
#   * One localized briefing paragraph + 2 one-sentence notes
#   * Quick-action chips that internally dispatch the same query
#
# The agent calls (ocean, pfz, hazard) run in parallel; the briefing LLM is
# a single follow-up call reusing the SAME hard-rules contract used for full
# /query answers, so the dashboard cannot fabricate a figure either.
#
# `user_key` (optional) loads the registered fisher's saved position and
# language; otherwise the call must supply `lat`/`lon`/`language` inline.

class DashboardRequest(BaseModel):
    user_key: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    language: str = "en"
    time_window: str = "today"
    vessel_class: str = "small_fishing_boat"
    # Skip the LLM briefing (cards + readiness only). Useful for first paint.
    skip_briefing: bool = False


def _resolve_dashboard_point(req: "DashboardRequest") -> "Location | None":
    """Pick a Location for the dashboard: registered user first, then inline."""
    if req.user_key:
        saved = get_user(req.user_key)
        if saved:
            return Location(
                name=saved.get("location_name") or req.location_name or "Saved position",
                lat=float(saved["lat"]),
                lon=float(saved["lon"]),
            )
    if req.lat is not None and req.lon is not None:
        return Location(
            name=req.location_name or f"{float(req.lat):.4f}, {float(req.lon):.4f}",
            lat=float(req.lat), lon=float(req.lon),
        )
    return None


@app.post("/dashboard")
async def dashboard(req: DashboardRequest):
    """One-shot smart dashboard for the fisher's first screen.

    Resolves the location from the registered user (if `user_key` given) or
    inline `lat`/`lon`, then returns the live, ranked cards, the readiness
    score, and (when the LLM is reachable) one localized briefing paragraph.
    """
    location = _resolve_dashboard_point(req)
    if location is None:
        raise HTTPException(
            400,
            "Provide `user_key` of a registered user, or inline `lat` + `lon`.",
        )

    cache_key = _dashboard_cache_key(req.user_key or "", location.lat, location.lon)
    cached = storage.dashboard_store.get(cache_key) if req.user_key else None
    if cached is not None:
        return cached

    inputs = await _gather_dashboard_inputs(location, req.time_window, req.vessel_class)
    ocean, pfz, risk = inputs["ocean"], inputs["pfz"], inputs["risk"]
    build_dashboard = inputs["build_dashboard"]
    compose_briefing = inputs["compose_briefing"]
    memory_service = inputs["memory_service"]
    reverse_geocode = inputs["reverse_geocode"]

    # Best-effort place name upgrade (geocoder is cached + tolerant of failure)
    if not req.location_name and not req.user_key:
        try:
            upgraded = reverse_geocode(location.lat, location.lon)
            if upgraded:
                location.name = upgraded
        except Exception:
            pass

    mem = memory_service.get(req.user_key) if req.user_key else None
    dashboard = build_dashboard(
        location=location, language=req.language, memory=mem,
        ocean=ocean, pfz=pfz, risk=risk, vessel_class=req.vessel_class,
    )

    # Personalize over time: opening the dashboard credits every visible card
    # weakly. An explicit card tap (below) outweighs the auto-credit.
    if req.user_key:
        try:
            memory_service.observe_safe(
                req.user_key,
                intent="dashboard_open",
                location_name=location.name,
                language=req.language,
                hour=__import__("datetime").datetime.utcnow().hour,
            )
        except Exception:
            pass

    briefing = None
    if not req.skip_briefing and (ocean or pfz or risk):
        try:
            briefing = compose_briefing(
                language=req.language,
                location_name=location.name,
                verdict=str(getattr(getattr(risk, "status", None), "value", "")
                            or "") or None,
                ocean=_ocean_summary(ocean),
                pfz=_pfz_summary(pfz),
                hazard=_hazard_summary(risk)[1],
                cards=dashboard.get("cards"),
                readiness=dashboard.get("readiness"),
            )
        except Exception as exc:
            logger.debug("dashboard briefing failed: %s", exc)
            briefing = None

    payload = {
        "location": {
            "name": location.name,
            "lat": location.lat, "lon": location.lon,
        },
        "language": req.language,
        "time_window": req.time_window,
        "vessel_class": req.vessel_class,
        "cards": dashboard.get("cards", []),
        "omitted_cards": dashboard.get("omitted_cards", []),
        "readiness": dashboard.get("readiness"),
        "hazard_override": dashboard.get("hazard_override", False),
        "briefing": briefing,
        # Quick-action chip definitions (so the client can render shortcuts
        # that map to existing /query intents).
        "quick_actions": [
            {"id": "pfz", "label": "Nearest PFZ", "icon": "fish",
             "query": "Where is the nearest potential fishing zone from here?"},
            {"id": "sst", "label": "SST", "icon": "thermometer",
             "query": "What is the sea-surface temperature here right now?"},
            {"id": "wind", "label": "Wind", "icon": "wind",
             "query": "Wind at current location"},
            {"id": "tide", "label": "Tide", "icon": "tide",
             "query": "Tide at current location"},
        ],
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "cached": False,
    }

    # Cache the full payload (cards + briefing) for the TTL window so a card
    # tap + re-render doesn't re-fetch INCOIS twice.
    if req.user_key:
        try:
            storage.dashboard_store.set(cache_key, payload, ttl_s=_DASHBOARD_TTL_S)
        except Exception:
            pass
    payload["cached"] = False
    return payload


@app.post("/dashboard/invalidate")
async def dashboard_invalidate(req: DashboardRequest):
    """Force a fresh fetch on the next /dashboard call (e.g. after a user
    changes their saved position via /users/{id}/position)."""
    location = _resolve_dashboard_point(req)
    if location is None:
        raise HTTPException(400, "Provide user_key or lat+lon.")
    key = _dashboard_cache_key(req.user_key or "", location.lat, location.lon)
    storage.dashboard_store.delete(key)
    return {"invalidated": True}


@app.post("/dashboard/card-tap")
async def dashboard_card_tap(req: "DashboardRequest", card: str):
    """Called by the client when the fisher taps a card or quick-action chip.

    It (1) records a strong tap signal into MarineMemory so the card will rank
    higher next time, and (2) returns the same full /dashboard payload so the
    UI can re-render with the new ranking immediately.
    """
    if not card or not isinstance(card, str):
        raise HTTPException(400, "card is required (pfz/sst/wind/current/tide/hazard)")
    card = card.strip().lower()
    if card not in ("pfz", "sst", "wind", "current", "tide", "hazard"):
        raise HTTPException(400, f"unknown card: {card}")

    if req.user_key:
        try:
            import memory.memory_service as _ms
            _ms.observe_safe(req.user_key, card=card,
                             location_name=(req.location_name or None),
                             language=req.language,
                             hour=__import__("datetime").datetime.utcnow().hour)
        except Exception:
            pass

    # Reuse the cached payload if available so the tap stays instant.
    location = _resolve_dashboard_point(req)
    if location is not None:
        key = _dashboard_cache_key(req.user_key or "", location.lat, location.lon)
        cached = storage.dashboard_store.get(key) if req.user_key else None
        if cached is not None:
            cached["last_tap"] = card
            return cached
    # Cold path: re-run the full pipeline.
    return await dashboard(req)


@app.get("/alerts/{user_id}")
def alerts_poll(user_id: str, since: float = 0.0):
    found = alert_bus.fetch(user_id, since_ts=since)
    return {"alerts": [a.as_dict() for a in found],
            "server_time": __import__("time").time()}


@app.get("/alerts/stream/{user_id}")
async def alerts_stream(user_id: str):
    """Server-Sent Events stream of proactive alerts for one user."""
    queue = alert_bus.subscribe(user_id)

    async def gen():
        try:
            # Initial comment so clients connect cleanly.
            yield ": connected\n\n"
            while True:
                try:
                    alert = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {alert_bus.json.dumps(alert.as_dict())}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            alert_bus.unsubscribe(user_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Visualisation payloads (P1 #13)
# ---------------------------------------------------------------------------

@app.get("/viz/{session_id}")
def viz_geojson(session_id: str):
    resp = _last_responses.get(session_id)
    if resp is None:
        raise HTTPException(404, "no response stored for this session")
    r = resp

    features: list[dict] = []

    o = getattr(r, "ocean_state", None)
    if o is not None:
        features.append({
            "type": "Feature",
            "properties": {
                "kind": "query_point", "name": o.location.name,
                "status": getattr(r.status, "value", str(r.status)),
            },
            "geometry": {"type": "Point",
                         "coordinates": [o.location.lon, o.location.lat]},
        })

    wind_div = getattr(r, "wind_divergence", None)
    if wind_div and wind_div.get("status") in ("MODERATE_DIVERGENCE", "HIGH_DIVERGENCE") and o is not None:
        features.append({
            "type": "Feature",
            "properties": {
                "kind": "wind_divergence",
                "status": wind_div["status"],
                "forecast_kn": wind_div.get("forecast_wind_kn"),
                "satellite_kn": wind_div.get("satellite_wind_kn"),
                "warning": wind_div.get("warning"),
                "is_simulated": wind_div.get("is_simulated"),
            },
            "geometry": {"type": "Point", "coordinates": [o.location.lon, o.location.lat]},
        })

    pfz = getattr(r, "pfz", None)
    # Fleet convergence — crowding-adjusted candidates (Innovation #1)
    fleet = getattr(r, "fleet_convergence", None)
    if fleet and fleet.get("candidates"):
        for cand in fleet["candidates"]:
            is_rec = cand.get("is_recommended", False)
            kind = "fleet_recommended" if is_rec else "fleet_candidate"
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": kind,
                    "zone_id": cand["zone_id"],
                    "name": f"{cand['zone_id']} {'✓ Recommended' if is_rec else ''}",
                    "base_suitability": cand["base_suitability"],
                    "fleet_count": cand["fleet_count"],
                    "adjusted_suitability": cand["adjusted_suitability"],
                    "crowding_ratio": cand["crowding_ratio"],
                    "crowding_label": cand.get("crowding_label", ""),
                    "status": fleet.get("status", "OK"),
                },
                "geometry": {"type": "Point", "coordinates": [cand["center_lon"], cand["center_lat"]]},
            })
        # Also add raw_best vs final for legend
        if fleet.get("raw_best_zone") and fleet.get("final_zone") and fleet.get("recommendation_changed"):
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "fleet_change",
                    "raw_best": fleet["raw_best_zone"]["zone_id"],
                    "final": fleet["final_zone"]["zone_id"],
                    "reason": fleet.get("change_reason", "")[:120],
                },
                "geometry": {"type": "Point", "coordinates": [fleet["final_zone"]["center_lon"], fleet["final_zone"]["center_lat"]]},
            })
    elif pfz is not None:
        features.append({
            "type": "Feature",
            "properties": {
                "kind": "pfz_primary", "name": "Recommended fishing zone",
                "distance_km": pfz.distance_from_reference_km,
                "bearing_deg": pfz.bearing_deg,
                "sst_celsius": pfz.sst_at_zone_celsius,
                "source": getattr(pfz.source, "value", str(pfz.source)),
            },
            "geometry": {"type": "Point",
                         "coordinates": [pfz.center_lon, pfz.center_lat]},
        })
        lc = getattr(pfz, "landing_center", None)
        if lc:
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "pfz_landing", "name": lc.get("name"),
                    "state": lc.get("state"), "sector_id": lc.get("sector_id"),
                    "direction": lc.get("direction"),
                    "advisory_distance_km": lc.get("advisory_distance_km"),
                    "advisory_depth_m": lc.get("advisory_depth_m"),
                    "pfz_lat": lc.get("pfz_lat"), "pfz_lon": lc.get("pfz_lon"),
                    "distance_km_to_centre": lc.get("distance_km_to_centre"),
                    "forecast_date": lc.get("forecast_date"),
                    "valid_upto": lc.get("valid_upto"),
                    "distance_from_user_km": pfz.distance_from_reference_km,
                    "bearing_from_user_deg": pfz.bearing_deg,
                },
                "geometry": {"type": "Point",
                             "coordinates": [lc.get("centre_lon"), lc.get("centre_lat")]},
            })
        for i, alt in enumerate(getattr(pfz, "alternates", []) or [], start=2):
            features.append({
                "type": "Feature",
                "properties": {"kind": "pfz_alternate", "rank": i,
                               "distance_km": alt["distance_km"],
                               "bearing_deg": alt["bearing_deg"]},
                "geometry": {"type": "Point",
                             "coordinates": [alt["center_lon"], alt["center_lat"]]},
            })

    route = getattr(r, "route", None)
    if route is not None and route.waypoints:
        coords = [[lon, lat] for lat, lon in route.waypoints]
        features.append({
            "type": "Feature",
            "properties": {
                "kind": "route", "algorithm": route.algorithm,
                "distance_km": route.estimated_distance_km,
                "min_depth_m": route.min_depth_m,
                "avoided_zones": route.avoided_zones,
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    risk = getattr(r, "risk", None)
    for poly in (getattr(risk, "cap_polygons", []) or []):
        ring = [[lon, lat] for lat, lon in poly.get("polygon", [])]
        if len(ring) >= 3:
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "cap_hazard", "event": poly.get("event"),
                    "severity": poly.get("severity"),
                    "area_desc": poly.get("area_desc"),
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })

    tourism = getattr(r, "tourism", None)
    if tourism:
        for poi in tourism:
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "tourism_poi",
                    "name": poi.name,
                    "type": poi.type,
                    "status": poi.status.value,
                    "reasoning": poi.reasoning,
                    "confidence": poi.confidence,
                },
                "geometry": {"type": "Point", "coordinates": [poi.lon, poi.lat]},
            })

    geo = getattr(r, "geofence", None)
    if geo is not None:
        for h in geo.hits:
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": "boundary_flag", "zone_name": h.zone_name,
                    "zone_type": h.zone_type, "inside": h.inside_zone,
                    "distance_km": h.distance_to_boundary_km,
                },
                "geometry": {"type": "Point", "coordinates": [
                    getattr(r.ocean_state.location, "lon", None)
                    if r.ocean_state else None,
                    getattr(r.ocean_state.location, "lat", None)
                    if r.ocean_state else None,
                ]},
            })

    # SAR overlay — latest surveillance scan (if any) so OceanMap shows authority picture
    try:
        _sar_latest = _sar_store.get_latest() or _last_sar_scan
        if _sar_latest and _sar_latest.get("detections"):
            for d in _sar_latest["detections"]:
                ms = d.get("match_status", "")
                al = d.get("alert_level", "")
                if ms == "UNKNOWN" and al == "HIGH":
                    kind = "sar_unknown_high"
                elif ms == "UNKNOWN":
                    kind = "sar_unknown"
                elif ms == "KNOWN":
                    kind = "sar_known"
                elif ms == "LOW_CONFIDENCE":
                    kind = "sar_low_confidence"
                else:
                    kind = "sar_other"
                features.append({
                    "type": "Feature",
                    "properties": {
                        "kind": kind,
                        "detection_id": d.get("detection_id") or d.get("id"),
                        "lat": d.get("latitude") or d.get("lat"),
                        "lon": d.get("longitude") or d.get("lon"),
                        "confidence": d.get("confidence"),
                        "distance_to_boundary_km": d.get("distance_to_boundary_km"),
                        "boundary_segment": d.get("boundary_segment"),
                        "match_status": ms,
                        "alert_level": al,
                        "source": d.get("source"),
                        "dataset": d.get("dataset"),
                        "acquisition_timestamp": d.get("acquisition_timestamp") or d.get("acquisition_time"),
                        "status": d.get("status"),
                        "is_near_boundary": d.get("is_near_boundary"),
                    },
                    "geometry": {"type": "Point", "coordinates": [d.get("longitude") or d.get("lon"), d.get("latitude") or d.get("lat")]},
                })
            # Also expose maritime boundary as LineString for map context (from geojson)
            try:
                import json as _json, os as _os
                _bpath = _os.path.join(_os.path.dirname(__file__), "data", "marine_boundaries.geojson")
                with open(_bpath, "r", encoding="utf-8") as _f:
                    _gj = _json.load(_f)
                    for feat in _gj.get("features", [])[:6]:
                        if feat.get("geometry", {}).get("type") == "LineString":
                            features.append({
                                "type": "Feature",
                                "properties": {"kind": "imbl_line", "name": feat.get("properties", {}).get("name", "IMBL")},
                                "geometry": feat["geometry"],
                            })
            except Exception:
                pass
    except Exception:
        pass

    return {
        "type": "FeatureCollection",
        "session_id": session_id,
        "features": [f for f in features
                     if f["geometry"]["coordinates"][0] is not None],
    }


@app.get("/viz/{session_id}/series")
def viz_series(session_id: str):
    resp = _last_responses.get(session_id)
    if resp is None:
        raise HTTPException(404, "no response stored for this session")
    o = getattr(resp, "ocean_state", None)
    raw_series = getattr(o, "hourly_series", {}) if o else {}
    # Normalize to flat frontend shape {times, wave_height_m, wind_gust_kmh}
    if raw_series and "times" in raw_series:
        series = raw_series
    elif raw_series:
        # Per-metric dict {metric: {times, values}} -> flat
        flat_times = None
        flat_wave: list = []
        flat_gust: list = []
        for k, v in raw_series.items():
            if isinstance(v, dict) and "times" in v:
                if flat_times is None:
                    flat_times = v["times"]
                if "wave" in k.lower():
                    flat_wave = v.get("values", [])
                if "gust" in k.lower() or "wind" in k.lower():
                    flat_gust = v.get("values", [])
        series = {"times": flat_times or [], "wave_height_m": flat_wave, "wind_gust_kmh": flat_gust} if flat_times else raw_series
    else:
        series = raw_series
    windows = [
        {
            "metric": w.metric, "threshold": w.threshold, "unit": w.unit,
            "start": w.start_local, "end": w.end_local, "peak": w.peak_value,
        }
        for w in (getattr(o, "exceedance_windows", []) or [])
    ]
    tides = [
        {"kind": e.kind, "time_local": e.time_local, "height_m": e.height_m}
        for e in (getattr(o, "tide_extremes", []) or [])
    ]
    return {"series": series, "exceedance_windows": windows, "tides": tides}


# ---------------------------------------------------------------------------
# SAR-Based Dark Vessel Detection Near Boundaries (Innovation #3)
# ---------------------------------------------------------------------------
from sar import get_provider as _sar_get_provider
from sar.engine import run_sar_scan, SARConfig
from sar.store import sar_store as _sar_store
from sar.boundary import get_boundary_info as _sar_boundary_info

_last_sar_scan: dict | None = None

class SARScanRequest(BaseModel):
    area: dict | None = None  # {lat_min, lat_max, lon_min, lon_max} or None = default IMBL bbox
    provider: str | None = None  # auto | demo | bhoonidhi
    time_window: str | None = None
    use_cache: bool = True
    boundary_radius_km: float | None = None
    match_radius_km: float | None = None
    match_window_minutes: int | None = None

@app.get("/sar/status")
def sar_status():
    prov_auto = _sar_get_provider("auto")
    prov_demo = _sar_get_provider("demo")
    prov_bhoo = _sar_get_provider("bhoonidhi")
    latest = _sar_store.get_latest()
    return {
        "providers": {
            "auto": prov_auto.describe(),
            "demo": prov_demo.describe(),
            "bhoonidhi": prov_bhoo.describe(),
        },
        "active_provider": getattr(prov_auto, "name", "demo"),
        "boundary": _sar_boundary_info(),
        "cache": _sar_store.cache_info(),
        "latest": {
            "has_latest": latest is not None,
            "summary": {
                "status": latest.get("status") if latest else None,
                "source": latest.get("source") if latest else None,
                "total": latest.get("total") if latest else 0,
                "unknown": latest.get("unknown") if latest else 0,
                "is_stale": latest.get("is_stale") if latest else False,
                "acquisition_time": latest.get("acquisition_time") if latest else None,
                "observation_id": latest.get("observation_id") if latest else None,
            } if latest else None,
        },
        "config": {
            "boundary_radius_km": float(os.getenv("ORCA_SAR_BOUNDARY_RADIUS_KM", "10")),
            "match_radius_km": float(os.getenv("ORCA_SAR_MATCH_RADIUS_KM", "2.0")),
            "match_window_minutes": int(os.getenv("ORCA_SAR_MATCH_WINDOW_MINUTES", "60")),
            "stale_minutes": int(os.getenv("ORCA_SAR_STALE_MINUTES", "120")),
            "cache_ttl_s": int(os.getenv("ORCA_SAR_CACHE_TTL_S", "600")),
        },
        "disclaimer": "SAR provenance: REAL vs SIMULATED vs UNAVAILABLE is always labeled. Unknown != illegal — requires authority verification.",
    }

@app.get("/sar/detections")
def sar_detections(provider: str | None = None, time_window: str | None = None):
    # Return latest scan from cache (honest: may be SIMULATED / STALE / UNAVAILABLE)
    latest = _sar_store.get_latest()
    if latest is None:
        # Try to run a demo scan on first access so authority dashboard isn't empty
        # This is a read path that triggers a scan only when cache is empty (not on every fisherman query)
        try:
            scan = run_sar_scan(provider=provider or "demo", time_window=time_window or "today")
            _sar_store.set(None, getattr(scan.observation, "source", "demo").lower() if hasattr(scan.observation, "source") else "demo", scan.to_dict())
            return scan.to_dict()
        except Exception as exc:
            raise HTTPException(500, f"SAR scan failed: {exc}")
    # Optionally filter by provider? For now return latest regardless
    return latest

@app.post("/sar/scan")
def sar_scan(req: SARScanRequest):
    try:
        cfg = SARConfig(
            boundary_radius_km=req.boundary_radius_km if req.boundary_radius_km is not None else float(os.getenv("ORCA_SAR_BOUNDARY_RADIUS_KM", "10")),
            match_radius_km=req.match_radius_km if req.match_radius_km is not None else float(os.getenv("ORCA_SAR_MATCH_RADIUS_KM", "2.0")),
            match_window_minutes=req.match_window_minutes if req.match_window_minutes is not None else int(os.getenv("ORCA_SAR_MATCH_WINDOW_MINUTES", "60")),
            provider=req.provider or "auto",
        )
        scan = run_sar_scan(
            area=req.area,
            provider=req.provider or "auto",
            config=cfg,
            use_cache=req.use_cache,
            time_window=req.time_window or "today",
        )
        global _last_sar_scan
        _last_sar_scan = scan.to_dict()
        return _last_sar_scan
    except Exception as exc:
        raise HTTPException(500, f"SAR scan failed: {exc}")

@app.post("/sar/demo")
def sar_demo(area: dict | None = None):
    """Deterministic demo: always uses DemoSARProvider, always fresh (no cache). Returns authoritative UNKNOWN example."""
    try:
        scan = run_sar_scan(area=area, provider="demo", use_cache=False)
        global _last_sar_scan
        _last_sar_scan = scan.to_dict()
        return _last_sar_scan
    except Exception as exc:
        raise HTTPException(500, f"SAR demo scan failed: {exc}")

@app.post("/sar/clear")
def sar_clear():
    _sar_store.clear()
    global _last_sar_scan
    _last_sar_scan = None
    return {"cleared": True}

@app.get("/sar/viz")
def sar_viz():
    """GeoJSON FeatureCollection for SAR detections — for direct authority map overlay."""
    latest = _sar_store.get_latest() or _last_sar_scan
    features: list[dict] = []
    if latest and latest.get("detections"):
        for d in latest["detections"]:
            ms = d.get("match_status", "")
            al = d.get("alert_level", "")
            if ms == "UNKNOWN" and al == "HIGH":
                kind = "sar_unknown_high"
            elif ms == "UNKNOWN":
                kind = "sar_unknown"
            elif ms == "KNOWN":
                kind = "sar_known"
            elif ms == "LOW_CONFIDENCE":
                kind = "sar_low_confidence"
            else:
                kind = "sar_other"
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": kind,
                    "detection_id": d.get("detection_id") or d.get("id"),
                    "confidence": d.get("confidence"),
                    "distance_to_boundary_km": d.get("distance_to_boundary_km"),
                    "boundary_segment": d.get("boundary_segment"),
                    "match_status": ms,
                    "alert_level": al,
                    "source": d.get("source"),
                    "dataset": d.get("dataset"),
                    "acquisition_timestamp": d.get("acquisition_timestamp") or d.get("acquisition_time"),
                    "status": d.get("status"),
                    "is_near_boundary": d.get("is_near_boundary"),
                },
                "geometry": {"type": "Point", "coordinates": [d.get("longitude") or d.get("lon"), d.get("latitude") or d.get("lat")]},
            })
    # Add IMBL lines for context
    try:
        import json as _json, os as _os
        _bpath = _os.path.join(_os.path.dirname(__file__), "data", "marine_boundaries.geojson")
        with open(_bpath, "r", encoding="utf-8") as _f:
            _gj = _json.load(_f)
            for feat in _gj.get("features", []):
                if feat.get("geometry", {}).get("type") == "LineString":
                    features.append({
                        "type": "Feature",
                        "properties": {"kind": "imbl_line", "name": feat.get("properties", {}).get("name", "IMBL")},
                        "geometry": feat["geometry"],
                    })
    except Exception:
        pass
    return {"type": "FeatureCollection", "features": features, "count": len(features), "status": (latest.get("status") if latest else "NO_DATA")}

# Also enrich /viz geojson with latest SAR detections when available (authority map overlay)
_original_viz_geojson = None  # placeholder for patching below

# ---------------------------------------------------------------------------
# Fleet Convergence Forecast (Innovation #1)
# ---------------------------------------------------------------------------

class FleetSimulateRequest(BaseModel):
    lat: float | None = None
    lon: float | None = None
    level: str = "high"  # low/medium/high/severe
    session_id: str | None = None  # reference session for zone, else use lat/lon

@app.get("/fleet/status")
def fleet_status():
    import fleet_convergence as fc
    recent = fc.fleet_store.get_recent(window_hours=fc.FLEET_WINDOW_HOURS, include_simulated=True)
    real = [a for a in recent if not a.is_simulated]
    sim = [a for a in recent if a.is_simulated]
    return {
        "window_hours": fc.FLEET_WINDOW_HOURS,
        "radius_km": fc.FLEET_RADIUS_KM,
        "target_capacity": fc.FLEET_TARGET_CAPACITY,
        "penalty_factor": fc.FLEET_PENALTY_FACTOR,
        "max_penalty": fc.FLEET_MAX_PENALTY,
        "total_recent": len(recent),
        "real_count": len(real),
        "simulated_count": len(sim),
        "recent": [
            {"zone_lat": a.zone_lat, "zone_lon": a.zone_lon, "session_id": a.session_id[:8], "is_simulated": a.is_simulated, "age_min": round((__import__("time").time() - a.timestamp)/60, 1)}
            for a in recent[-20:]
        ],
    }

@app.post("/fleet/simulate")
def fleet_simulate(req: FleetSimulateRequest):
    import fleet_convergence as fc
    # If lat/lon not provided, try to use last response's pfz
    lat = req.lat
    lon = req.lon
    if lat is None or lon is None:
        # Try to find from last response for this session
        if req.session_id and req.session_id in _last_responses:
            pfz = getattr(_last_responses[req.session_id], "pfz", None)
            if pfz:
                lat = pfz.center_lat
                lon = pfz.center_lon
        if lat is None or lon is None:
            raise HTTPException(400, "lat/lon required or provide session_id with prior PFZ")
    n = fc.simulate_fleet_activity(lat, lon, level=req.level)
    return {"simulated": n, "level": req.level, "center": {"lat": lat, "lon": lon}, "status": "SIMULATED"}

@app.post("/fleet/clear")
def fleet_clear(simulated_only: bool = True):
    import fleet_convergence as fc
    fc.fleet_store.clear(simulated_only=simulated_only)
    return {"cleared": True, "simulated_only": simulated_only}

@app.get("/fleet/demo")
def fleet_demo(lat: float, lon: float, level: str = "high"):
    """Deterministic demo: returns what fleet analysis WOULD be for given center without persisting."""
    import fleet_convergence as fc
    from models import Location
    # Build a fake pfz at this location for demo
    fake_pfz = type("obj", (), {
        "center_lat": lat, "center_lon": lon,
        "distance_from_reference_km": 12.0, "bearing_deg": 45.0,
        "sst_at_zone_celsius": 27.5, "chlorophyll_at_zone_mg_m3": 0.8,
        "source": type("obj", (), {"value": "simulated"})(),
        "alternates": [
            {"center_lat": lat+0.1, "center_lon": lon+0.1, "distance_km": 18, "bearing_deg": 90, "sst_celsius": 27.0, "gradient_vs_reference_c": 1.2},
            {"center_lat": lat-0.1, "center_lon": lon-0.1, "distance_km": 22, "bearing_deg": 180, "sst_celsius": 26.8, "gradient_vs_reference_c": 0.8},
        ]
    })()
    # Temporarily simulate without polluting store? For demo we just compute with simulated counts
    # We will simulate in-memory counts without persisting by using a temporary fleet_store snapshot
    # Simpler: call simulate then analyze then clear simulated? But we want to show effect
    # For GET demo, we compute crowding as if fleet at given level, without persisting
    # Use the current store plus simulated on-the-fly
    # Instead, just return the levels mapping
    levels = {"low": 2, "medium": 5, "high": 10, "severe": 20}
    n = levels.get(level.lower(), 10)
    # Compute mock result
    candidates = fc.build_candidates_from_pfz(fake_pfz)
    # Mock fleet counts: primary gets n, alternates get small
    mock_counts = {c.zone_id: (n if c.zone_id=="ZONE_A" else max(0, n//4)) for c in candidates}
    fc.apply_fleet_convergence(candidates, mock_counts)
    raw_best = max(candidates, key=lambda x: x.base_suitability)
    final = max([c for c in candidates if c.base_suitability >= fc.FLEET_MIN_BASE_SUITABILITY], key=lambda x: x.adjusted_suitability, default=raw_best)
    return {
        "demo_level": level,
        "candidates": [
            {"zone_id": c.zone_id, "base_suitability": c.base_suitability, "fleet_count": c.fleet_count, "adjusted_suitability": c.adjusted_suitability, "crowding_ratio": c.crowding_ratio}
            for c in candidates
        ],
        "raw_best": raw_best.zone_id if raw_best else None,
        "final": final.zone_id if final else None,
        "changed": raw_best.zone_id != final.zone_id if raw_best and final else False,
    }

# ---------------------------------------------------------------------------
# Satellite–Model Wind Divergence Flag (Innovation #4)
# ---------------------------------------------------------------------------

@app.get("/satellite-wind/status")
def satellite_wind_status():
    """Whether the real (ISRO/MOSDAC) satellite wind connector is activated."""
    import os as _os
    import wind_divergence as wd
    configured = bool(_os.getenv("MOSDAC_API_KEY", "").strip())
    return {
        "real_provider": "MOSDAC_OSCAT3",
        "real_provider_activated": configured,
        "note": (
            "Oceansat-3 (OSCAT-3) is ISRO's current operational scatterometer; "
            "SCATSAT-1 (named in early planning docs) ended its mission in "
            "Feb 2021 and is not live."
        ),
        "moderate_threshold_kmh": wd.MODERATE_ABS_KMH,
        "high_threshold_kmh": wd.HIGH_ABS_KMH,
        "moderate_threshold_pct": wd.MODERATE_PCT,
        "high_threshold_pct": wd.HIGH_PCT,
        "obs_ttl_s": wd._OBS_TTL_S,
        "max_spatial_km": wd.MAX_SPATIAL_KM,
        "max_age_min": wd.MAX_AGE_MIN,
    }


@app.get("/satellite-wind/latest")
def satellite_wind_latest(lat: float, lon: float, demo_scenario: str | None = None):
    """Latest cached satellite wind observation for a point (REAL/SIMULATED/UNAVAILABLE)."""
    import wind_divergence as wd
    obs = wd.get_satellite_observation(Location(name="query", lat=lat, lon=lon), demo_scenario=demo_scenario)
    return {
        "latitude": obs.latitude, "longitude": obs.longitude,
        "wind_speed_kmh": obs.wind_speed_kmh, "wind_direction_deg": obs.wind_direction_deg,
        "observation_timestamp": obs.observation_timestamp.isoformat() if obs.observation_timestamp else None,
        "source": obs.source, "dataset": obs.dataset,
        "status": obs.status.value, "reason": obs.reason,
    }


@app.get("/satellite-wind/divergence")
def satellite_wind_divergence(lat: float, lon: float, forecast_wind_kmh: float | None = None,
                               demo_scenario: str | None = None):
    """Standalone divergence check/demo trigger without running a full /query.

    If forecast_wind_kmh is omitted, the live INCOIS forecast is fetched
    for the point (same OceanStateAgent path used by /query).
    """
    import wind_divergence as wd
    from agents.ocean_state_agent import OceanStateAgent
    loc = Location(name="query", lat=lat, lon=lon)
    if forecast_wind_kmh is None:
        reading, _t = OceanStateAgent().run(loc, "now")
        forecast_wind_kmh = reading.wind_speed_kmh
    result = wd.analyze_wind_divergence(forecast_wind_kmh, loc, demo_scenario=demo_scenario)
    return wd.result_to_dict(result)


@app.delete("/sessions/{session_id}")
def session_clear(session_id: str):
    session_store.clear(session_id)
    _last_responses.pop(session_id, None)
    return {"cleared": True}


def _serialize(response) -> dict:
    """Convert dataclasses (incl. nested ones and enums) into plain JSON-safe dicts."""
    def convert(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return {k: convert(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [convert(v) for v in obj]
        if hasattr(obj, "value"):  # Enum
            return obj.value
        return obj

    return convert(response)


from models import Location  # noqa: E402  (kept close to usage as before)
