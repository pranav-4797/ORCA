# ORCA — Agent Operating Guide (AGENTS.md)

**Project:** ORCA — Marine EcOsystem Reasoning with Collaborative Agents
**Event:** SIH 2026 — Problem Statement 26176 (ISRO)
**Repo:** `orcaV1` — GitHub `FarhanFarooqi122/orca-sih26176` (private), branch `main`
**Current HEAD:** `8e77b2a` (in sync with `origin/main`)
**Date of last full review:** 2026-08-30

---

## 1. What this document is

The day-one orientation + living status source for anyone (human or coding agent)
working on ORCA. It supersedes the old "gap analysis" framing from 2026-08-25:
all 10 PS components and every P0/P1 gap are now implemented. It documents how
to run, verify, and extend the system, what the real architecture is, what remains
credential-blocked, and the conventions that must not be broken.

Source documents that define the requirement: `DOC-20260824-WA0005.pdf` (15 pages)
and the SIH PS-26176 description (NL intent, auto language detect/reply, multi-turn
context, autonomous multi-source integration, spatial/temporal/contextual reasoning,
explainable evidence-backed answers with maps/charts, proactive alerts incl.
weather/high-waves/LIGHTNING/cyclones, geofence push (IMBL/restricted/MPA),
weather-aware route optimization, modular multi-agent collaboration, voice as a
first-class mode, multilingual, safety NFRs).

---

## 2. Run it

```bash
# Backend (from ORCA_Backend/)
pip install -r requirements.txt
python -m uvicorn main:app --port 8000            # docs UI at /docs
python test_run.py                                # CLI smoke of the pipeline

# UI (from ORCA UI/) — vite auto-spawns the backend if :8000 is free
npm install
npm run dev                                       # http://localhost:3000

# One-command container deploy
docker compose up --build
```

- Backend needs `ORCA_Backend/.env` (git-ignored; template `.env.example`) with a
  free **Groq** key (`GROQ_API_KEY`) for the LLM + Whisper STT layers. Everything
  degrades gracefully without it (rule/keyword fallbacks, template answers).
- **INCOIS single marine pipeline (8e77b2a):** all SST/Wind/Current/Swell via THREDDS WMS + Chlorophyll via OceanSat-2 ERDDAP through `data_connectors/incois_marine.py`; `chlorophyll.py` (NOAA CoastWatch) deleted; query-aware filtering (SST-only shows only SST) and readable markdown tables with `📍` coords.
- The deployed backend (`https://orca-backend-1i5u.onrender.com`, Render free plan,
  Docker, region Singapore) can go cold/offline; local is the reliable path.
  Render health: `GET /health`. Render service = `ORCA_Backend/Dockerfile` +
  `render.yaml`; UI is hosted on Firebase (`orca-2530.web.app`, CORS allow-listed).

---

## 3. Architecture (current reality)

Backend: FastAPI (`main.py`, v0.3.0) + **LangGraph** orchestrator split into a
package `orchestrator/` (`graph.py` graph+conditional edges, `planning.py` planner
schema v3 + rule fallback, `state.py` shared state + `Intent` constants,
`dispatch.py` parallel specialist dispatch). A regex `auto_router.py` fast path
short-circuits common English intents before any LLM planning call. Specialists may
hold a moderated round-table `agents/discussion_agent.py`, then `SynthesisAgent`
reconciles and `ResponseAgent` writes the final message.

```
/query -> session memory -> [auto_router] or [planning (LLM·tools)] -> dispatch
   -> {ocean_state -> hazard} ∥ {pfz} ∥ {geospatial} ∥ {trend}
   -> optional discussion round -> synthesis -> response -> trace + viz payload
```

