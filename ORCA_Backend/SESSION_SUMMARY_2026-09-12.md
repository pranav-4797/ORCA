# Session Summary — 2026-09-12

**Branch:** `main` → `origin/main` (`FarhanFarooqui122/orca-sih26176`, private)
**Commits this session:** `840d5b4` → `45faa7f` → `f0fc6e8` → `c22d9a0` (+ docs commit)
**Date:** 2026-09-12 (UTC+5:30) — pull upstream, then verify-and-fix day driven by `ORCA_LEFT_TO_DO.md` and live UI testing

---

## 1. Pulled upstream (`a6531f2` → `8394b23`)

Four commits landed from teammate `Chirayu1167` before this session started:

- `b884a21` — 9 P0 drift fixes (docs synced to INCOIS-only pipeline, honest
  `DataSource.UNAVAILABLE`, hazard wind fallback to sustained when gust is None,
  `/query` made async, OceanMap WMS date-templated URLs, PFZ bbox pre-filter,
  orchestrator 333-line block de-duplicated to `state.py`), PPT rebuild (`PPT.md`),
  real CI workflow (`.github/workflows/ci.yml`).
- `781bc9f` — `heatmap_scan.py` + `/heatmap/*` endpoints, 3 new eco polygons
  (Pichavaram, Chilika, Sundarbans → 8 total), hazard-aware A* routing
  (IMD CAP polygons block, current >1 m/s penalty), 5 new languages (as/ur/ne/si/mni → 22 total).
- `56981c9`, `8394b23` — README updates.

This pull resolved two `ORCA_LEFT_TO_DO.md` items on its own: **GEBCO bathymetry is
wired** into route planning (`data_connectors/bathymetry.py` + A*, `<10 m draft
blocks`, verified `geospatial_agent.py:463`), and part of the SAR matching work.

## 2. `840d5b4` — TODO-item fixes (3 backend test failures → green)

| Fix | Files |
|---|---|
| **Multilingual degraded-mode fallback** (items: `test_19_degraded_non_english_llm_outage`, `test_romanized_degraded_per_language`, `test_romanized_indic_script_unchanged`). Root causes: (a) the location-unresolved prompt was a hardcoded English string; (b) when the rules planner understood nothing (`intent=unknown`) for a non-English query with the LLM down, `_node_unsupported` returned the English generic fallback. Both paths now use the i18n layer: new `ASK_LOCATION` table in `i18n.py` (11 languages + `_FALLBACK` map), localized ask everywhere, and LLM-outage + non-English composes the honest localized limited-mode message with `routing_mode=degraded` | `i18n.py`, `orchestrator/__init__.py` |
| **SAR demo matching** (`test_integration_demo_pipeline`). The demo's synthetic known vessels were only injected when the *global* inventory was empty — any unrelated real fleet/user activity anywhere in India suppressed injection → all 5 demo detections UNKNOWN. Replaced with per-detection guarantee: real activity is matched first (spatial+temporal via `find_match`), any still-unmatched demo detection with a known-vessel offset gets a labelled-simulated synthetic. Demo is now deterministic 4 KNOWN / 1 UNKNOWN regardless of store state | `sar/engine.py` |
| **wind_divergence NoneType crash**. `analyze_wind_divergence(forecast_wind_kmh=None, ...)` (signature accepts None; `main.py` passes None by default) did arithmetic on None → `unsupported operand type(s) for /` masked by the orchestrator's catch-all. Added None guards for forecast AND observation wind, `result_to_dict` None-safe, regression test `test_none_forecast_wind_returns_unavailable_not_crash` | `wind_divergence.py`, `test_wind_divergence.py` |

Result: **109/109 pytest** (was 104/108).

Confirmed-blocked TODO items (no code change possible): MOSDAC/INCOIS/IMD
registered connectors (`isro_sources.py`, `satellite_wind.py`,
`imd_live.DISTRICT_IDS` — all `NotImplementedError`/empty pending API keys);
`flutter analyze` — no Flutter SDK on this machine.

