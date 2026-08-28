# ORCA — Agentic AI Marine Intelligence Platform

**Smart India Hackathon 2026 · Problem Statement 26176**
Agentic AI for Indian coastal waters: ask in any language, get a safety verdict backed by live ocean data, official alerts, and a transparent multi-agent debate.

---

## What it does

A fisherman or maritime user asks a question like *"Is it safe to go fishing near Ratnagiri tomorrow morning?"* — in English, Marathi, Hindi, Tamil, and 7 more languages — and ORCA:

1. Detects the language and parses intent/location/time.
2. Dispatches only the relevant specialist agents **in parallel**.
3. Specialists fetch live ocean/weather/alert data and report findings.
4. A **round-table discussion** runs: agents challenge, clarify, concede, and converge on a shared reading of each other's findings.
5. A synthesis agent reconciles everything into one verdict (SAFE / CAUTION / UNSAFE) with confidence and flagged conflicts.
6. The answer is composed in the user's language — grounded strictly in the fetched numbers, with every field's provenance (live vs derived vs simulated) disclosed.

You can also address **one specialist directly** (no debate) via the UI pill or `mode=agent`.

---

## Architecture

```
                 START
                   |
             language_intent                    (PS #1)
                   |
                planning                         (PS #2)
        [which specialists does THIS query need?]
                   |
               specialists  -- PARALLEL threads:
                   |            ocean_state -> hazard   (PS #4/#5)
                   |            pfz                      (PS #3)
                   |            geospatial               (PS #6)
                   |            trend
                   |
                discussion  -- round-table: agents read each
                   |            other's findings and debate
                   |            (challenge/clarify/concede/agree)
                   |
                synthesis    -- single reconciled pass     (PS #7)
                   |
                response                                 (PS #9)
                   |
                  END

  proactive_monitor (PS #10): background loop pushing safety alerts
  over SSE/SMS to registered users — no query required.
```

LangGraph StateGraph with an add-only trace channel; if LangGraph or the LLM is unavailable every step degrades gracefully to deterministic behaviour — the demo never hard-crashes.

## The agents

| Agent | Role | Data reality |
|---|---|---|
| Language | Detect 11 Indian/coastal languages, normalize query | LLM + script heuristic fallback |
| Planning | Intent, place, time window, hour, needed specialists | LLM forced tool-call + rule fallback |
| Ocean-State | SST, waves, wind/gusts, tides, chlorophyll | **Live** Open-Meteo marine+weather (parallel), **live** UHSLC harmonic tide fit (cached), NOAA ERDDAP chlorophyll when reachable else seeded & tagged |
| Hazard | Threshold verdicts, exceedance windows, cyclone checks | Deterministic thresholds + **live** keyless IMD CAP feed |
| PFZ | Nearest fishing zone from the daily official advisory; distance/bearing to the nearest point on the digitized PFZ lines | **Live** INCOIS/SAMUDRA official PFZ (keyless); SST-ring derived + seeded fallbacks honestly tagged |
| Geospatial | IMBL/MPA geofencing, weather-aware safe routes | Real point-in-polygon math on treaty-digitized GeoJSON |
| Trend | Months-long SST/chlorophyll trends + correlation | Live Open-Meteo archive |
| **Discussion** | Moderated round-table transcript between specialists (structured `speaker/addressing/stance/point` turns + consensus) | LLM-moderated, numbers-only constraint; deterministic fallback |
| Synthesis | Reconcile findings, flag cross-agent conflicts, confidence | LLM over structured results + transcript |
| Response | Final answer in the user's language, explains how disagreements were settled | LLM; template fallback |
| Proactive Monitor | Background position monitoring → pushed alerts | Reuses ocean/hazard/geospatial agents |

## Query modes

| Mode | Behaviour |
|---|---|
| `panel` *(default)* | Full pipeline — specialists run, hold the round-table, reconcile one verdict |
| `agent` | One named specialist answers directly (no discussion). Registry served at `GET /agents`; dependencies (e.g. hazard needs an ocean reading) are resolved silently |

Every response carries `mode`, `answered_by`, the full agent trace, the discussion transcript, and per-field provenance.

## Chat UI (Vite + TypeScript)

- Streaming chat with verdict callouts and markdown
- **Voice in / voice out** — hold the mic, speak your question (any language); Whisper STT transcribes it ("Heard you say…"), the full pipeline answers, and the browser speaks the reply back in the detected language
- **Agent activity panel** streaming the real execution trace live, including each round-table turn (⚡ challenge / ℹ️ clarify / ✅ agree / 🤝 concede) and the consensus
- **Operational picture**: Leaflet sea map (query point, PFZ zones + ring, safe route, IMBL/MPA flags, IMD warning polygons) plus 48-hour wave/gust charts with unsafe thresholds and exceedance windows shaded, tide extremes as chips — auto-refreshed per answer from `/viz/*`
- **Query-routing pill**: pick the full panel or any single specialist (color-coded, dropdown lists the live backend registry)
- Per-message badge showing exactly which path answered
- Proactive safety alerts pushed over SSE; optional demo GPS
- Multi-turn session memory ("same place, tomorrow evening")

## API surface (FastAPI, port 8000)

```
POST /query                     {query, session_id?, device_gps?, destination?, mode?, agent?, vessel_class?}
POST /query/voice               multipart audio -> Whisper STT -> same graph -> answer JSON (+transcribed_text)
GET  /agents                    addressable specialist registry for mode="agent"
GET  /health                    (+ storage backend info)
POST /users/register            proactive alert registration
GET  /alerts/{user_id}          poll alerts
GET  /alerts/stream/{user_id}   Server-Sent Events stream
GET  /viz/{session_id}          GeoJSON FeatureCollection (point, PFZ, route, boundaries, CAP polygons)
GET  /viz/{session_id}/series   hourly wave/gust series + exceedance windows + tide extremes
DELETE /sessions/{session_id}
```