| # | Component | Reality (2026-08-29) | Where |
|---|---|---|---|
| 1 | Language/Intent | Detects 11 Indic + English, normalizes; Unicode-script fallback; ASCII fast-path skips the LLM call on English | `agents/language_agent.py`, `auto_router.py` |
| 2 | Orchestrator/Planner | LangGraph StateGraph; planning schema v3 (`intent` incl. `trend_analysis`/`zone_scan`, `target_hour`, `agents_needed`); parallel dispatch via ThreadPoolExecutor in one node; no-LLM fallback; sequential fallback if langgraph missing | `orchestrator/` |
| 3 | PFZ | **LIVE official INCOIS/SAMUDRA advisory** is the primary source (`data_connectors/incois_pfz.py`: pfzLines + pfzMobile + sector text, 10-min TTL). Nearest point on the official digitized geometry drives distance/bearing/target coords. Fallbacks: derived live-SST ring (`DERIVED_LIVE`), seeded last resort. Official lookups return ONE exact answer template (no LLM) | `agents/pfz_agent.py`, `agents/pfz_output.py` |
| 4 | Ocean-State | **Single INCOIS pipeline** — `incois_marine.py` is the ONLY marine connector: OSF SST + WW3 wind (`mag`) + wind vector + Currents + WW3 PHS01 primary swell + OceanSat-2:CHL ERDDAP; field-by-field graceful (never fabricates), `Value: 28.` truncated fix, `ORCA_DEBUG_INCOIS` per-layer logging, tide via UHSLC 8-constituent harmonic; no Open-Meteo/NOAA fallbacks | `agents/ocean_state_agent.py`, `data_connectors/incois_marine.py`, `data_connectors/tide.py` |
| 5 | Hazard/Alert | Thresholds per vessel class (None-guarded `wave_height_m`/`wind_gust_kmh`); **keyless IMD CAP live** hit-tested — cyclone only forces UNSAFE when covering location/route, marine covering filtered to non-cyclone; lightning via CAP terms; keyed `api.imd.gov.in` secondary (401-gated) | `agents/hazard_agent.py`, `data_connectors/imd_cap.py`, `imd_live.py` |
| 6 | Geospatial | Treaty-digitized IMBL + MPAs (15 km buffer); sampled planner + **GEBCO/INCOIS bathymetry + pure-Python A***; PFZ line style `#00E5FF` weight 4 overlay with `fitBounds` | `agents/geospatial_agent.py`, `data_connectors/bathymetry.py`, `data/marine_boundaries.geojson` |
| 7 | Synthesis | Reconciles findings + round-table transcript, flags conflicts, verdict/confidence/key_points; numeric `confidence_score` (0–1) + per-source `evidence_tiers` (Tier 1/2/3) | `agents/synthesis_agent.py`, `fleet_convergence.py` |
| 8 | Explainability | Add-only `operator.add` `traces` channel; every node appends `AgentTrace` with duration; UI streams it live | `orchestrator/state.py`, `models.py` |
| 9 | Response | Multilingual final answer (≤ ~70 words, concise mode), exact official INCOIS PFZ template on PFZ lookups, anti-hallucination rules, template fallback | `agents/response_agent.py` |
| 10 | Proactive Monitor | Independent asyncio timer loop (15 min) re-polls OceanState/Hazard/Geospatial per registered user position; signature dedup (fires on new/escalating hazard or geofence approach only); composes alert in user's language; SSE push + Twilio SMS (no-dep REST, honestly disabled without creds) | `agents/proactive_monitor.py`, `alerts.py` |

### Cross-cutting subsystems (all live)

- **Session memory**: `sessions.py` — location/time-window/language/GPS/destination/`map_point`
  per `session_id`, 1 h TTL, anaphora-aware planning ("same place, tomorrow evening"); map-tap priority `mapPoint > GPS > chat`.
- **Storage**: `storage.py` TTLStore — Redis when `REDIS_URL` set, in-process otherwise;
  used by sessions + a 60 s response cache (absorbs UI retries/double-taps).
- **Fleet convergence**: `fleet_convergence.py` + `/fleet/*` demo endpoints (simulated
  fleet activity levels).
