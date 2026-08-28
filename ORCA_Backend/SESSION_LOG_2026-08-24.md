# ORCA Session Log — 2026-08-24

## Summary

Replaced the gated IMD API dependency with a keyless official feed, removed
nearly all hardcoded/simulated input data, and validated everything end-to-end
with live runs. Final state: every agent answer is driven by real data except
chlorophyll when its satellite host is unreachable (honestly tagged per-run).

---

## 1. Hazard Agent — real cyclone warnings without the IMD API key problem

**Problem:** `api.imd.gov.in` returns HTTP 401 without an issued key
(IP-whitelist approval process), has an incomplete TLS chain, and unpublished
object IDs. Effectively unusable for a hackathon prototype.

**Solution:** IMD's own **CAP (Common Alerting Protocol) alerts feed** —
`https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml`, linked publicly from
mausam.imd.gov.in/responsive/apis.php. Verified keyless HTTP 200, no TLS issues,
digitally-signed CAP 1.2 XMLs with severity/urgency/onset/expires/area polygons.

### New file: `data_connectors/imd_cap.py`
- Fetches RSS → each item's CAP XML → parses event/severity/headline/
  instruction/area polygons (`lat,lon` pairs).
- Drops expired `cap:info` blocks by comparing `expires` to UTC now.
- `fetch_cyclone_status(location)` — drop-in replacement matching the old
  `imd_live.fetch_cyclone_status()` contract, plus polygon hit-testing of the
  user's point (`point_in_polygon` ray casting).
- Marine-relevance keyword filters (`_MARINE_TERMS`, `_CYCLONE_TERMS`).

### Rewired: `agents/hazard_agent.py`
- CAP feed is Tier 1 primary source (with location-aware zone coverage:
  "affects this area" vs "active elsewhere" — both force UNSAFE).
- Gated `api.imd.gov.in` connector retained only as secondary fallback if CAP
  is unreachable; both failing still reports honestly as "unverifiable".
- Trace/evidence tags updated (`DataSource.IMD_CAP_LIVE` added in models.py).

Verified: RSS fetched live; expired alerts correctly filtered; Odisha polygon
contains offshore-Odisha point and not Ratnagiri; full pipeline shows
`[cyclone=clear]` sourced from CAP on every query.

---

## 2. Agent-count audit vs the project PDF

PDF Section 7.2 defines **10 components**. Implemented status:

| # | Component | Status |
|---|---|---|
| 1 | Language/Intent Agent | Real |
| 2 | Orchestrator/Planner Agent | Real (LangGraph + LLM planning) |
| 3 | PFZ Agent | Now **derived from live SST field** (was seeded RNG) |
| 4 | Ocean-State Agent | SST/waves/wind live; **tide now real** (was simulated); chlorophyll live-when-reachable |
| 5 | Hazard/Alert Agent | Real (CAP feed) |
| 6 | Geospatial Reasoning Agent | Real math on real static boundaries; GEBCO TODO |
| 7 | Risk-Scoring/Synthesis Agent | Real |
| 8 | Explainability Trace Layer | Embedded as AgentTrace logging (per PDF note) |
| 9 | Response Agent | Real |
| 10 | Proactive Monitor Agent | **Not yet implemented** |