Every response also carries `confidence_score` (numeric 0–1 combining data provenance, verdict confidence and cross-agent agreement) and `evidence_tiers` (each source labelled Tier 1 user-device / Tier 2 live feed / Tier 3 derived-simulated).

## Configuration & hardening

| Env var | Effect |
|---|---|
| `GROQ_API_KEY` | LLM + Whisper STT (free key; everything degrades without it) |
| `CORS_ORIGINS` | Comma-separated allow-list; default `*` for local dev |
| `ORCA_API_KEY` | When set, all routes except `/health` require `X-API-Key` |
| `REDIS_URL` | `redis://...` moves session memory + response cache to Redis (default: in-process TTL store) |
| `Vessel thresholds` | `vessel_class` per request: `small_fishing_boat` (default), `mechanized_trawler`, `coastal_cargo`; fine-tune via `ORCA_THRESHOLD_OVERRIDES` JSON |

**Data privacy note:** ORCA processes device GPS / destination coordinates only to answer the current safety query and short-lived session context (1 h TTL). Positions are not persisted beyond the TTL cache, sold, or shared; proactive monitoring stores only the position a user explicitly registers.

## Performance engineering

- Whole-readings cached 15 min (trace honestly marks `CACHED`)
- Tide harmonic models fitted once, cached 6 h (fit window 120 days of gauge data)
- Marine/weather/chlorophyll/tide fetched concurrently; marine dry-cell retries under a 30 s budget
- Cold query ≈ 12–25 s (dominated by LLM calls); warm repeat ≈ 10 s

---

## Status: implemented vs planned

### Implemented
- Full multi-agent graph incl. round-table discussion + consensus (this repo's core differentiator)
- Panel / direct-agent query routing with per-answer badges
- **Voice queries end-to-end**: mic capture → Groq Whisper STT → same pipeline → browser TTS reply in the detected language (`/query/voice`)
- **Map & charts UI**: Leaflet operational map + hourly wave/gust series charts fed by `/viz/*`
- Live Open-Meteo, UHSLC tides, IMD CAP alerts, OSM geocoding; honest seeded fallbacks with per-field provenance
- Multilingual answers (11 languages), multi-turn memory
- Proactive monitoring with SSE push (SMS sending code present, not live-fired)
- Docker: `docker compose up --build` runs backend + UI
- **Hardening**: pluggable Redis/in-memory storage, optional API key, configurable CORS, per-vessel-class thresholds, numeric confidence + Tier 1/2/3 evidence labels, ASCII fast-path + response caching for latency

### In planning (next up)
1. Batch/downgrade further LLM calls in the sequential chain (discussion+synthesis fusion candidate)

### Blocked externally (code ready, waiting on credentials/access)
- Bhuvan WMS live activation (ISRO account) — optional now that the official INCOIS PFZ advisory is live
- `api.imd.gov.in` key (secondary fallback only; keyless CAP feed already active)
- Cyclone cone-of-uncertainty overlays once the IMD key exists (connector coded)
- Twilio SMS live-fire test (TRAI DLT registration path)

---

## Run it

```bash
# --- One command (Docker) -------------------------------------------
docker compose up --build
#   UI      -> http://localhost:3000
#   Backend -> http://localhost:8000

# --- Manual -----------------------------------------------------------
# Backend
cd ORCA_Backend
pip install -r requirements.txt
python -m uvicorn main:app --port 8000        # or: uvicorn main:app --reload

# Frontend (auto-spawns the backend if :8000 is free)
cd "ORCA UI"
npm install
npm run dev                                    # http://localhost:3000
```

Configure `ORCA_Backend/.env` (see `.env.example`) with a free Groq key for the LLM layers; everything degrades gracefully without one.

Quick CLI smoke test:

```bash
cd ORCA_Backend && python test_run.py
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "Is it safe to go fishing near Ratnagiri tomorrow morning?"}'
```

Direct-agent example:

```bash
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "Any cyclone warnings near Visakhapatnam?", "mode": "agent", "agent": "hazard"}'
```

## Repository layout

```
ORCA-SIH/
├── README.md                  ← you are here
├── ORCA_Backend/
│   ├── main.py                FastAPI entrypoint (+ /agents registry, viz, alerts)
│   ├── orchestrator.py        LangGraph pipeline, panel/direct routing, planning
│   ├── models.py              shared schemas (OrchestratorResponse contract)
│   ├── llm_client.py          single LLM gateway (Groq/OpenAI-compatible)
│   ├── sessions.py, alerts.py session memory + proactive alert bus
│   ├── agents/                language, ocean_state, hazard, pfz, geospatial,
│   │                          trend, discussion, synthesis, response,
│   │                          proactive_monitor
│   ├── data_connectors/       open-meteo helpers, tide (UHSLC harmonic fit),
│   │                          chlorophyll, imd_cap, geocode, bathymetry,
│   │                          isro_sources (stubbed, NOT ACTIVATED)
│   └── data/                  IMBL + MPA boundaries GeoJSON
└── ORCA UI/                   Vite + TypeScript chat workspace
    └── src/services/orcaApiService.ts   backend client (panel/direct modes,
                                          discussion streaming, alerts SSE)
```

Detailed backend engineering log: [`ORCA_Backend/SESSION_SUMMARY.md`](ORCA_Backend/SESSION_SUMMARY.md).
