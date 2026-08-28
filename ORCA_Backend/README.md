# ORCA Agent Backend — Multi-Agent Pipeline (Panel + Direct Modes)

Implements the full Orchestrator pipeline: Language -> Planning -> parallel
specialists (Ocean-State + Hazard, PFZ, Geospatial, Trend) -> **round-table
Discussion** -> Synthesis -> Response, plus a background Proactive Monitor.
Queries run in `panel` mode (specialists debate before reconciling) or
`agent` mode (one named specialist answers directly -- see `GET /agents`).

## What's real vs. simulated right now

| Component | Status |
|---|---|
| Language/Intent Agent | **Real** — LLM language detection (11 Indian/coastal languages), script-heuristic fallback |
| Orchestrator (LangGraph) | **Real** — planning, conditional specialist selection, parallel dispatch, trace |
| Ocean-State Agent | **Fully real** — LIVE Open-Meteo SST/waves/wind + harmonic tide prediction fitted on real UHSLC gauge observations; chlorophyll LIVE via NOAA ERDDAP when reachable, honest seeded fallback otherwise (per-field provenance always shown) |
| Hazard Agent | **Fully real** — threshold logic + LIVE keyless IMD CAP alert feed (cyclone/marine warnings, polygon hit-test); gated `api.imd.gov.in` kept as secondary fallback |
| PFZ Agent | **Derived from live data** — strongest live-SST thermal front sampled around the user via one batched Open-Meteo call; Bhuvan official layer coded, disabled until endpoint verified. Seeded value only as last-resort error fallback, always tagged |
| Geospatial Reasoning Agent | **Real math** on Tier-2 static data — point-in-polygon/distance vs treaty-digitized IMBL + MPA GeoJSON (`data/marine_boundaries.geojson`), safe-route detours; GEBCO bathymetry TODO |
| Synthesis Agent | **Real** — reconciles all findings, flags cross-agent conflicts, assigns confidence |
| Response Agent | **Real** — final answer composed in the user's detected language |
| Discussion Agent | **Real** — moderated round-table between specialists before reconciliation: structured challenge/clarify/concede turns over each other's actual numbers, ending in a consensus that feeds Synthesis and the final explanation; deterministic fallback without an LLM |
| Location resolution | **Real geocoding** — free-text place names resolved via OSM Nominatim (`countrycodes=in`); hardcoded table is now only an offline cache |

This mirrors the "what's live vs simulated" distinction from the architecture
doc — nothing simulated is hidden; provenance is returned in every response.

## Run it

```bash
pip install -r requirements.txt

# Option A: quick CLI test, no server needed
python3 test_run.py

# Option B: run as an API (panel mode -- specialists discuss)
uvicorn main:app --reload --port 8000
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "Is it safe to go fishing near Ratnagiri tomorrow morning?"}'

# Option C: ask ONE specialist directly (no discussion round)
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "Any cyclone warnings near Visakhapatnam?", "mode": "agent", "agent": "hazard"}'
curl http://localhost:8000/agents     # addressable specialist registry
```

## Project structure

```
orca_backend/
├── models.py                    # shared schemas (the contract every agent uses)
├── orchestrator.py              # LangGraph StateGraph: language -> planning ->
│                                #   parallel specialist dispatch -> synthesis -> response
├── agents/
│   ├── language_agent.py        # PS #1: detect language, normalize query
│   ├── ocean_state_agent.py     # PS #4: LIVE Open-Meteo SST/waves/wind (+tide/chl sim)
│   ├── hazard_agent.py          # PS #5: threshold-based safety verdict
│   ├── pfz_agent.py             # PS #3: nearest fishing zone (derived; Bhuvan TODO)
│   ├── geospatial_agent.py      # PS #6: IMBL/MPA geofence + safe-route planning
│   ├── synthesis_agent.py       # PS #7: reconcile findings, flag conflicts
│   ├── response_agent.py        # PS #9: final answer in the user's language
│   └── ...
├── data/
│   └── marine_boundaries.geojson  # Tier-2 IMBL + MPA boundaries (treaty-digitized)
├── data_connectors/             # MOSDAC/INCOIS/IMD stubs (NOT ACTIVATED)
├── main.py                      # FastAPI HTTP layer
├── test_run.py                  # CLI smoke test (all intents + Marathi query)
└── requirements.txt
```