- **Routing telemetry**: `routing_telemetry.py` + `/debug/telemetry[/summary]`;
  routing fixtures in `ORCA_Backend/test_data/`.
- **UI**: Vite + React + Leaflet (`ORCA UI/`). Streaming chat (readable markdown tables with query-aware filtering), verdict callouts, agent activity panel, operational map (`/viz` GeoJSON, PFZ `#00E5FF` weight 4 `fitBounds`), 48 h wave/gust charts (`/viz/series` normalized), voice in/out, `marineService.ts` INCOIS WMS tiles, Firebase Google-sign-in, proactive SSE alert feed, query-routing pills, mock fallback when backend/LIVE absent.
- **Graceful degradation**: no key → rules + template answers; feed down → tagged
  seeded fallback, never a crash; per-specialist failures are skipped, not fatal.

### API surface (`main.py`)

```
GET  /health                         keep-alive (Render/UptimeRobot)
GET  /debug/telemetry[/summary]      routing latency metrics
GET  /agents                         addressable specialist registry
GET  /api/pfz/live                   live INCOIS PFZ zones (official advisory JSON)
POST /query                          {query, session_id?, device_gps?, destination?, mode?,
                                      agent?, vessel_class?, query_depth?, fleet_demo_level?}
POST /query/voice                    multipart audio -> Groq Whisper STT -> same graph (+transcribed_text)
POST /users/register                 proactive alert registration (lat/lon/phone/language)
GET/DELETE /users{/user_id}          registry list/delete
POST /users/{user_id}/position       GPS heartbeat
GET  /alerts/{user_id}               poll alerts
GET  /alerts/stream/{user_id}        Server-Sent Events alert stream
GET  /viz/{session_id}               consolidated GeoJSON FeatureCollection
GET  /viz/{session_id}/series        hourly wave/gust series + exceedance windows + tide extremes
POST /fleet/{status,simulate,clear,demo}
```

---

## 4. Conventions (must not break)

- **Honesty/provenance:** per-field `field_sources` + `evidence_tiers`; degraded-mode
  always disclosed; "unverifiable" ≠ "clear".
- **LLMs reason ON TOP of deterministic data; they never invent numbers.**
- **Graceful degradation everywhere** (no 500 on missing key/feed/package).
- **Exact PFZ answer format:** for official INCOIS advisories the answer must be the
  template in `agents/pfz_output.py` (`🛡️ IMPORTANT` → `🔶 VERDICT` → target coords →
  `📋 Quick Summary`), 4-decimal coords, 1-decimal km, 8-point compass. Shared by
  `ResponseAgent.run()` and the orchestrator fast path (`intent == "pfz_lookup"`). UI
  skips its own verdict callout when the answer already contains `🛡️ IMPORTANT`.
