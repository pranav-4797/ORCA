# ORCA Backend — Work Summary (2026-08-24)

Marine EcOsystem Reasoning with Collaborative Agents — SIH 2026, PS 26176.
FastAPI + LangGraph multi-agent backend; LLM layer on Groq (`openai/gpt-oss-120b`, free tier).

This file summarizes today's three work blocks. Longer-form running log: `SESSION_SUMMARY.md`.
Target spec: `ORCA_Project_Documentation.pdf` (10-component architecture, tiered data sources).

---

## 1. LangGraph migration (orchestrator core)

- Replaced hardcoded sequential dispatch with a compiled `StateGraph`
  (`langgraph>=0.2`, installed 1.2.11).
- Shared `ORCAGraphState` TypedDict; `traces` is an add-only channel
  (`Annotated[List[AgentTrace], operator.add]`) — every agent appends its own trace entries.
- Conditional edge on the Planning Agent's parsed intent routes to specialists or an
  `unsupported` terminal node.
- Graceful degradation extended one layer down: if the `langgraph` package is missing,
  `handle_query()` runs the identical sequence via direct calls instead of crashing.

## 2. Full conversational agent set (PS components #1–#9)

Graph topology now running:

```
START -> language_intent -> planning --[supported]--> specialists --> synthesis -> response -> END
                              \---[otherwise]--> unsupported -------------------------------^

specialists (one graph step, parallel threads):
    ocean_state -> hazard      (hazard consumes the ocean reading)
    pfz                        (nearest fishing zone)
    geospatial                 (geofence + optional safe route from GPS/destination)
```

| File | Status | Role |
|---|---|---|
| `agents/language_agent.py` | NEW | Detects query language (11 languages), normalizes to English; Unicode-script heuristic fallback |
| `agents/ocean_state_agent.py` | pre-existing | LIVE Open-Meteo SST/waves/wind; chlorophyll+tide simulated per-field |
| `agents/hazard_agent.py` | MODIFIED today | Threshold verdicts **+ live IMD cyclone check** (see §3) |
| `agents/pfz_agent.py` | NEW | Nearest-PFZ (distance/bearing/SST/chl). Bhuvan WMS call coded, `USE_LIVE_BHUVAN_PFZ=False` until endpoint verified; zone derived deterministically & tagged SIMULATED |
| `agents/geospatial_agent.py` | NEW | Pure-Python point-in-polygon geofence vs IMBL/MPA boundaries (15 km buffer) + sampled safe-route planner with detours (GEBCO/A* TODO) |
| `data/marine_boundaries.geojson` | NEW | Tier-2 static: India–Sri Lanka IMBL (1974/1976 segments), India–Pakistan IMBL (Sir Creek approx.), Gulf of Mannar MPA, Malvan sanctuary. Simplified, NOT FOR NAVIGATION |
| `agents/synthesis_agent.py` | REWRITTEN | Reconciles all findings → verdict/confidence/conflicts/key_points; tolerates absent specialists |
| `agents/response_agent.py` | NEW | Final answer composed in the user's detected language (verified fluent Marathi); ≤130 words; anti-hallucination rules |
| `models.py` | EXTENDED | `PFZRecommendation`, `GeofenceStatus`, `RestrictedZoneHit`, `RoutePlan`; context gained `language`/`device_gps`/`destination`; response gained `language`/`pfz`/`geofence`/`route` |
| `main.py` | EXTENDED | `/query` accepts optional `device_gps` and `destination`; GPS/destination always forces the Geospatial Agent |

Key decisions:
- **Dispatch-node fan-out:** native LangGraph branch joins re-fire the join node once per
  branch completion when branches end in different supersteps (tried list-routing AND
  `Send`). Solution: selected agents run concurrently inside one `specialists` node via
  `ThreadPoolExecutor` — exactly one synthesis pass, true wall-clock parallelism preserved.
