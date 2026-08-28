"""
Orchestrator -- implemented as a LangGraph StateGraph.

This is the "brain" of the system (see ORCA_Project_Documentation.pdf
Section 7): it takes a raw user query, detects its language, plans what's
being asked, fans the request out to the relevant specialist agents IN
PARALLEL, then lets them discuss, reconciles their findings and composes
one answer in the user's language -- with a full explainability trace
attached.

Graph topology (mirrors the documented 10-component pipeline):

                       START
                         |
                  language_intent                    (PS #1)
                         |
                     planning                          (PS #2)
          [which specialists does THIS query need?]
                         |
                     specialists  -- runs the selected agents in
                          |            PARALLEL threads inside one
                          |            graph step:
                          |              ocean_state -> hazard (PS #4/#5)
                          |              pfz                (PS #3)
                          |              geospatial         (PS #6)
                          |
                      discussion    <- round-table: agents read each
                          |            other's findings and debate
                          |            (challenge/clarify/concede)
                          |
                       synthesis     <- single reconciled pass   (PS #7)
                         |
                      response                           (PS #9)
                         |
                        END

Specialist results and AgentTrace entries accumulate in shared graph state
via operator.add channels. The Planner decides WHICH specialists run per
query ("not every query needs every agent"); hazard always consumes the
ocean reading, so both run in the same worker while PFZ and Geospatial run
truly concurrently alongside them.

Why a dispatch node instead of native per-agent graph branches: LangGraph's
pregel join re-fires a fan-in node once PER incoming branch completion when
branches end in different supersteps (hazard finishes ~3 s after ocean;
geospatial may finish sooner), which duplicated synthesis/response calls.
The dispatch node guarantees exactly one synthesis pass while keeping real
wall-clock parallelism across specialist agents.

If the LLM is unavailable every step falls back to deterministic behaviour,
and if the langgraph package itself is missing handle_query() degrades to
the identical sequential calls. The demo never hard-crashes.
"""

from __future__ import annotations

import operator
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, List, Optional, TypedDict

import llm_client
import sessions as session_store
from agents.discussion_agent import DiscussionAgent
from agents.geospatial_agent import GeospatialAgent
from agents.hazard_agent import HazardAgent, get_thresholds
from agents.language_agent import LanguageAgent
from agents.ocean_state_agent import OceanStateAgent
from agents.pfz_agent import PFZAgent
from agents.response_agent import ResponseAgent
from agents.synthesis_agent import SynthesisAgent
from agents.trend_agent import TrendAgent
from models import (
    AgentTrace,
    DataSource,
    GeofenceStatus,
    Location,
    OrchestratorResponse,
    PFZRecommendation,
    QueryContext,
    RiskAssessment,
    RoutePlan,
    SafetyStatus,
)

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive, keeps the demo alive
    LANGGRAPH_AVAILABLE = False


# Pre-seeded coordinate cache for frequently-asked demo locations. These are
# real coordinates; the resolver below now geocodes ANY free-text place name
# via OpenStreetMap Nominatim (data_connectors/geocode.py) and treats this
# dict as an offline cache/fallback only -- not a whitelist.
KNOWN_LOCATIONS = {
    "ratnagiri": Location(name="Ratnagiri Coast", lat=16.9902, lon=73.3120),
    "kochi": Location(name="Kochi Coast", lat=9.9312, lon=76.2673),
    "visakhapatnam": Location(name="Visakhapatnam Coast", lat=17.6868, lon=83.2185),
    "odisha": Location(name="Odisha Coast (Puri)", lat=19.8135, lon=85.8312),
}
DEFAULT_LOCATION = Location(name="Unknown Coast (default demo point)", lat=15.5, lon=73.8)

_geocode_cache: dict[str, Location] = {}


def resolve_location(place_name: str) -> Location:
    """Free-text place name -> Location.

    Order: exact known-key hit -> in-session geocode cache -> live
    Nominatim lookup -> DEFAULT_LOCATION. Every resolved point is real;
    nothing is invented when resolution fails (the default point is named
    honestly as such).
    """
    key = " ".join((place_name or "").strip().lower().split())
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key]
    if key in _geocode_cache:
        return _geocode_cache[key]
    if key and key != "unknown":
        try:
            import data_connectors.geocode as geocode

            hit = geocode.geocode(key)
        except Exception as exc:  # network down etc. -> honest default below
            import logging

            logging.getLogger("orca.orchestrator").warning(
                "geocoding '%s' failed (%s); using default location",
                place_name, exc,
            )
            return DEFAULT_LOCATION
        if hit:
            lat, lon, display = hit
            loc = Location(name=display.split(",")[0].strip() + " Coast", lat=lat, lon=lon)
            _geocode_cache[key] = loc
            return loc
    return DEFAULT_LOCATION

KNOWN_TIME_WINDOWS = ["today", "tomorrow", "tomorrow_morning"]