- **Do not re-introduce** the old "thermal-front heuristic / simulated chlorophyll /
  not an official INCOIS advisory" wording on the official path; the derived-fallback
  path still says honestly it is an estimate ("official advisory unavailable for this
  spot today").
- **API + agent-interface stability:** `/query` payload and v3 planner schema are
  contract — extend, don't remove fields.
- **No secrets in git:** `.env` is git-ignored; only `.env.example` tracked.
- Backend code is Python 3.11+ (targeting 3.14); UI is TypeScript strict + tsc.

---

## 5. Verify before you claim "done"

```bash
# Backend syntax for touched files
python -m py_compile <changed .py files>

# Quick smoke (needs no key)
cd ORCA_Backend && python test_run.py

# Unit-ish checks already in repo (run at least the ones covering your change)
python test_health.py test_safety_floor.py test_fleet_convergence.py test_optimized.py
python test_romanized_degraded.py test_demo_cache.py

# UI typecheck + build (from ORCA UI/)
npx tsc --noEmit
npm run build
```

Live-agency checks: `GET /health`; `POST /query` with `mode=panel` (round table),
`mode=agent&agent=pfz` (official INCOIS answer template), `mode=auto` fast path; a
follow-up with a `session_id` reusing the prior location; register a user + poll
`/alerts`. CI skeleton: `.github/workflows/ci.yml`.

---

## 6. Feature-delivery history (git map)

- The remote rewrite (34 commits) brought Firebase auth, dashboard+latency rework,
  routing fixtures, fleet convergence, routing telemetry and Docker/Render deployment.
- **INCOIS PFZ go-live** — `3a85744`..`5e1eeac` (connector + agent consumption +
  `/api/pfz/live` + UI layer + docs).
- **Official PFZ answer format** — `cbf67a3`..`dc6b9a3` (shared template, nearest-point
  distance/bearing, popup metadata, verdict dedup).
- **INCOIS consolidation master patch** — `8e77b2a` (single marine pipeline `incois_marine.py`: OSF/WW3/Currents/OceanSat-2, deleted NOAA `chlorophyll.py`, fixed Hazard `None` guards + cyclone scoping + confidence excluding `unavailable`, fixed `_serialize` dynamic-field drop, `/query/voice` → `asyncio.to_thread`, WMS `Value: 28.` parse + `ORCA_DEBUG_INCOIS` logging, PFZ nondeterminism + `0.0` fab fix, `hourly_series` flat + `viz_series` normalization, PFZ line `#00E5FF`, map-tap priority, readable markdown tables, query-aware field filtering). Current HEAD = `8e77b2a`.
- Session history and detailed decisions: `ORCA_Backend/SESSION_SUMMARY.md`
  (Phases 1–13), `ORCA_Backend/PFZ_INCOIS_INTEGRATION.md`, `SESSION_LOG_2026-08-24.md`.

---

## 7. Remaining / blocked (accurate as of 2026-08-29)

True gaps are all **externally blocked or polish** — the engine is complete:

| Item | State |
|---|---|
| Bhuvan WMS live (ISRO's own platform) — SST/chl/buoy layers | Superseded: **INCOIS official PFZ is live** (evaluation-relevant); Bhuvan optional Tier-1 verification if account access granted (`isro_sources.py` stubs) |
| `api.imd.gov.in` key + cyclone cone-of-uncertainty / wind-warning overlays | Code ready (`imd_live.py`), 401-gated, blocked on credentials; keyless CAP feed covers alerts today |
| Twilio SMS live-fire | Sending code complete (`alerts.py`, urllib REST); needs trial verified number / TRAI DLT path |
| PostGIS / vector DB / warehouse | Not present — storage is Redis-or-in-process JSON; PDF Sec. 13 stack for scale-out only |
| LLM latency (cold ≈ 12–25 s; warm ≈ 10 s) | Sequential chain inherently so; next lever = discussion+synthesis fusion (README item 1) |
| MOSDAC satellite SST/chl (Oceansat-3, user already downloaded sample NetCDFs via `mdapi.py`) | Connector stub only; wire into Ocean-State if a key/URL is approved |
| Automated backend CI gate (currently `ci.yml` skeleton, scripts manual) | Polish |

### Housekeeping (untracked, do not commit unless asked)

`ORCA_Backend/_pre_incois_backup/` (pre-integration snapshot), `architecture*.png`,
`ORCA_Backend/test_openmeteo.py`, `ORCA_Backend/demo_cache/` cache files, `__pycache__/`.

---

## 8. Quick reference — key env vars

`GROQ_API_KEY` (LLM+STT) · `LLM_BASE_URL` · `LLM_MODEL` · `CORS_ORIGINS` ·
`ORCA_API_KEY` (X-API-Key guard, skip in dev) · `REDIS_URL` (session/response cache) ·
`ORCA_THRESHOLD_OVERRIDES` (per-vessel-class safety thresholds) ·
`ORCA_RESPONSE_CACHE_TTL_S` (default 60) · `INCOIS_PFZ_TIMEOUT` ·
`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_FROM_NUMBER` (SMS).