## 3. `45faa7f` — "No PFZ available right now" quick-action toast

User report: chat PFZ queries worked, but the dashboard "Nearest PFZ" quick
action always toasted "No PFZ available right now".

Root cause: `PFZAgent.run()` and `HazardAgent.run()` return **tuples**
`(result, AgentTrace)`. `_gather_dashboard_inputs` passed the raw tuples into
`build_dashboard`, where `_card_pfz`/`_card_hazard`/`compute_readiness` do
`getattr(tuple, "distance_from_reference_km")` → always None → cards silently
omitted. Chat worked because the orchestrator unpacks the tuple.

Fix: unwrap both tuples in `_gather_dashboard_inputs` (OceanState was already
unpacked). Verified live: `POST /dashboard {lat:18.67, lon:73.89}` now returns
the pfz card (distance/bearing/center) + hazard card + readiness score. Note:
sst/wind/current/tide cards stay honestly omitted for an inland pin.

## 4. `f0fc6e8` — PFZ distance attributed to the wrong place in prose

User report: chat said "13.8 km from Mumbai" while the quick action (pinned
point ~100 km inland) said 130 km — "two different reference points".

Repro with `map_point=[18.67,73.89]` + question "…from Mumbai?": the PFZ math
was **already correct** (130.3 km, 253.4° from the pin — identical to the
dashboard), but the AI prose said "from Mumbai" because the narrative prompts
got the question text plus bare numbers with **no reference position**.

Fix (three layers):
- pfz summary dicts now carry `measured_from = reference_location.name`
  (`orchestrator/_summary_dicts` + `response_agent` fast path AND general path —
  the PFZ fast path has its own dict builder, which is why the first
  narrative-only fix didn't take effect end-to-end).
- `compose_narrative` and `generate_context_summary` get a REFERENCE POSITION
  rule: attribute figures to the resolved position, never to a place name
  merely mentioned in the question.
- UI `pfzCardMarkdown` ("OFFICIAL PFZ ADVISORY" card) now shows the actual
  target zone (`pfz.center_lat/lon` — the point distance/bearing refer to)
  instead of the landing centre's advisory position, plus a
  "From your location" row; `OrcaPfz` interface extended.

Verified live: same query now answers "…from your location (18.67° N, 73.89° E)…".

## 5. `c22d9a0` — Nearest PFZ quick action flew to a previous pin's zone

User report: pinned on the EAST coast, quick action flew to a WEST-coast zone;
chat was correct.

Root cause: `_runPfzOnMap` reused any pfz card already in `store.dashboard`
without checking it was fetched for the active location — a stale snapshot from
the previously pinned point survived the re-pin (`setMapPoint` triggers an
async refresh, but the click read the old snapshot first).

Fix: the snapshot is only trusted when its `location` matches the active pin
within 2 km; otherwise a fresh `/dashboard` is fetched for the current point
(`QuickActionsDock._snapshotMatches`). Verified: `/dashboard` for the east pin
(14.59, 81.12) returns the zone at 14.35, 80.63 (58.8 km WSW, off Nellore).

## 6. Tooling

- New **`start.bat`** one-click Windows launcher at the repo root: installs
  frontend deps on first run, runs `npm run dev -- --open` (vite auto-spawns
  the backend on :8000 and kills the tree on exit), opens the browser.
  Verified end-to-end: UI 200 on :3000, `/health` ok on :8000, clean shutdown.

## 7. Verification

- `python -m py_compile` all touched files → OK
- Full backend suite `python -m pytest test_*.py -q` → **109/109** (twice)
- `npx tsc --noEmit` → clean
- Live probes on `:8010`: `/dashboard` (west pin, east pin) and `/query`
  PFZ repro — all correct after fixes
- `start.bat` end-to-end run + clean shutdown

## 8. Remaining / next

- MOSDAC/IMD/Bhoonidhi API keys (externally blocked — biggest honest-degradation area)
- Flutter `analyze`/`build` once a Flutter SDK is available
- Watch the GitHub Actions CI run go green (workflow is new as of `b884a21`)
