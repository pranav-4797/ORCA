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
    session_id = request.session_id or orchestrator_new_session()

    # Short-TTL cache of identical repeat requests (UI retries / double
    # taps): same query+params within the TTL returns the stored payload.
    # TTL from env ORCA_RESPONSE_CACHE_TTL_S (default 60s for live safety, shorter than session).
    import os as _os
    _ttl = int(_os.getenv("ORCA_RESPONSE_CACHE_TTL_S", "60").strip() or 60)
    cache_key_src = "|".join([
        request.query.strip().lower(), request.mode, request.agent or "",
        request.vessel_class or "", str(device_gps), str(destination),
        session_id, request.query_depth or "", request.fleet_demo_level or "",
    ])
    cache_key = hashlib.sha256(cache_key_src.encode()).hexdigest()
    # Don't cache demo fleet queries — they are meant to change with simulated levels
    use_cache = not request.fleet_demo_level
    cached = storage.response_cache.get(cache_key) if use_cache else None
    if cached is not None:
        return cached

    response = orchestrator.handle_query(
        request.query,
        session_id,
        device_gps=device_gps,
        destination=destination,
        mode=request.mode,
        target_agent=request.agent,
        vessel_class=request.vessel_class,
        query_depth=request.query_depth,
        fleet_demo_level=request.fleet_demo_level,
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
    response = orchestrator.handle_query(transcript, sid, mode=mode, target_agent=agent)
    _last_responses[sid] = response
    payload = _serialize(response)
    if isinstance(payload, dict):
        payload["session_id"] = sid
        payload["transcribed_text"] = transcript
    return payload


# ---------------------------------------------------------------------------
# User registry + proactive alerts (PS component #10 delivery channels)
# ---------------------------------------------------------------------------

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
    series = getattr(o, "hourly_series", {}) if o else {}
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