- Per-specialist failures are caught/logged/skipped — one dead agent never kills a query.
- Planner schema v2: intents `{safety_check, pfz_lookup, route_plan, geofence_check,
  hazard_alerts, unknown}` with rule-based keyword fallback router.

## 3. IMD live cyclone check

- **`data_connectors/imd_live.py` (NEW):** keyless-by-design connector for
  `https://api.imd.gov.in/api/v1`: `cyclone_track`, `cyclone_wind`, `cyclone_cou`,
  `coastalbulletin`, `districtwarning`, `portwarning`, `seaareabulletin`;
  `DISTRICT_IDS={}` TODO with devtools-discovery instructions.
  All network/HTTP/parse failures raise `ImdUnavailableError` — never fake data.
- **Field reality (probed live):** after working around IMD's incomplete TLS chain,
  every endpoint answers `HTTP 401 {"error":"API key missing"}` — the API is NOT keyless
  today despite docs saying so. Connector sends optional `IMD_API_KEY`
  (`api-key` param + Bearer header) so it goes live the moment a credential exists.
  Cert-failure retry-once-relaxed is logged loudly and documented.
- **HazardAgent wiring:** cyclone check runs between threshold checks and verdict.
  Active system → `"Active cyclone system"` HazardFlag → UNSAFE. Unreachable feed →
  reasoning line "Cyclone risk assumed unknown, not clear" (never treated as clear).
  `DataSource.IMD_LIVE` (already existed in models.py) enters `evidence_sources` ONLY on
  genuine success. Cyclone note flows into the LLM reasoning-note prompt and fallbacks.

## 4. Verified end-to-end (actual runs)

- `test_run.py`: safety_check (en), pfz_lookup, route_plan w/ GPS+destination,
  geofence_check (3.5 km off Palk Strait IMBL → correctly FLAGGED; Odisha offshore → clear,
  78.4 km route planned), Marathi query (`mr` detected, Marathi answer citing live numbers).
- Trace shows every agent incl. `[cyclone=unverifiable]` on HazardAgent; Synthesis flagged
  the unverifiable cyclone as a cross-agent conflict; final answers honestly disclose
  simulated fields and unverified feeds.
- Degraded mode (bogus GROQ key): script-heuristic language detection, keyword intent
  routing, all specialists run, `[llm_unavailable]` template notes.
- Server smoke tests (in-process uvicorn): `/query` round-trips pfz/geofence/route objects;
  `/health` ok; degraded path verified earlier with bogus-key env.

## 5. Data source status (honest tiering)

| Source | State |
|---|---|
| Open-Meteo Marine/Weather | LIVE (default production path) |
| IMD api.imd.gov.in | Coded; HTTP 401 without key — add `IMD_API_KEY` to `.env` when issued |
| Bhuvan WMS (PFZ/SST/chl) | Connector coded, disabled — endpoint pattern returned 404, needs verification |
| IMBL/MPA boundaries | Real static (Tier 2), simplified treaty digitization |
| Chlorophyll/tide/PFZ zone | Deterministic simulation, tagged per-field |
| MOSDAC / INCOIS | Stubbed in `data_connectors/isro_sources.py` (require credentials) |

## 6. Run it

```bash
pip install -r requirements.txt
python test_run.py                 # CLI smoke across all intents (+ Marathi query)
uvicorn main:app --reload --port 8000
# POST /query {"query": "...", "device_gps": [lat,lon], "destination": {"lat":..,"lon":..,"name":".."}}
```

## 7. Remaining roadmap

1. Proactive Monitor Agent (#10): async timer loop + push alerts (+ Twilio SMS trial mode).
2. Obtain IMD API key → flip cyclone/warning checks truly live; discover district/port ids.
3. Verify Bhuvan WMS GetFeatureInfo endpoint → enable `USE_LIVE_BHUVAN_PFZ`.
4. Multi-turn session memory ("what about the day after?").
5. Voice STT/TTS, map overlays, Agent Orchestration Console (frontend scope).