So 9 of 10 components exist; the "6 main" PS roles (#1–6) are all present.

---

## 3. De-hardcoding pass ("real and accurate")

### New file: `data_connectors/tide.py` — REAL tide prediction
- Source: UHSLC (University of Hawaii Sea Level Center) Fast-Delivery hourly
  tide gauges via keyless ERDDAP. Verified Indian stations: Minicoy (153),
  Vishakhapatnam (157), Cochin (174), Port Blair (908).
- Method: fetch station's last ≤365 days of observed sea level → pure-Python
  least-squares harmonic fit of 8 constituents (M2 S2 N2 K2 K1 O1 P1 Q1 +
  mean level; normal equations + Gaussian elimination, no numpy) → predict at
  requested UTC hour. This is exactly the "locally computed harmonic
  prediction model" the PDF documents as Tier 2.
- Stations tried nearest-first within a 400 km cap; falls back through the
  list; refuses beyond it rather than extrapolating fake accuracy.
- Validated live: Cochin gauge 5.5 km from test point, fit RMS 0.09 m over 609
  samples, clean diurnal-dominant cycle over 48 h; Vizag fit RMS 0.22 m over
  6544 samples; Ratnagiri correctly refused (no gauge in range).

### New file: `data_connectors/chlorophyll.py` — satellite chlorophyll-a
- Target: NOAA CoastWatch ERDDAP `erdMWchla8day` (MODIS-Aqua 8-day composite,
  global, keyless). Request implemented and auto-flips fields to LIVE whenever
  the host is reachable.
- Reality check documented in-file: coastwatch.pfeg.noaa.gov is TCP-blocked
  from the dev machine (verified via Python AND PowerShell); polarwatch has no
  India-covering chl dataset; PIFSC is Pacific-only; Ifremer has broken TLS;
  NASA OpenDAP rate-limited (HTTP 429). Until reachable, calls fail fast
  (6 s timeout + 10 min negative cache) into the tagged seeded fallback.
- Nothing ever presents the fallback value as satellite data.

### New file: `data_connectors/geocode.py` — free-text place names
- OpenStreetMap Nominatim (`countrycodes=in`), keyless, usage-policy-compliant
  UA, in-process result cache. Honest miss = None; network failure raises.

### Rewired: `orchestrator.py`
- Planning schema's `location_name` changed from a 4-key enum to free text;
  LLM prompt updated to copy any Indian coastal place name.
- `resolve_location()`: known-key cache → session geocode cache → live
  geocode → honest default point. `KNOWN_LOCATIONS` is now just an offline
  cache, not a whitelist.
- Rule-based no-LLM path extracts place candidates via regex ("near …",
  "off …") before falling back to unknown.

### Rewired: `agents/ocean_state_agent.py`
- Tide: `_get_tide()` → real UHSLC harmonic prediction at the target local
  hour, tagged `DataSource.TIDE_GAUGE_MODEL`; seeded value only where no
  gauge is in range (tagged SIMULATED).
- Chlorophyll: `_get_chlorophyll()` → ERDDAP pixel when reachable (LIVE tag),
  else seeded (SIMULATED tag).
- `_get_marine()` hardening: coastal coordinates that land outside Open-Meteo's
  marine grid return HTTP 200 with all-null series — retries a small offshore
  cross of offsets with backoff before degrading the whole reading.
- Per-field provenance always recorded; trace summary lists any simulated
  fields explicitly.

### Rewired: `agents/pfz_agent.py`
- Zone placement no longer RNG: samples live SST at the reference point plus
  three rings (12/25/40 km × 8 bearings = 25 points) in ONE batched Open-Meteo
  request; the strongest thermal gradient cell wins (classic PFZ front proxy).
- Tagged `DataSource.DERIVED_LIVE` ("derived_from_live_data"), confidence 0.65;
  land/coastal null samples skipped (needs ≥60% valid ring); deterministic
  seeded zone remains only as last-resort error fallback (SIMULATED).
- Bhuvan official PFZ layer still coded but disabled pending endpoint
  verification (unchanged).

### Other updates
- `models.py`: added `TIDE_GAUGE_MODEL`, `DERIVED_LIVE`, `IMD_CAP_LIVE`.
- `test_run.py`: added a non-hardcoded place query ("Gopalpur") exercising
  live geocoding; provenance printer now shows exact per-field tags.
- `README.md`: provenance table rewritten; known-simplifications updated.
- `.env.example`: notes that cyclone/warning checks need no key.

---

## 4. End-to-end validation (live runs)

Final `python test_run.py` run (7 queries, LLM mode):
- Ratnagiri / Kochi / Odisha-route / Marathi queries: LIVE SST, waves, wind;
  Kochi tide from the REAL Cochin gauge (0.58 m, tide_gauge_model); CAP feed
  clear; verdicts CAUTION/SAFE per thresholds.
- PFZ Kochi: **25 km @ 225° derived from the live SST field**
  (`derived_from_live_data`), not random.
- Gopalpur query: geocoded live to (19.26, 84.91) and answered; during one run
  Open-Meteo intermittently returned all-null series (upstream flakiness under
  burst load) so the reading degraded honestly to SIM-tagged values — the
  offset+backoff retry recovers it when the upstream settles (verified:
  isolated rerun returned fully LIVE data for the same point).
- Chlorophyll remained SIM everywhere (pfeg host blocked on this network),
  disclosed in every response.

## Remaining known gaps (documented, not hidden)

1. Chlorophyll is seeded while pfeg.noaa.gov stays unreachable from this
   network — flips to live satellite data automatically elsewhere.
2. Tide needs a UHSLC gauge within 400 km (Cochin/Vizag/Minicoy/Port Blair);
   e.g. Ratnagiri currently degrades to a tagged seeded value.
3. Bhuvan official PFZ layer disabled until endpoint verification.
4. GEBCO bathymetry for route depth checks (PDF roadmap) still TODO.
5. Proactive Monitor Agent (#10) not yet built.