## How to add the next agent (Tide, Cyclone-track, ...)

1. Create `agents/<name>_agent.py` with a class exposing
   `run(...) -> tuple[YourResultType, AgentTrace]` — follow the exact pattern
   in `pfz_agent.py`.
2. Add the result type to `models.py` if it's new.
3. In `orchestrator.py`:
   - add the agent to `INTENT_DEFAULT_AGENTS` for the intents that warrant it
     (and optionally to the planning schema's `agents_needed` enum)
   - run it in `_node_dispatch()`'s thread pool and fold its result + trace
     into the state update
   - pass its result into `SynthesisAgent.run(...)` and `ResponseAgent.run(...)`
4. Nothing else needs to change — `main.py` and `test_run.py` work
   automatically against any new agent because they only ever touch the
   `OrchestratorResponse` object.

## Orchestration graph

The orchestrator is a compiled LangGraph app (`orchestrator.py`), mirroring
the PS documentation's Section-7 pipeline. State flows through a shared
TypedDict; every node appends its `AgentTrace` entries to an add-only
channel; routing is a conditional edge on the Planning Agent's parsed intent:

```
START -> language_intent -> planning --[supported]--> specialists --> synthesis -> response -> END
                              \---[otherwise]--> unsupported -------------------------------^

specialists (one graph step, parallel threads):
    ocean_state -> hazard      (hazard consumes the ocean reading)
    pfz                        (nearest fishing zone)
    geospatial                 (geofence + optional safe route from GPS/destination)
```

The Planner decides WHICH specialists run per query — "not every query needs
every agent". Explicit device GPS / destination always forces the Geospatial
Agent. Specialists execute concurrently in threads inside a single dispatch
node: LangGraph's pregel fan-in re-fires a join node once per branch when
branches end in different supersteps, and a single dispatch node guarantees
exactly one synthesis pass while keeping true wall-clock parallelism.

If the `langgraph` package is missing, `handle_query()` runs the identical
sequence via direct calls instead of crashing.

## Known simplifications (intentional, for this stage)

- Intent parsing is keyword-based, not LLM-based. Fine for the demo's known
  query patterns; swap in an LLM-based Planning Agent later without changing
  the agent interfaces.
- Location extraction resolves ANY Indian coastal place name via live geocoding
  (OSM Nominatim); the small built-in table (`KNOWN_LOCATIONS`) is only an offline
  cache now.
- Chlorophyll falls back to a deterministic seeded value when the NOAA ERDDAP
  satellite host is unreachable (network-blocked on the dev machine — see
  `data_connectors/chlorophyll.py`); provenance tags always show which path ran.
- Tide prediction needs a UHSLC gauge within 400 km (Cochin/Vizag/Minicoy/Port
  Blair today); outside that range it degrades to a tagged seeded value.

---

## Keep-Alive Health Check (`GET /health`)

ORCA provides an ultra-lightweight health-check endpoint designed specifically for container liveness probes and external uptime monitoring services (such as [UptimeRobot](https://uptimerobot.com)):

- **Endpoint:** `GET /health`
- **Public URL (Production):** `https://orca-backend-1i5u.onrender.com/health`
- **Response Format:**
  ```json
  {
    "status": "ok"
  }
  ```

### Design Guarantees:
- **Instant Execution (<1ms):** Does not trigger LLMs (Groq), LangGraph pipelines, oceanographic APIs, or Firestore storage.
- **Zero Authentication / Header Requirements:** Accessible publicly without `X-API-Key` or Bearer tokens so standard HTTP monitoring pings succeed reliably.
- **Uptime Monitoring:** External monitoring services (e.g. UptimeRobot configured on a 5 or 10-minute recurring interval) can ping this URL to verify backend availability and keep the service warm.
