# ORCA — Architecture

**ORCA** (Marine EcOsystem Reasoning with Collaborative Agents) · SIH 2026 · PS 26176 (ISRO)
FastAPI + LangGraph multi-agent backend. Live keyless data first; every value provenance-tagged with honest fallbacks.

![ORCA architecture (simple)](architecture.png)

<details>
<summary>Detailed view (every agent, connector and endpoint)</summary>

![ORCA architecture (detailed)](architecture_detailed.png)

</details>

## Flow (Mermaid)

```mermaid
flowchart TD
    subgraph CLIENTS["Clients"]
        APP["Fisher / Coastal App<br/>(chat · 11 Indic languages · map)"]
        GPS["Device GPS + destination"]
        SMS["Feature Phone (SMS)"]
    end

    subgraph API["API Layer — FastAPI (main.py)"]
        Q["POST /query<br/>(query, session_id?, device_gps?, destination?)"]
        REG["POST /users/register · POST /users/{id}/position"]
        ALERTS["GET /alerts/{user_id} (poll)<br/>GET /alerts/stream/{user_id} (SSE)"]
        VIZ["GET /viz/{session_id} (GeoJSON)<br/>GET /viz/{session_id}/series"]
    end

    subgraph RAIL["Proactive / State Rail"]
        MEM["Session Memory<br/>sessions.py · TTL 1h · Redis-ready"]
        MON["Proactive Monitor Agent #10<br/>asyncio 15-min loop · dedup"]
        BUS["Alert Bus (alerts.py)<br/>pub-sub → SSE · Twilio SMS"]
    end

    subgraph CORE["Agentic Core — LangGraph StateGraph (orchestrator.py)"]
        LANG["Language / Intent Agent #1<br/>11 Indic languages · EN normalization"]
        PLAN["Planning Agent #2<br/>intent · place · time/hour · agents_needed"]
        DISP["Dispatch node<br/>specialists in parallel"]
        OCEAN["Ocean-State Agent #4<br/>SST · waves · swell · wind · tide"]
        HAZ["Hazard / Alert Agent #5<br/>thresholds · IMD CAP cyclone/lightning/marine"]
        GEO["Geospatial Agent #6<br/>IMBL/MPA geofence · hazard-aware routes"]
        PFZ["PFZ Agent #3 (+ Trend)<br/>thermal-front scan · ranked zones"]
        SYN["Synthesis Agent #7<br/>reconcile · conflicts · verdict"]
        RESP["Response Agent #9<br/>answer in user's language"]
        TRACE["AgentTrace #8 (add-only channel)"]
    end

    LLM["llm_client.py → Groq openai/gpt-oss-120b<br/>(language · planning · synthesis · response)"]

    subgraph SRC["Data Source / Connector Layer (data_connectors/)"]
        OM["Open-Meteo Marine + Weather"]
        TIDE["UHSLC ERDDAP tide harmonics"]
        NOAA["NOAA ERDDAP: chlorophyll-a · ETOP180 depth"]
        CAP["IMD CAP RSS (keyless) + api.imd.gov.in (gated)"]
        ISRO["MOSDAC · INCOIS · data.gov.in (gated)"]
        OSM["OSM Nominatim geocoding"]
        BND["marine_boundaries.geojson<br/>India–SL IMBL · Sir Creek · MPAs"]
    end

    APP -->|"query"| Q
    GPS --> Q
    Q --> LANG --> PLAN --> DISP
    DISP --> OCEAN --> HAZ
    DISP --> PFZ
    DISP --> GEO
    OCEAN -.-> GEO
    HAZ --> SYN
    PFZ --> SYN
    GEO --> SYN
    SYN --> RESP --> Q
    PLAN <-.-> MEM
    REG --> MON
    MON -.->|"reuses .run()"| OCEAN & HAZ & GEO
    MON --> BUS
    BUS --> ALERTS
    BUS -->|"Twilio REST"| SMS
    OCEAN & PFZ --> OM
    OCEAN --> TIDE
    PFZ --> NOAA
    HAZ --> CAP
    HAZ -.-> ISRO
    PLAN --> OSM
    GEO --> BND
    GEO --> NOAA
    LANG & PLAN & SYN & RESP -.-> LLM
    CORE -.-> TRACE
```

## Component map (PS 26176 numbering)

| # | Component | File | Notes |
|---|---|---|---|
| 1 | Language / Intent | `agents/language_agent.py` | LLM detection of 11 Indic languages + Unicode-script fallback |
| 2 | Orchestrator / Planner | `orchestrator.py` | LangGraph StateGraph; LLM plan schema + rule fallback; parallel dispatch |
| 3 | PFZ | `agents/pfz_agent.py` | Official INCOIS/SAMUDRA daily advisory via nearest landing centre (KD-indexed); derived 25-pt SST-ring + SIM fallbacks |
| 4 | Ocean-State | `agents/ocean_state_agent.py` | Open-Meteo marine/weather; UHSLC harmonic tide; exceedance windows |
| 5 | Hazard / Alert | `agents/hazard_agent.py` + `data_connectors/imd_cap.py` | Wave/gust thresholds; live IMD CAP (cyclone, lightning, marine) polygon hit-test |
| 6 | Geospatial | `agents/geospatial_agent.py` | Ray-cast IMBL/MPA geofence; hazard-aware route detours; depth check |
| 7 | Synthesis | `agents/synthesis_agent.py` | Reconciles findings, flags conflicts, verdict + confidence |
| 8 | Explainability | `orchestrator.py` (`operator.add` channel), `models.py` | Add-only AgentTrace + per-field provenance |
| 9 | Response | `agents/response_agent.py` | Final answer in detected language, anti-hallucination rules |
| 10 | Proactive Monitor | `agents/proactive_monitor.py`, `alerts.py` | 15-min asyncio loop per user; SSE + Twilio SMS delivery; dedup |

## Data-source tiers

- **Tier 1 (official/live):** IMD CAP RSS (keyless, signed), api.imd.gov.in (key-gated), UHSLC tide gauges, MOSDAC/INCOIS (key-gated)
- **Tier 2 (derived/live):** Open-Meteo marine + weather, NOAA ERDDAP (chlorophyll-a, ETOP180 bathymetry), OSM Nominatim
- **Tier 3 (local/seeded):** `data/marine_boundaries.geojson` (digitized treaties), seeded last-resort values — always labelled

Every numeric field carries a `DataSource` tag (`live` / `tide_gauge_model` / `derived` / `simulated`); an unreachable feed is reported as *unverifiable*, never *clear*.