# Addressable specialists for "direct" mode (mode="agent"). The UI lists
# these via GET /agents. `requires` are extra agents silently run first
# because the target consumes their output (hazard needs an ocean reading).
SPECIALIST_REGISTRY = {
    "ocean_state": {
        "name": "Ocean-State Agent",
        "description": (
            "Live SST, wave height, wind and gusts, harmonic tides and "
            "chlorophyll for any Indian coastal point"
        ),
        "requires": [],
    },
    "hazard": {
        "name": "Hazard Agent",
        "description": (
            "Threshold-based safety verdicts plus live IMD cyclone/marine "
            "CAP alert checks (consumes a fresh ocean reading)"
        ),
        "requires": ["ocean_state"],
    },
    "pfz": {
        "name": "PFZ Agent",
        "description": (
            "Nearest potential fishing zones derived from live sea-surface "
            "temperature fronts around you"
        ),
        "requires": [],
    },
    "geospatial": {
        "name": "Geospatial Agent",
        "description": (
            "IMBL/MPA boundary geofencing and weather-aware safe-route "
            "planning from your GPS or destination"
        ),
        "requires": [],
    },
    "trend": {
        "name": "Trend Agent",
        "description": (
            "Months-long SST/chlorophyll trend analysis with correlation "
            "for 'why has X changed' questions"
        ),
        "requires": [],
    },
}

# intent -> default specialist set when the planner names none explicitly
INTENT_DEFAULT_AGENTS = {
    "safety_check": ["OceanStateAgent", "HazardAgent", "GeospatialAgent"],
    "pfz_lookup": ["PFZAgent", "OceanStateAgent", "GeospatialAgent"],
    "route_plan": ["GeospatialAgent", "OceanStateAgent", "HazardAgent"],
    "geofence_check": ["GeospatialAgent"],
    "hazard_alerts": ["HazardAgent", "OceanStateAgent"],
    "trend_analysis": ["TrendAgent"],
    "zone_scan": ["PFZAgent", "OceanStateAgent", "HazardAgent", "GeospatialAgent"],
}

PLANNING_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "safety_check",    # safe to go into/on the sea?
                "pfz_lookup",      # where is the nearest fishing zone?
                "route_plan",      # safest route from A to B
                "geofence_check",  # am I near/inside restricted waters?
                "hazard_alerts",   # any cyclone/lightning/advisory for my area?
                "trend_analysis",  # WHY has something changed over weeks/months?
                "zone_scan",       # which zones to seek / avoid around me?
                "unknown",
            ],
            "description": (
                "The query type. safety_check = is it safe to venture out "
                "(fishing/boating). pfz_lookup = finding fishing zones. "
                "route_plan = navigating somewhere safely. geofence_check = "
                "boundary/restricted-zone proximity. hazard_alerts = active "
                "weather/marine alerts. trend_analysis = analytical questions "
                "about how SST/chlorophyll/fish productivity changed over a "
                "period and why. zone_scan = ranked good/avoid zones around an "
                "area. unknown if nothing fits."
            ),
        },
        "location_name": {
            "type": "string",
            "description": (
                "The coastal place name mentioned in the query (free text -- "
                "any Indian coastal town/village/port/region, e.g. 'Gopalpur', "
                "'Ratnagiri', 'Kochi'). Use 'same' when the query refers back "
                "to the previous location without naming one. Use 'unknown' "
                "only if no place at all is mentioned."
            ),
        },
        "time_window": {
            "type": "string",
            "enum": KNOWN_TIME_WINDOWS,
            "description": "Roughly when the user is asking about.",
        },
        "target_hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": (
                "Exact local hour of day (0-23) if the user names one, e.g. "
                "'tomorrow at 10 am' -> 10. Omit entirely when no specific "
                "hour is mentioned."
            ),
        },
        "months_back": {
            "type": "integer",
            "minimum": 3,
            "maximum": 24,
            "description": (
                "For trend_analysis: how many months of history to analyse "
                "(e.g. 'last 3 months' -> 3). Omit for other intents."
            ),
        },
        "agents_needed": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "OceanStateAgent", "HazardAgent",
                    "PFZAgent", "GeospatialAgent", "TrendAgent",
                ],
            },
            "description": (
                "Specialist agents genuinely needed to answer THIS query."
            ),
        },
        "why": {
            "type": "string",
            "description": "One sentence explaining the planning decision.",
        },
    },
    "required": ["intent", "location_name", "time_window", "agents_needed", "why"],
}


class Intent:
    SAFETY_CHECK = "safety_check"
    PFZ_LOOKUP = "pfz_lookup"
    ROUTE_PLAN = "route_plan"
    GEOFENCE_CHECK = "geofence_check"
    HAZARD_ALERTS = "hazard_alerts"
    TREND_ANALYSIS = "trend_analysis"
    ZONE_SCAN = "zone_scan"
    UNKNOWN = "unknown"


class ORCAGraphState(TypedDict):
    """Shared state flowing through the graph.

    `traces` is an add-only channel: every node appends its own AgentTrace
    entries and LangGraph merges them across parallel branches -- exactly how
    the final architecture merges parallel-agent findings.
    """

    raw_query: str
    session_id: str
    device_gps: Optional[tuple]
    destination: Optional[Location]
    vessel_class: str

    normalized_query: str
    language: str
    plan: dict
    plan_mode: str
    location: Location
    context: QueryContext

    ocean_state: Optional[object]           # OceanStateReading
    risk: Optional[object]                  # RiskAssessment
    pfz: Optional[object]                   # PFZRecommendation
    geofence: Optional[object]              # GeofenceStatus
    route: Optional[object]                 # RoutePlan
    trend: Optional[object]                 # TrendAnalysis
    discussion: Optional[dict]              # {"turns": [...], "consensus": str}
    synthesis: Optional[dict]               # reconciled verdict + conflicts

    response: Optional[OrchestratorResponse]
    traces: Annotated[List[AgentTrace], operator.add]


class Orchestrator:
    def __init__(self):
        self.language_agent = LanguageAgent()
        self.ocean_state_agent = OceanStateAgent()
        self.hazard_agent = HazardAgent()
        self.pfz_agent = PFZAgent()
        self.geospatial_agent = GeospatialAgent()
        self.trend_agent = TrendAgent()
        self.discussion_agent = DiscussionAgent()
        self.synthesis_agent = SynthesisAgent()
        self.response_agent = ResponseAgent()
        self.app = self._build_graph() if LANGGRAPH_AVAILABLE else None

    # ------------------------------------------------------------------
    # Graph assembly
    # ------------------------------------------------------------------
    def _build_graph(self):
        g = StateGraph(ORCAGraphState)
        g.add_node("language_intent", self._node_language)
        g.add_node("planning", self._node_planning)
        g.add_node("specialists", self._node_dispatch)
        g.add_node("discussion", self._node_discussion)
        g.add_node("synthesis", self._node_synthesis)
        g.add_node("response", self._node_response)
        g.add_node("unsupported", self._node_unsupported)

        g.add_edge(START, "language_intent")
        g.add_edge("language_intent", "planning")

        g.add_conditional_edges(
            "planning",
            lambda state: (
                "specialists"
                if self._selected_specialists(
                    state["plan"],
                    live_position=bool(state.get("device_gps") or state.get("destination")),
                )
                else "unsupported"
            ),
            {"specialists": "specialists", "unsupported": "unsupported"},
        )
        g.add_edge("specialists", "discussion")
        g.add_edge("discussion", "synthesis")
        g.add_edge("synthesis", "response")
        g.add_edge("response", END)
        g.add_edge("unsupported", END)
        return g.compile()

    def _selected_specialists(
        self, plan: dict, live_position: bool = False
    ) -> List[str]:
        """Resolve the planner's decision into concrete specialist nodes.

        The planner's `agents_needed` is intersected with the intent's
        sensible default set (the planner may name extra agents; the
        defaults define what this intent actually warrants). Empty or
        unmatched -> fall back to the full default set for the intent.
        `live_position`: when the client explicitly sent device GPS or a
        destination, the Geospatial Agent ALWAYS runs -- the user is asking
        about their specific spot even if the planner missed it.
        """
        requested = {a for a in (plan.get("agents_needed") or [])}
        defaults = INTENT_DEFAULT_AGENTS.get(plan["intent"], [])
        chosen = requested & set(defaults) or set(defaults)
        # Dependency repair: hazard needs an ocean reading.
        if "HazardAgent" in chosen:
            chosen.add("OceanStateAgent")
        if live_position:
            chosen.add("GeospatialAgent")
        nodes: List[str] = []
        if "TrendAgent" in chosen and plan["intent"] == Intent.TREND_ANALYSIS:
            nodes.append("trend")
            return nodes
        if "OceanStateAgent" in chosen:
            nodes.append("ocean_state")
        if "PFZAgent" in chosen:
            nodes.append("pfz")
        if "GeospatialAgent" in chosen:
            nodes.append("geospatial")
        return nodes

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------
    def handle_query(
        self,
        raw_query: str,
        session_id: str | None = None,
        device_gps: tuple | None = None,
        destination: Location | None = None,
        mode: str = "panel",
        target_agent: str | None = None,
        vessel_class: str | None = None,
    ) -> OrchestratorResponse:
        session_id = session_id or str(uuid.uuid4())
        initial: ORCAGraphState = {
            "raw_query": raw_query,
            "session_id": session_id,
            "device_gps": device_gps,
            "destination": destination,
            "vessel_class": vessel_class or "small_fishing_boat",
            "traces": [],
        }
        if mode == "agent" and target_agent in SPECIALIST_REGISTRY:
            return self._handle_single_agent(initial, target_agent)
        return self._handle_query_panel(initial)

    # ------------------------------------------------------------------
    # Panel mode: full graph incl. the round-table discussion
    # ------------------------------------------------------------------
    def _handle_query_panel(self, initial: dict) -> OrchestratorResponse:
        if self.app is not None:
            final_state = self.app.invoke(initial)
            response = final_state["response"]
            response.mode = "panel"
            response.answered_by = (
                "ORCA panel (specialists discussed before answering)"
            )
            return response
        response = self._handle_query_sequential(initial)
        response.mode = "panel"
        response.answered_by = "ORCA panel (specialists discussed before answering)"
        return response

    # ------------------------------------------------------------------
    # Nodes -- thin adapters over the shared step helpers below, so the
    # graph path and the no-langgraph fallback share one code path.
    # ------------------------------------------------------------------
    def _node_language(self, state: ORCAGraphState) -> dict:
        result, trace = self.language_agent.run(state["raw_query"])
        return {
            "normalized_query": result["normalized_query"],
            "language": result["language"],
            "traces": [trace],
        }

    def _node_planning(self, state: ORCAGraphState) -> dict:
        plan, plan_mode, location, context, trace = self._step_plan(
            state["normalized_query"], state["raw_query"], state
        )
        return {
            "plan": plan,
            "plan_mode": plan_mode,
            "location": location,
            "context": context,
            "traces": [trace],
        }

    def _node_dispatch(self, state: ORCAGraphState) -> dict:
        """Run every selected specialist agent.

        Phase 1 (parallel): Ocean-State -> Hazard chain AND PFZ.
        Phase 2 (after phase 1): Geospatial, so the route planner can avoid
        the zones Hazard just flagged (P1 #7) -- it is pure geometry (<10 ms),
        so serialising it costs nothing while making routes weather-aware.
        All AgentTrace entries land on the add-only traces channel. One
        specialist failing never kills the query -- it is logged and skipped.
        """
        plan = state["plan"]
        ctx = state["context"]
        location = state["location"]
        selected = self._selected_specialists(
            plan,
            live_position=bool(state.get("device_gps") or state.get("destination")),
        )
        results: dict = {}
        hour = plan.get("target_hour")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}

            def _ocean_then_hazard():
                thr = get_thresholds(ctx.vessel_class)
                reading, t1 = self.ocean_state_agent.run(
                    location, plan["time_window"], target_hour=hour,
                    thresholds=thr,
                )
                risk, t2 = self.hazard_agent.run(reading, ctx.vessel_class)
                return (reading, t1), (risk, t2)

            if "trend" in selected:
                months = int(plan.get("months_back") or 6)
                futures["trend"] = pool.submit(
                    self.trend_agent.run, location, months
                )
            if "ocean_state" in selected:
                futures["ocean_hazard"] = pool.submit(_ocean_then_hazard)
            if "pfz" in selected:
                futures["pfz"] = pool.submit(
                    self.pfz_agent.run, location, None,
                    plan["time_window"]
                )

            # ---- phase 1 ----
            for key in ("trend", "ocean_hazard", "pfz"):
                if key in futures:
                    try:
                        results[key] = futures[key].result(timeout=240)
                    except Exception as exc:
                        import logging

                        logging.getLogger("orca.orchestrator").warning(
                            "%s failed (%s: %s); continuing without it",
                            key, type(exc).__name__, exc,
                        )
                        results[key] = None
                    del futures[key]

            # ---- phase 2: geospatial now knows hazard flags ----
            if "geospatial" in selected:
                ocean_hazard = results.get("ocean_hazard")
                risk = ocean_hazard[1][0] if ocean_hazard else None
                hazard_labels = (
                    [f.label for f in risk.flags] if risk else []
                )
                exceedance = (
                    getattr(risk, "exceedance_windows", []) if risk else []
                )
                for w in exceedance or []:
                    hazard_labels.append(f"{w.metric} > {w.threshold}{w.unit} "
                                         f"{w.start_local}..{w.end_local}")
                try:
                    results["geospatial"] = pool.submit(
                        self.geospatial_agent.run,
                        location,
                        device_gps=ctx.device_gps,
                        destination=ctx.destination,
                        hazard_zone_names=hazard_labels,
                    ).result(timeout=180)
                except Exception as exc:
                    import logging

                    logging.getLogger("orca.orchestrator").warning(
                        "geospatial failed (%s: %s); continuing without it",
                        type(exc).__name__, exc,
                    )
                    results["geospatial"] = None

        update: dict = {"traces": []}
        if results.get("ocean_hazard"):
            (reading, o_trace), (risk, h_trace) = results["ocean_hazard"]
            update["ocean_state"] = reading
            update["risk"] = risk
            update["traces"].extend([o_trace, h_trace])
        if results.get("pfz"):
            pfz, p_trace = results["pfz"]
            update["pfz"] = pfz
            update["traces"].append(p_trace)
        if results.get("geospatial"):
            (geofence, route), g_trace = results["geospatial"]
            update["geofence"] = geofence
            if route is not None:
                update["route"] = route
            update["traces"].append(g_trace)
        if results.get("trend"):
            trend, tr_trace = results["trend"]
            update["trend"] = trend
            update["traces"].append(tr_trace)
        return update

    def _node_discussion(self, state: ORCAGraphState) -> dict:
        """Round-table: specialists read each other's findings and debate."""
        transcript, trace = self.discussion_agent.run(
            state["context"],
            ocean_state=state.get("ocean_state"),
            risk=state.get("risk"),
            pfz=state.get("pfz"),
            geofence=state.get("geofence"),
            route=state.get("route"),
            trend=state.get("trend"),
        )
        return {"discussion": transcript, "traces": [trace]}

    def _node_synthesis(self, state: ORCAGraphState) -> dict:
        synthesis, synth_trace = self.synthesis_agent.run(
            state["context"],
            state.get("ocean_state"),
            state.get("risk"),
            pfz=state.get("pfz"),
            geofence=state.get("geofence"),
            route=state.get("route"),
            trend=state.get("trend"),
            discussion=state.get("discussion") or {},
        )
        return {"synthesis": synthesis, "traces": [synth_trace]}

    def _node_response(self, state: ORCAGraphState) -> dict:
        answer, resp_trace = self.response_agent.run(
            state["context"], state["synthesis"],
            ocean_state=state.get("ocean_state"),
            risk=state.get("risk"),
            pfz=state.get("pfz"),
            geofence=state.get("geofence"),
            route=state.get("route"),
            trend=state.get("trend"),
            discussion=state.get("discussion") or {},
        )
        response = self._assemble_response(state, answer)
        response.trace.append(resp_trace)
        return {"response": response, "traces": [resp_trace]}

    def _node_unsupported(self, state: ORCAGraphState) -> dict:
        trace = AgentTrace(
            agent_name="Orchestrator",
            action="No specialist agent matched this intent",
            result_summary="Returned fallback response",
            data_sources=[],
            duration_ms=0.0,
        )
        return {
            "response": OrchestratorResponse(
                answer=(
                    "I can answer questions like 'Is it safe to fish near Ratnagiri "
                    "tomorrow?', 'Where is the nearest fishing zone?', 'Am I close "
                    "to a restricted boundary?' or 'What is the safest route to "
                    "<place>?'. Other query types are on the roadmap."
                ),
                status=SafetyStatus.CAUTION,
                reasoning=["Query intent not yet supported by an active specialist agent."],
                evidence_sources=[],
                trace=list(state["traces"]) + [trace],
                language=state.get("language", "en"),
            ),
            "traces": [trace],
        }

    # ------------------------------------------------------------------
    # Shared step helpers (used by graph nodes AND the sequential fallback)
    # ------------------------------------------------------------------
    def _step_plan(self, normalized_query: str, raw_query: str, state: ORCAGraphState):
        prior = session_store.get(state["session_id"])
        plan, plan_mode = self._plan(normalized_query, prior=prior)

        # Multi-turn memory: 'same'/'unknown' location or hour falls back to
        # what this conversation already established (P0 #3).
        if prior is not None:
            loc_name = str(plan.get("location_name") or "").lower()
            if loc_name in ("", "same", "unknown", "there", "here"):
                if prior.location_name:
                    plan["location_name"] = prior.location_name
            elif prior.lat is not None:
                pass  # new explicit place wins; stored below
            if not plan.get("target_hour") and prior.target_hour is not None \
                    and plan["intent"] == prior.last_intent and prior.time_window == plan["time_window"]:
                plan["target_hour"] = None  # stale hour only for identical asks
            if prior.language and plan_mode == "llm":
                pass  # language agent result flows via state anyway

        location = resolve_location(plan["location_name"])

        device_gps = state.get("device_gps") or (
            tuple(prior.device_gps) if (prior and prior.device_gps) else None
        )
        destination = state.get("destination") or (
            Location(**prior.destination) if (prior and prior.destination) else None
        )

        context = QueryContext(
            raw_query=raw_query,
            location=location,
            time_window=plan["time_window"],
            session_id=state["session_id"],
            language=state.get("language", "en"),
            device_gps=device_gps,
            destination=destination,
            target_hour=plan.get("target_hour"),
            vessel_class=state.get("vessel_class") or "small_fishing_boat",
        )

        # Persist the turn for the next follow-up.
        session_store.upsert(
            state["session_id"],
            location_name=plan["location_name"] if plan["location_name"] != "unknown" else "",
            lat=location.lat, lon=location.lon,
            time_window=plan["time_window"],
            target_hour=plan.get("target_hour"),
            language=state.get("language", "en"),
            device_gps=list(device_gps) if device_gps else None,
            destination=(
                {"lat": destination.lat, "lon": destination.lon, "name": destination.name}
                if destination else None
            ),
            last_intent=plan["intent"],
            last_query=raw_query,
        )

        dispatch_chain = (
            " -> ".join([
                *self._selected_specialists(
                    plan,
                    live_position=bool(state.get("device_gps") or state.get("destination")),
                ),
                "SynthesisAgent",
            ])
            or "(no specialist agents)"
        )
        trace = AgentTrace(
            agent_name="PlanningAgent",
            action=(
                f"Parsed query [mode={plan_mode}] intent='{plan['intent']}', "
                f"location='{location.name}', time_window='{plan['time_window']}'"
            ),
            result_summary=f"{plan['why']} Dispatching to {dispatch_chain}.",
            data_sources=[],
            duration_ms=plan["duration_ms"],
        )
        return plan, plan_mode, location, context, trace

    # Data-tier labels (PDF Sec 9/16) for the evidence register.
    _TIER_LIVE = ("Tier 2", "live external feed")
    _TIER_DERIVED = ("Tier 2/3", "derived from live data")
    _TIER_SIM = ("Tier 3", "simulated / seeded fallback")
    _TIER_USER = ("Tier 1", "user device / user input")

    @staticmethod
    def _tier_for(source: str) -> tuple[str, str]:
        s = str(source)
        if s == DataSource.SIMULATED.value:
            return Orchestrator._TIER_SIM
        if s in (DataSource.TIDE_GAUGE_MODEL.value, DataSource.DERIVED_LIVE.value,
                 DataSource.STATIC_DERIVED.value):
            return Orchestrator._TIER_DERIVED
        return Orchestrator._TIER_LIVE

    def _score_and_tiers(self, state: ORCAGraphState,
                         conflicts: list[str]) -> tuple[float, list[dict]]:
        """Numeric confidence in [0,1] + tiered evidence register.

        score = 0.55 * live_fraction(provenance)
              + 0.30 * hazard verdict confidence (or ocean input confidence)
              + 0.15 * cross-agent agreement (1.0 clean, 0.5 when conflicts)
        """
        tiers: list[dict] = []
        seen: set[str] = set()

        def add(source: str) -> None:
            if not source or source in seen:
                return
            seen.add(source)
            tier, kind = self._tier_for(source)
            tiers.append({"source": source, "tier": tier, "kind": kind})

        risk: RiskAssessment | None = state.get("risk")
        ocean = state.get("ocean_state")
        geofence = state.get("geofence")

        sources: list[str] = []
        if ocean is not None:
            sources.extend((ocean.field_sources or {}).values())
            add(ocean.source.value)
        if risk is not None:
            for ds in getattr(risk, "evidence_sources", []) or []:
                add(getattr(ds, "value", str(ds)))
        if geofence is not None:
            sources.append(DataSource.STATIC_DERIVED.value)
        if state.get("device_gps"):
            tier, kind = self._TIER_USER
            tiers.insert(0, {"source": "device_gps", "tier": tier, "kind": kind})

        sim_tagged = DataSource.SIMULATED.value
        liveish = [s for s in sources if s and s != sim_tagged]
        live_fraction = (len(liveish) / len(sources)) if sources else 0.0

        verdict_conf = (
            risk.confidence if risk is not None and risk.confidence is not None
            else (ocean.confidence if ocean is not None else 0.5)
        )
        agreement = 1.0 if not conflicts else 0.5
        score = round(min(1.0, 0.55 * live_fraction + 0.30 * float(verdict_conf)
                          + 0.15 * agreement), 2)
        return score, tiers

    def _assemble_response(self, state: ORCAGraphState, answer: str) -> OrchestratorResponse:
        risk: RiskAssessment | None = state.get("risk")
        geofence = state.get("geofence")
        reasoning: list[str] = []
        evidence = []
        status = SafetyStatus.CAUTION
        if risk is not None:
            status = risk.status
            evidence = list(risk.evidence_sources)
            for flag in risk.flags:
                reasoning.append(f"{flag.label}: {flag.detail} ({flag.threshold_crossed})")
            reasoning.extend(risk.reasoning)

        # Region-scan avoid list (P1 #12): restricted zones + active hazard
        # flags + exceedance windows, deduplicated.
        avoid_zones: list[dict] = []
        if geofence is not None and not geofence.clear:
            for h in geofence.hits:
                avoid_zones.append({
                    "zone": h.zone_name,
                    "reason": ("inside protected/restricted boundary"
                               if h.inside_zone else
                               f"within {h.distance_to_boundary_km} km of boundary"),
                    "distance_km": h.distance_to_boundary_km,
                })
        if risk is not None:
            seen = {a["zone"] for a in avoid_zones}
            for flag in risk.flags:
                zone_key = f"{flag.label}: {flag.detail[:60]}"
                if zone_key not in seen:
                    avoid_zones.append({
                        "zone": zone_key,
                        "reason": flag.threshold_crossed,
                        "distance_km": 0.0,
                    })
                    seen.add(zone_key)

        conflicts = list(state.get("synthesis", {}).get("conflicts", []))
        confidence_score, evidence_tiers = self._score_and_tiers(state, conflicts)

        return OrchestratorResponse(
            answer=answer,
            status=status,
            reasoning=reasoning,
            evidence_sources=evidence,
            trace=list(state["traces"]),
            ocean_state=state.get("ocean_state"),
            risk=risk,
            conflicts=conflicts,
            discussion=self._flatten_discussion(state.get("discussion")),
            language=state.get("language", "en"),
            pfz=state.get("pfz"),
            geofence=geofence,
            route=state.get("route"),
            trend=state.get("trend"),
            avoid_zones=avoid_zones,
            confidence_score=confidence_score,
            evidence_tiers=evidence_tiers,
        )

    @staticmethod
    def _flatten_discussion(transcript: dict | None) -> list:
        """{"turns": [...], "consensus": s} -> [turn..., {"consensus": s}]."""
        if not transcript:
            return []
        flat: list = [
            {
                "speaker": t.get("speaker", ""),
                "addressing": t.get("addressing"),
                "stance": t.get("stance", "clarify"),
                "point": t.get("point", ""),
            }
            for t in (transcript.get("turns") or [])
        ]
        if transcript.get("consensus"):
            flat.append({"consensus": transcript["consensus"]})
        return flat

    # ------------------------------------------------------------------
    # No-langgraph fallback: same flow via direct sequential calls
    # ------------------------------------------------------------------
    def _handle_query_sequential(self, initial: dict) -> OrchestratorResponse:
        state: ORCAGraphState = dict(initial)
        trace: list[AgentTrace] = []

        lang_result, t = self.language_agent.run(state["raw_query"])
        state.update(lang_result)
        trace.append(t)

        plan, plan_mode, location, context, t = self._step_plan(
            state["normalized_query"], state["raw_query"], state
        )
        state.update({"plan": plan, "location": location, "context": context})
        trace.append(t)

        specialists = self._selected_specialists(
            plan,
            live_position=bool(initial.get("device_gps") or initial.get("destination")),
        )
        if not specialists:
            unsupported = self._node_unsupported(state)["response"]
            unsupported.trace = trace + unsupported.trace
            return unsupported

        if "trend" in specialists:
            trend, t = self.trend_agent.run(
                location, int(state["plan"].get("months_back") or 6)
            )
            state["trend"] = trend
            trace.append(t)

        if "ocean_state" in specialists:
            reading, t = self.ocean_state_agent.run(
                location, state["plan"]["time_window"],
                target_hour=state["plan"].get("target_hour"),
                thresholds=get_thresholds(state.get("vessel_class") or "small_fishing_boat"),
            )
            state["ocean_state"] = reading
            trace.append(t)
            risk, t = self.hazard_agent.run(
                reading, state.get("vessel_class") or "small_fishing_boat"
            )
            state["risk"] = risk
            trace.append(t)
        if "pfz" in specialists:
            pfz, t = self.pfz_agent.run(location, state.get("ocean_state"), plan["time_window"])
            state["pfz"] = pfz
            trace.append(t)
        if "geospatial" in specialists:
            hazard_labels = (
                [f.label for f in state["risk"].flags] if state.get("risk") else []
            )
            (gf, rt), t = self.geospatial_agent.run(
                location, context.device_gps, context.destination,
                hazard_zone_names=hazard_labels,
            )
            state["geofence"] = gf
            if rt is not None:
                state["route"] = rt
            trace.append(t)

        transcript, t = self.discussion_agent.run(
            context, ocean_state=state.get("ocean_state"),
            risk=state.get("risk"), pfz=state.get("pfz"),
            geofence=state.get("geofence"), route=state.get("route"),
            trend=state.get("trend"),
        )
        state["discussion"] = transcript
        trace.append(t)

        synthesis, t = self.synthesis_agent.run(
            context, state.get("ocean_state"), state.get("risk"),
            pfz=state.get("pfz"), geofence=state.get("geofence"),
            route=state.get("route"), trend=state.get("trend"),
            discussion=transcript,
        )
        state["synthesis"] = synthesis
        trace.append(t)

        answer, t = self.response_agent.run(
            context, synthesis,
            ocean_state=state.get("ocean_state"), risk=state.get("risk"),
            pfz=state.get("pfz"), geofence=state.get("geofence"),
            route=state.get("route"), trend=state.get("trend"),
            discussion=transcript,
        )
        state["traces"] = trace[:-1]  # response node appends its own
        response = self._assemble_response(state, answer)
        response.trace = trace
        return response

    # ------------------------------------------------------------------
    # Direct mode: one named specialist answers, no discussion round.
    # Same language -> planning -> synthesis -> response spine; only the
    # requested specialist runs (plus silent dependencies).
    # ------------------------------------------------------------------
    def _handle_single_agent(
        self, initial: dict, target_key: str
    ) -> OrchestratorResponse:
        state: ORCAGraphState = dict(initial)
        trace: list[AgentTrace] = []
        spec = SPECIALIST_REGISTRY[target_key]

        lang_result, t = self.language_agent.run(state["raw_query"])
        state.update(lang_result)
        trace.append(t)

        plan, plan_mode, location, context, t = self._step_plan(
            state["normalized_query"], state["raw_query"], state
        )
        state.update({"plan": plan, "location": location, "context": context})
        trace.append(t)

        def _run_ocean():
            reading, t = self.ocean_state_agent.run(
                location, plan["time_window"],
                target_hour=plan.get("target_hour"),
                thresholds=get_thresholds(context.vessel_class),
            )
            state["ocean_state"] = reading
            return [t]

        def _run_hazard():
            dep_traces = []
            if not state.get("ocean_state"):
                dep_traces.extend(_run_ocean())
            risk, t = self.hazard_agent.run(state["ocean_state"], context.vessel_class)
            state["risk"] = risk
            return [*dep_traces, t]

        def _run_pfz():
            pfz, t = self.pfz_agent.run(
                location, state.get("ocean_state"), plan["time_window"]
            )
            state["pfz"] = pfz
            return [t]

        def _run_geospatial():
            hazard_labels = (
                [f.label for f in state["risk"].flags] if state.get("risk") else []
            )
            (gf, rt), t = self.geospatial_agent.run(
                location, context.device_gps, context.destination,
                hazard_zone_names=hazard_labels,
            )
            state["geofence"] = gf
            if rt is not None:
                state["route"] = rt
            return [t]

        def _run_trend():
            trend, t = self.trend_agent.run(
                location, int(plan.get("months_back") or 6)
            )
            state["trend"] = trend
            return [t]

        runners = {
            "ocean_state": _run_ocean,
            "hazard": _run_hazard,
            "pfz": _run_pfz,
            "geospatial": _run_geospatial,
            "trend": _run_trend,
        }
        for key in dict.fromkeys([*spec["requires"], target_key]):
            try:
                trace.extend(runners[key]())
            except Exception as exc:
                import logging

                logging.getLogger("orca.orchestrator").warning(
                    "direct-mode agent '%s' failed (%s: %s)",
                    key, type(exc).__name__, exc,
                )

        synthesis, t = self.synthesis_agent.run(
            context, state.get("ocean_state"), state.get("risk"),
            pfz=state.get("pfz"), geofence=state.get("geofence"),
            route=state.get("route"), trend=state.get("trend"),
        )
        state["synthesis"] = synthesis
        trace.append(t)

        answer, t = self.response_agent.run(
            context, synthesis,
            ocean_state=state.get("ocean_state"), risk=state.get("risk"),
            pfz=state.get("pfz"), geofence=state.get("geofence"),
            route=state.get("route"), trend=state.get("trend"),
        )
        state["traces"] = trace[:-1]
        response = self._assemble_response(state, answer)
        response.trace = trace
        response.mode = "agent"
        response.answered_by = f"{spec['name']} (direct -- no discussion round)"
        return response

    # ------------------------------------------------------------------
    # Planning -- LLM first, deterministic rules as fallback
    # ------------------------------------------------------------------
    def _plan(self, normalized_query: str, prior=None) -> tuple[dict, str]:
        start = time.perf_counter()

        if llm_client.is_available():
            try:
                memory_line = ""
                if prior is not None and prior.location_name:
                    memory_line = (
                        f"\nCONVERSATION MEMORY: the previous turn was about "
                        f"'{prior.location_name}' at '{prior.time_window}'. If "
                        "the user says 'same place'/'there', copy that location "
                        "name verbatim into location_name."
                    )
                args = llm_client.complete_structured(
                    system_prompt=(
                        "You are the Planning Agent of ORCA, a marine-intelligence "
                        "system for Indian coastal waters. Parse the user's query into "
                        "a structured plan: what they want (intent), the coastal place "
                        "they mention (any Indian coastal town, village, port or region "
                        "-- copy the name as-is; 'unknown' only if none), the time "
                        "window, the exact local hour if one is named (target_hour), "
                        "which specialist agents are genuinely needed, and why. "
                        "Analytical 'why has X changed over time' questions are "
                        "trend_analysis; ranked good/avoid zone requests are zone_scan. "
                        "Be conservative with intent 'unknown' only when the query has "
                        "nothing to do with the sea, fishing, weather, safety, or coasts."
                    ),
                    user_prompt=f'USER QUERY: "{normalized_query}"{memory_line}',
                    tool_name="plan_query",
                    tool_description=(
                        "Structure the user's marine query into intent, location, time "
                        "window, needed specialist agents, and rationale."
                    ),
                    schema=PLANNING_TOOL_SCHEMA,
                )
                plan = {
                    "intent": args.get("intent", Intent.UNKNOWN),
                    "location_name": args.get("location_name", "unknown"),
                    "time_window": args.get("time_window", "today"),
                    "target_hour": args.get("target_hour"),
                    "months_back": args.get("months_back"),
                    "agents_needed": args.get("agents_needed", []),
                    "why": args.get("why", ""),
                    "duration_ms": (time.perf_counter() - start) * 1000,
                }
                return plan, "llm"
            except llm_client.LLMUnavailableError:
                pass  # fall through to rule-based planning

        # Deterministic fallback (original rule-based logic, extended)
        plan = {
            "intent": self._route_intent(normalized_query),
            "location_name": self._extract_place_name(normalized_query),
            "time_window": self._extract_time_window(normalized_query),
            "target_hour": self._extract_target_hour(normalized_query),
            "months_back": 6 if "trend" in normalized_query.lower() or
                            "declined" in normalized_query.lower() else None,
            "agents_needed": [],
            "why": "[llm_unavailable] Rule-based keyword parsing used.",
            "duration_ms": (time.perf_counter() - start) * 1000,
        }
        return plan, "rules"

    def _extract_target_hour(self, query: str) -> int | None:
        """Rule-based explicit-hour extraction ('at 10 am' -> 10)."""
        import re

        m = re.search(
            r"\bat\s+(\d{1,2})\s*(:\d{2})?\s*(am|pm)?", query.lower()
        )
        if not m:
            return None
        hour = int(m.group(1))
        suffix = m.group(3)
        if suffix == "pm" and hour < 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        return hour if 0 <= hour <= 23 else None

    def _extract_place_name(self, query: str) -> str:
        """Rule-based place-name extraction for the no-LLM path."""
        q = query.lower()
        hit = next((k for k in KNOWN_LOCATIONS if k in q), None)
        if hit:
            return hit
        import re

        m = re.search(
            r"(?:near|around|close to|off)\s+([a-z][a-z ]{2,40}?)(?:\s+(?:tomorrow|today|coast\b)|[?.!]|$)",
            q,
        )
        if m:
            return " ".join(m.group(1).split()[:4])
        return "unknown"

    # ------------------------------------------------------------------
    # Rule-based fallbacks (kept intentionally for no-LLM mode)
    # ------------------------------------------------------------------
    def _route_intent(self, query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ["why has", "why is", "trend", "declined", "decline",
                                  "changed over", "over the last", "productivity"]):
            return Intent.TREND_ANALYSIS
        if any(kw in q for kw in ["which zones", "which regions", "zones to avoid",
                                  "where should i fish", "good zones"]):
            return Intent.ZONE_SCAN
        if any(kw in q for kw in ["fishing zone", "fish zone", "pfz", "where to fish"]):
            return Intent.PFZ_LOOKUP
        if any(kw in q for kw in ["route", "navigate", "safest path", "how do i get"]):
            return Intent.ROUTE_PLAN
        if any(kw in q for kw in ["boundary", "border", "restricted", "geofence", "imbl"]):
            return Intent.GEOFENCE_CHECK
        if any(kw in q for kw in ["alert", "cyclone warning", "lightning"]):
            return Intent.HAZARD_ALERTS
        if any(kw in q for kw in ["safe", "safety", "go fishing", "venture", "risky", "danger"]):
            return Intent.SAFETY_CHECK
        return Intent.UNKNOWN

    def _extract_time_window(self, query: str) -> str:
        q = query.lower()
        if "tomorrow" in q:
            return "tomorrow_morning" if "morning" in q else "tomorrow"
        return "today"
