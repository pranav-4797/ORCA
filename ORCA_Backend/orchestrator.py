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
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, List, Optional, TypedDict

import llm_client
import sessions as session_store
import fleet_convergence as fleet_engine
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

# Auto Router (fast deterministic intent -> fallback LLM)
try:
    import auto_router
    _AUTO_ROUTER_AVAILABLE = True
except Exception:
    _AUTO_ROUTER_AVAILABLE = False
    auto_router = None  # type: ignore

# Query depth policy: auto | fast | standard | deep (env-overridable)
QUERY_DEPTH = os.getenv("ORCA_QUERY_DEPTH", "auto").strip().lower() or "auto"
# TTLs (env-overridable) — short for live safety, longer for geocoding
OCEAN_TTL_S = int(os.getenv("ORCA_OCEAN_TTL_S", "120").strip() or 120)
RESPONSE_CACHE_TTL_S = int(os.getenv("ORCA_RESPONSE_CACHE_TTL_S", "60").strip() or 60)
GEOCODE_TTL_S = int(os.getenv("ORCA_GEOCODE_TTL_S", "86400").strip() or 86400)

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


class ORCAGraphState(TypedDict, total=False):
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
    # Routing explainability (auto mode)
    routing_mode: str  # fast-rules | llm-planner | rules
    routing_reason: str
    complexity: str  # fast | standard | deep
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
    # Latency telemetry (ms) — populated per node, total at end
    timings: dict
    query_depth: str
    mode: str  # auto | panel | agent
    fleet_convergence: Optional[dict]  # FleetConvergenceResult as dict
    fleet_demo_level: Optional[str]  # low/medium/high/severe for demo


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
        g.add_node("fleet_convergence", self._node_fleet_convergence)
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
        g.add_edge("specialists", "fleet_convergence")
        g.add_edge("fleet_convergence", "discussion")
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
    # Helper: should we run discussion / synthesis LLM for this query?
    # ------------------------------------------------------------------
    def _should_run_discussion(self, state: ORCAGraphState) -> bool:
        mode = (state.get("mode") or "auto").lower()
        # Panel = full deliberation demo — always discuss
        if mode == "panel":
            return True
        # Agent direct = never discuss
        if mode == "agent":
            return False
        # Auto mode: decision based on complexity + query_depth policy
        complexity = (state.get("complexity") or state.get("plan", {}).get("complexity") or "fast")
        # Respect env override: force fast/standard/deep
        depth_policy = (state.get("query_depth") or QUERY_DEPTH).lower()
        if depth_policy == "fast":
            return False
        if depth_policy == "deep":
            return True
        # auto: fast/standard -> no discussion, deep/complex -> discuss
        if complexity in ("fast", "standard"):
            return False
        return True  # deep

    def _should_use_synthesis_llm(self, state: ORCAGraphState) -> bool:
        mode = (state.get("mode") or "auto").lower()
        if mode == "panel":
            return True
        if mode == "agent":
            return False
        # Auto: only use LLM synthesis when conflict or deep complexity
        complexity = (state.get("complexity") or state.get("plan", {}).get("complexity") or "fast")
        depth_policy = (state.get("query_depth") or QUERY_DEPTH).lower()
        if depth_policy == "fast":
            return False
        if depth_policy == "deep":
            return True
        # Check if multiple specialists disagree (risk vs pfz tension)
        # For auto, use deterministic synthesis when 0-1 conflicts and complexity not deep
        if complexity in ("fast", "standard"):
            return False
        return True

    # ------------------------------------------------------------------
    # Public entrypoint — now supports auto | panel | agent
    # ------------------------------------------------------------------
    def handle_query(
        self,
        raw_query: str,
        session_id: str | None = None,
        device_gps: tuple | None = None,
        destination: Location | None = None,
        mode: str = "auto",
        target_agent: str | None = None,
        vessel_class: str | None = None,
        query_depth: str | None = None,
        fleet_demo_level: str | None = None,
    ) -> OrchestratorResponse:
        # Normalize mode (backwards compat: panel default previously)
        mode_norm = (mode or "auto").strip().lower()
        if mode_norm not in ("auto", "panel", "agent"):
            mode_norm = "auto"
        session_id = session_id or str(uuid.uuid4())
        initial: ORCAGraphState = {
            "raw_query": raw_query,
            "session_id": session_id,
            "device_gps": device_gps,
            "destination": destination,
            "vessel_class": vessel_class or "small_fishing_boat",
            "mode": mode_norm,
            "query_depth": (query_depth or QUERY_DEPTH).strip().lower() if query_depth else QUERY_DEPTH,
            "fleet_demo_level": (fleet_demo_level.strip().lower() if fleet_demo_level else None),
            "timings": {},
            "traces": [],
        }
        if mode_norm == "agent" and target_agent in SPECIALIST_REGISTRY:
            return self._handle_single_agent(initial, target_agent)
        if mode_norm == "panel":
            return self._handle_query_panel(initial)
        # auto is default
        return self._handle_query_auto(initial)

    # ------------------------------------------------------------------
    # Auto mode — fast intelligent orchestration, discussion only when needed
    # ------------------------------------------------------------------
    def _handle_query_auto(self, initial: dict) -> OrchestratorResponse:
        # Use graph if available (nodes internally gate discussion/synthesis LLM)
        if self.app is not None:
            t0 = time.perf_counter()
            final_state = self.app.invoke(initial)
            response = final_state["response"]
            total_ms = (time.perf_counter() - t0) * 1000
            response.mode = "auto"
            # Explain which agents auto-selected
            plan = final_state.get("plan", {})
            agents = self._selected_specialists(plan, live_position=bool(initial.get("device_gps") or initial.get("destination")))
            routing_mode = final_state.get("routing_mode", "fast-rules")
            complexity = final_state.get("complexity", "fast")
            response.answered_by = f"AUTO SELECT → {' + '.join(a.replace('Agent','').strip() for a in agents) or 'no specialist'} ({routing_mode}, {complexity})"
            # Attach latency trace
            timings = final_state.get("timings", {})
            timings["total_ms"] = round(total_ms, 1)
            response = self._attach_latency_trace(response, timings, final_state.get("traces", []))
            # Safety clamp: LLM must not override deterministic UNSAFE
            response = self._enforce_safety_clamp(response, final_state)
            # Record fleet activity for future convergence (real, not simulated)
            try:
                self._record_fleet_activity(final_state, response)
            except:
                pass
            # expose timings optionally
            if hasattr(response, "timings"):
                response.timings = timings  # type: ignore
            return response
        # No langgraph fallback — sequential with same gating
        return self._handle_query_auto_sequential(initial)

    def _handle_query_auto_sequential(self, initial: dict) -> OrchestratorResponse:
        t0 = time.perf_counter()
        response = self._handle_query_sequential(initial, auto_mode=True)
        total_ms = (time.perf_counter() - t0) * 1000
        response.mode = "auto"
        # Ensure timings dict exists on response
        if not hasattr(response, "timings") or getattr(response, "timings", None) is None:
            response.timings = {"total_ms": round(total_ms, 1)}  # type: ignore
        else:
            response.timings["total_ms"] = round(total_ms, 1)  # type: ignore
        response = self._attach_latency_trace(response, getattr(response, "timings", {}), response.trace)
        return response

    def _attach_latency_trace(self, response: OrchestratorResponse, timings: dict, existing_traces: list) -> OrchestratorResponse:
        total = timings.get("total_ms", 0)
        breakdown = ", ".join(f"{k}={v:.0f}ms" for k, v in sorted(timings.items()) if k != "total_ms")
        detail = f"ORCA completed in {total:.0f} ms" + (f" ({breakdown})" if breakdown else "")
        # Add Auto Router selection explainability if available
        auto_bits = []
        for t in existing_traces:
            if "Auto Router" in t.action or "Routing mode" in t.result_summary:
                auto_bits.append(t.result_summary[:200])
        if auto_bits:
            detail += " | " + " | ".join(auto_bits[:2])
        trace = AgentTrace(
            agent_name="Orchestrator",
            action="Latency telemetry",
            result_summary=detail,
            data_sources=[],
            duration_ms=float(total),
        )
        response.trace.append(trace)
        return response

    def _enforce_safety_clamp(self, response: OrchestratorResponse, state: dict) -> OrchestratorResponse:
        """LLM must NEVER override deterministic UNSAFE. If hazard says UNSAFE, response stays UNSAFE."""
        risk = state.get("risk")
        if risk is not None and hasattr(risk, "status") and risk.status.value == "UNSAFE":
            if response.status.value != "UNSAFE":
                response.status = risk.status
                response.reasoning = getattr(risk, "reasoning", []) or response.reasoning
        return response

    def _record_fleet_activity(self, state: dict, response: OrchestratorResponse):
        """Record fleet activity for future convergence — uses final_zone if available, else primary PFZ."""
        try:
            fleet = state.get("fleet_convergence") or getattr(response, "fleet_convergence", None)
            if not fleet or fleet.get("status") == "UNAVAILABLE":
                return
            # Don't record simulated demo activity as real fleet — keep isolated
            if fleet.get("status", "").startswith("SIMULATED"):
                return
            final = fleet.get("final_zone")
            if final:
                fleet_engine.record_recommendation(
                    final_zone=type("Obj", (), {
                        "center_lat": final["center_lat"],
                        "center_lon": final["center_lon"],
                    })(),
                    session_id=state.get("session_id", ""),
                    reference_lat=state.get("location", {}).lat if hasattr(state.get("location", {}), "lat") else None,
                    reference_lon=state.get("location", {}).lon if hasattr(state.get("location", {}), "lon") else None,
                    is_simulated=False,
                )
            else:
                pfz = state.get("pfz")
                if pfz:
                    fleet_engine.record_recommendation(
                        final_zone=type("Obj", (), {"center_lat": pfz.center_lat, "center_lon": pfz.center_lon})(),
                        session_id=state.get("session_id", ""),
                        is_simulated=False,
                    )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Panel mode: full graph incl. the round-table discussion
    # ------------------------------------------------------------------
    def _handle_query_panel(self, initial: dict) -> OrchestratorResponse:
        if self.app is not None:
            t0 = time.perf_counter()
            final_state = self.app.invoke(initial)
            response = final_state["response"]
            total_ms = (time.perf_counter() - t0) * 1000
            response.mode = "panel"
            response.answered_by = (
                "ORCA panel (specialists discussed before answering)"
            )
            timings = final_state.get("timings", {})
            timings["total_ms"] = round(total_ms, 1)
            response = self._attach_latency_trace(response, timings, final_state.get("traces", []))
            response = self._enforce_safety_clamp(response, final_state)
            try:
                self._record_fleet_activity(final_state, response)
            except:
                pass
            if hasattr(response, "timings"):
                response.timings = timings  # type: ignore
            return response
        response = self._handle_query_sequential(initial)
        response.mode = "panel"
        response.answered_by = "ORCA panel (specialists discussed before answering)"
        try:
            # For sequential fallback, record from response if available
            self._record_fleet_activity({"pfz": getattr(response, "pfz", None), "fleet_convergence": getattr(response, "fleet_convergence", None), "session_id": initial.get("session_id")}, response)
        except:
            pass
        return response

    # ------------------------------------------------------------------
    # Nodes -- thin adapters over the shared step helpers below, so the
    # graph path and the no-langgraph fallback share one code path.
    # ------------------------------------------------------------------
    def _node_language(self, state: ORCAGraphState) -> dict:
        t0 = time.perf_counter()
        result, trace = self.language_agent.run(state["raw_query"])
        timings = dict(state.get("timings") or {})
        timings["language_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "normalized_query": result["normalized_query"],
            "language": result["language"],
            "timings": timings,
            "traces": [trace],
        }

    def _node_planning(self, state: ORCAGraphState) -> dict:
        t0 = time.perf_counter()
        plan, plan_mode, location, context, trace = self._step_plan(
            state["normalized_query"], state["raw_query"], state
        )
        timings = dict(state.get("timings") or {})
        timings["planning_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        # Also store routing specifics in timings
        timings["routing_ms"] = round(float(plan.get("duration_ms", 0)), 1)
        routing_mode = plan.get("routing_mode", plan_mode)
        complexity = plan.get("complexity", "fast")
        return {
            "plan": plan,
            "plan_mode": plan_mode,
            "routing_mode": routing_mode,
            "routing_reason": plan.get("why", ""),
            "complexity": complexity,
            "location": location,
            "context": context,
            "timings": timings,
            "traces": [trace],
        }

    def _node_dispatch(self, state: ORCAGraphState) -> dict:
        """Run every selected specialist agent with maximal parallelism.

        Optimized pipeline (latency-tuned):
        - Phase 1 (concurrent): Ocean-State, PFZ, Geofence, Trend all start together.
        - Hazard depends on Ocean-State: launched as soon as ocean completes,
          overlapping with remaining PFZ/Geofence work.
        - Route planning (if destination) runs after both hazard and geofence are ready,
          so it can avoid hazard-flagged zones.
        All timings recorded for telemetry; one specialist failing never kills the query.
        """
        t_dispatch0 = time.perf_counter()
        plan = state["plan"]
        ctx = state["context"]
        location = state["location"]
        selected = self._selected_specialists(
            plan,
            live_position=bool(state.get("device_gps") or state.get("destination")),
        )
        # Determine which agents are truly needed (including implicit hazard)
        needs_ocean = "ocean_state" in selected
        needs_pfz = "pfz" in selected
        needs_geo = "geospatial" in selected
        needs_trend = "trend" in selected
        # Hazard is needed for most intents except pure pfz/geofence/trend
        needs_hazard = needs_ocean and plan.get("intent") in ("safety_check", "hazard_alerts", "zone_scan", "route_plan")
        # Also if hazard explicitly requested via agents_needed
        if "HazardAgent" in set(plan.get("agents_needed") or []):
            needs_hazard = True
            needs_ocean = True

        hour = plan.get("target_hour")
        timings = dict(state.get("timings") or {})
        results: dict = {}
        traces: list[AgentTrace] = []

        import logging
        logger = logging.getLogger("orca.orchestrator")

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures: dict[str, object] = {}
            # Launch independent specialists immediately
            t_ocean0 = None
            if needs_ocean:
                thr = get_thresholds(ctx.vessel_class)
                def _run_ocean():
                    return self.ocean_state_agent.run(
                        location, plan["time_window"], target_hour=hour, thresholds=thr,
                    )
                futures["ocean"] = pool.submit(_run_ocean)
                t_ocean0 = time.perf_counter()
            if needs_pfz:
                futures["pfz"] = pool.submit(
                    self.pfz_agent.run, location, None, plan["time_window"]
                )
            if needs_geo:
                # Geofence check is pure geometry (<10ms) — run independently now;
                # route will be handled later after hazard is known.
                def _run_geofence():
                    # Use the agent's internal geofence logic directly to avoid LLM overhead
                    ref_lat, ref_lon = (ctx.device_gps or (location.lat, location.lon))
                    # Direct call to avoid double geofence+route; route handled separately
                    gf = self.geospatial_agent._check_geofence(ref_lat, ref_lon, location)
                    # Create a minimal trace for geofence-only part
                    tr = AgentTrace(
                        agent_name=self.geospatial_agent.name,
                        action="Checked boundaries (geofence)",
                        result_summary=f"Geofence checked: {'clear' if gf.clear else f'{len(gf.hits)} hit(s)'}",
                        data_sources=[],
                        duration_ms=0.0,
                    )
                    return (gf, None), tr
                futures["geofence"] = pool.submit(_run_geofence)
            if needs_trend:
                months = int(plan.get("months_back") or 6)
                futures["trend"] = pool.submit(self.trend_agent.run, location, months)

            # Wait for ocean first, then launch hazard (if needed) while others still running
            # Timeout env-configurable: fast fail to simulated fallback rather than hanging 30s
            ocean_reading = None
            ocean_trace = None
            _OCEAN_FUTURE_TIMEOUT = float(os.getenv("ORCA_OCEAN_FUTURE_TIMEOUT_S", "12").strip() or 12)
            if "ocean" in futures:
                try:
                    ocean_reading, ocean_trace = futures["ocean"].result(timeout=_OCEAN_FUTURE_TIMEOUT)  # type: ignore
                    if t_ocean0 is not None:
                        timings["ocean_ms"] = round((time.perf_counter() - t_ocean0) * 1000, 1)
                    traces.append(ocean_trace)
                    results["ocean_state"] = ocean_reading
                except Exception as exc:
                    logger.warning("ocean_state failed (%s: %s); continuing without it", type(exc).__name__, exc)
                    try:
                        futures["ocean"].result(timeout=0)  # ensure exception consumed
                    except:  # noqa
                        pass
                finally:
                    futures.pop("ocean", None)

            # Launch hazard as soon as ocean is ready (overlaps with pfz/geofence)
            haz_future = None
            t_haz0 = None
            if needs_hazard and ocean_reading is not None:
                t_haz0 = time.perf_counter()
                haz_future = pool.submit(self.hazard_agent.run, ocean_reading, ctx.vessel_class)

            # Collect remaining independents while hazard runs
            pfz_res = None
            geo_res = None
            trend_res = None
            for key in ("pfz", "geofence", "trend"):
                if key in futures:
                    # Shorter timeouts: geofence is <10ms, pfz ~1s, trend may be longer (network heavy)
                    _to = 15.0 if key in ("pfz","geofence") else 25.0
                    try:
                        val = futures[key].result(timeout=_to)  # type: ignore
                        if key == "pfz":
                            pfz_res = val
                            traces.append(val[1])
                            results["pfz"] = val[0]
                            timings["pfz_ms"] = round(val[1].duration_ms, 1)
                        elif key == "geofence":
                            (gf, _rt), tr = val
                            # Fix trace duration if needed
                            traces.append(tr)
                            results["geofence"] = gf
                            # Keep RoutePlan placeholder None for now; route added later if needed
                            timings["geospatial_ms"] = round(tr.duration_ms, 1) if tr.duration_ms else 0.0
                            geo_res = gf
                        elif key == "trend":
                            trend_res = val
                            traces.append(val[1])
                            results["trend"] = val[0]
                            timings["trend_ms"] = round(val[1].duration_ms, 1)
                    except Exception as exc:
                        logger.warning("%s failed (%s: %s); continuing without it", key, type(exc).__name__, exc)
                    finally:
                        futures.pop(key, None)

            # Collect hazard (IMD CAP 60s cache, should be <2s after cache)
            if haz_future is not None:
                try:
                    risk, h_trace = haz_future.result(timeout=12)  # type: ignore
                    if t_haz0 is not None:
                        timings["hazard_ms"] = round((time.perf_counter() - t_haz0) * 1000, 1)
                    else:
                        timings["hazard_ms"] = round(h_trace.duration_ms, 1)
                    traces.append(h_trace)
                    results["risk"] = risk
                    # If geofence was not launched independently (e.g., destination-only case), run it now
                except Exception as exc:
                    logger.warning("hazard failed (%s: %s); continuing without it", type(exc).__name__, exc)

            # Route planning — needs hazard + geofence + destination
            if needs_geo and ctx.destination is not None:
                try:
                    t_route0 = time.perf_counter()
                    risk = results.get("risk")
                    hazard_labels = [f.label for f in risk.flags] if risk else []
                    exceedance = getattr(risk, "exceedance_windows", []) if risk else []
                    for w in exceedance or []:
                        hazard_labels.append(f"{w.metric} > {w.threshold}{w.unit} {w.start_local}..{w.end_local}")
                    geofence = results.get("geofence")
                    # If geofence wasn't run (edge), run it now
                    if geofence is None:
                        ref_lat, ref_lon = (ctx.device_gps or (location.lat, location.lon))
                        geofence = self.geospatial_agent._check_geofence(ref_lat, ref_lon, location)
                        results["geofence"] = geofence
                    # Now plan route avoiding both restricted and hazard zones
                    route = self.geospatial_agent._plan_route(
                        (ctx.device_gps[0] if ctx.device_gps else location.lat),
                        (ctx.device_gps[1] if ctx.device_gps else location.lon),
                        ctx.destination.lat, ctx.destination.lon,
                        restricted=[h.zone_name for h in (geofence.hits if geofence else [])],
                        hazard_names=hazard_labels,
                    )
                    results["route"] = route
                    # Create trace for route
                    r_trace = AgentTrace(
                        agent_name=self.geospatial_agent.name,
                        action="Planned safe route (geofence+hazard aware)",
                        result_summary=f"Route {route.estimated_distance_km:.0f} km [{route.algorithm}] avoiding {len(route.avoided_zones)} zone(s)",
                        data_sources=[],
                        duration_ms=(time.perf_counter() - t_route0) * 1000,
                    )
                    traces.append(r_trace)
                    timings["route_ms"] = round(r_trace.duration_ms, 1)
                    # Also enrich geofence trace with route note
                    if geofence is not None:
                        geofence.reasoning_note = f"Route planned to {ctx.destination.name} avoiding {len(route.avoided_zones)} zone(s)."
                except Exception as exc:
                    logger.warning("route planning failed (%s: %s)", type(exc).__name__, exc)
            elif needs_geo and not needs_trend and not needs_ocean and not needs_pfz:
                # Pure geofence-only query without ocean/hazard: ensure we still have geofence timing
                pass

        timings["dispatch_ms"] = round((time.perf_counter() - t_dispatch0) * 1000, 1)
        # Merge results into update dict
        update: dict = {"traces": traces, "timings": timings}
        if "ocean_state" in results:
            update["ocean_state"] = results["ocean_state"]
        if "risk" in results:
            update["risk"] = results["risk"]
        if "pfz" in results:
            update["pfz"] = results["pfz"]
        if "geofence" in results:
            update["geofence"] = results["geofence"]
        if "route" in results:
            update["route"] = results["route"]
        if "trend" in results:
            update["trend"] = results["trend"]
        return update

    def _node_fleet_convergence(self, state: ORCAGraphState) -> dict:
        """Fleet Convergence Forecast — crowding-adjusted suitability.

        Uses PFZ candidates + fleet activity to compute penalty and select
        best alternative. Safety/legal always overrides fleet optimization.
        Demo mode: if fleet_demo_level is set, simulated fleet is included.
        """
        t0 = time.perf_counter()
        pfz = state.get("pfz")
        # If no PFZ, nothing to converge
        if pfz is None:
            trace = AgentTrace(
                agent_name="FleetConvergence",
                action="Skipped fleet convergence — no PFZ candidates",
                result_summary="No fishing zones to analyze; fleet convergence unavailable",
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["fleet_ms"] = round(trace.duration_ms, 1)
            return {"fleet_convergence": {"status": "UNAVAILABLE", "reason": "no PFZ"}, "traces": [trace], "timings": timings}

        # Handle demo simulation injected via state
        demo_level = state.get("fleet_demo_level")
        include_simulated = bool(demo_level) or False
        # Also check if any simulated data exists globally — include for demo visualization but label SIMULATED
        # For real queries, we want to count real only; for demo, include simulated
        # If demo_level set, ensure simulated data exists (auto-generate if empty)
        if demo_level and pfz:
            # If no simulated data, auto-populate for demo
            try:
                recent_sim = fleet_engine.fleet_store.get_recent(include_simulated=True)
                sim_count = sum(1 for a in recent_sim if a.is_simulated)
                if sim_count == 0:
                    # Generate around primary zone
                    fleet_engine.simulate_fleet_activity(pfz.center_lat, pfz.center_lon, level=demo_level)
                    include_simulated = True
            except:
                pass

        # If demo not requested but simulated data exists, we still want to show it but mark status SIMULATED
        # Check if we should include simulated: if there is simulated data and no real data, include for visualization
        try:
            all_recent = fleet_engine.fleet_store.get_recent(include_simulated=True)
            has_sim = any(a.is_simulated for a in all_recent)
            has_real = any(not a.is_simulated for a in all_recent)
            if has_sim and not has_real:
                include_simulated = True
            elif has_sim and has_real and demo_level:
                include_simulated = True
        except:
            pass

        try:
            result = fleet_engine.analyze_fleet_convergence(
                pfz=pfz,
                ocean_state=state.get("ocean_state"),
                geofence=state.get("geofence"),
                risk=state.get("risk"),
                include_simulated=include_simulated,
            )
            # Convert to serializable dict
            fleet_dict = {
                "status": result.status,
                "window_hours": result.window_hours,
                "timestamp": result.timestamp,
                "recommendation_changed": result.recommendation_changed,
                "change_reason": result.change_reason,
                "candidates": [
                    {
                        "zone_id": c.zone_id,
                        "center_lat": c.center_lat,
                        "center_lon": c.center_lon,
                        "distance_km": c.distance_km,
                        "bearing_deg": c.bearing_deg,
                        "sst_celsius": c.sst_celsius,
                        "base_suitability": c.base_suitability,
                        "fleet_count": c.fleet_count,
                        "crowding_ratio": c.crowding_ratio,
                        "crowding_penalty": c.crowding_penalty,
                        "adjusted_suitability": c.adjusted_suitability,
                        "is_safe": c.is_safe,
                        "is_legal": c.is_legal,
                        "is_recommended": c.is_recommended,
                        "source": c.source,
                    } for c in result.candidates
                ],
                "raw_best_zone": {
                    "zone_id": result.raw_best_zone.zone_id,
                    "center_lat": result.raw_best_zone.center_lat,
                    "center_lon": result.raw_best_zone.center_lon,
                    "base_suitability": result.raw_best_zone.base_suitability,
                    "fleet_count": result.raw_best_zone.fleet_count,
                    "adjusted_suitability": result.raw_best_zone.adjusted_suitability,
                } if result.raw_best_zone else None,
                "final_zone": {
                    "zone_id": result.final_zone.zone_id,
                    "center_lat": result.final_zone.center_lat,
                    "center_lon": result.final_zone.center_lon,
                    "base_suitability": result.final_zone.base_suitability,
                    "fleet_count": result.final_zone.fleet_count,
                    "adjusted_suitability": result.final_zone.adjusted_suitability,
                } if result.final_zone else None,
            }
            # Add crowding labels for UI
            for cand in fleet_dict["candidates"]:
                ratio = cand["crowding_ratio"]
                if ratio >= 1.5:
                    cand["crowding_label"] = "🔴 High crowding"
                elif ratio >= 0.8:
                    cand["crowding_label"] = "🟠 Medium crowding"
                elif ratio >= 0.3:
                    cand["crowding_label"] = "🟡 Low crowding"
                else:
                    cand["crowding_label"] = "🟢 Minimal crowding"

            summary = f"Fleet convergence {result.status}: {len(result.candidates)} zones, raw {result.raw_best_zone.zone_id if result.raw_best_zone else 'none'} → final {result.final_zone.zone_id if result.final_zone else 'none'} changed={result.recommendation_changed}"
            if result.recommendation_changed and result.final_zone and result.raw_best_zone:
                summary += f" ({result.raw_best_zone.base_suitability}→{result.raw_best_zone.adjusted_suitability} vs {result.final_zone.base_suitability}→{result.final_zone.adjusted_suitability})"

            trace = AgentTrace(
                agent_name="FleetConvergence",
                action=f"Analyzed fleet crowding for {len(result.candidates)} candidate zones [{result.status}]",
                result_summary=summary,
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["fleet_ms"] = round(trace.duration_ms, 1)
            return {"fleet_convergence": fleet_dict, "traces": [trace], "timings": timings}
        except Exception as exc:
            import logging
            logging.getLogger("orca.orchestrator").warning("fleet convergence failed: %s", exc)
            trace = AgentTrace(
                agent_name="FleetConvergence",
                action="Fleet convergence unavailable — fallback to raw ranking",
                result_summary=f"Fleet data unavailable: {exc}",
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["fleet_ms"] = round(trace.duration_ms, 1)
            return {"fleet_convergence": {"status": "UNAVAILABLE", "reason": str(exc), "candidates": []}, "traces": [trace], "timings": timings}

    def _node_discussion(self, state: ORCAGraphState) -> dict:
        """Round-table: specialists read each other's findings and debate. Skipped for FAST mode."""
        t0 = time.perf_counter()
        if not self._should_run_discussion(state):
            trace = AgentTrace(
                agent_name="DiscussionAgent",
                action="Skipped round-table (fast path — no conflict/complexity)",
                result_summary="Discussion disabled for fast/standard query; deterministic synthesis will be used.",
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["discussion_ms"] = round(trace.duration_ms, 1)
            return {"discussion": {"turns": [], "consensus": ""}, "traces": [trace], "timings": timings}
        transcript, trace = self.discussion_agent.run(
            state["context"],
            ocean_state=state.get("ocean_state"),
            risk=state.get("risk"),
            pfz=state.get("pfz"),
            geofence=state.get("geofence"),
            route=state.get("route"),
            trend=state.get("trend"),
        )
        timings = dict(state.get("timings") or {})
        timings["discussion_ms"] = round(trace.duration_ms, 1)
        return {"discussion": transcript, "traces": [trace], "timings": timings}

    def _node_synthesis(self, state: ORCAGraphState) -> dict:
        t0 = time.perf_counter()
        fleet = state.get("fleet_convergence")
        # Gating: use deterministic synthesis when LLM not needed
        if not self._should_use_synthesis_llm(state):
            # Deterministic verdict pass-through — no LLM call
            risk = state.get("risk")
            deterministic = self.synthesis_agent._fallback_verdict(risk)  # type: ignore
            # Inject fleet convergence info into synthesis for response
            if fleet and fleet.get("recommendation_changed"):
                deterministic["fleet_convergence"] = fleet
                deterministic["conflicts"].append(f"Fleet convergence: {fleet['raw_best_zone']['zone_id']} raw {fleet['raw_best_zone']['base_suitability']} fleet {fleet['raw_best_zone']['fleet_count']} → {fleet['final_zone']['zone_id']} raw {fleet['final_zone']['base_suitability']} fleet {fleet['final_zone']['fleet_count']}")
                deterministic["key_points"].append(f"Fleet convergence changed recommendation from {fleet['raw_best_zone']['zone_id']} to {fleet['final_zone']['zone_id']} due to crowding")
            trace = AgentTrace(
                agent_name="SynthesisAgent",
                action="Deterministic synthesis (fast path — no LLM reconciliation needed)",
                result_summary=f"Verdict '{deterministic['verdict']}' (deterministic); single specialist/no conflict." + (f" Fleet {fleet['raw_best_zone']['zone_id']}→{fleet['final_zone']['zone_id']}" if fleet and fleet.get("recommendation_changed") else ""),
                data_sources=list(risk.evidence_sources) if risk else [],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["synthesis_ms"] = round(trace.duration_ms, 1)
            return {"synthesis": deterministic, "traces": [trace], "timings": timings}
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
        # Inject fleet info for LLM synthesis as well
        if fleet and fleet.get("recommendation_changed"):
            synthesis["fleet_convergence"] = fleet
            synthesis["conflicts"].append(f"Fleet convergence: {fleet['raw_best_zone']['zone_id']} → {fleet['final_zone']['zone_id']}")
            synthesis["key_points"].append(f"Fleet convergence: {fleet['change_reason']}")
        timings = dict(state.get("timings") or {})
        timings["synthesis_ms"] = round(synth_trace.duration_ms, 1)
        return {"synthesis": synthesis, "traces": [synth_trace], "timings": timings}

    def _node_response(self, state: ORCAGraphState) -> dict:
        t0 = time.perf_counter()
        # For fast auto queries with single authoritative hazard verdict, use deterministic template (no LLM call)
        mode = (state.get("mode") or "auto").lower()
        complexity = (state.get("complexity") or state.get("plan", {}).get("complexity") or "fast")
        risk = state.get("risk")
        # Fast path: safety_check / hazard_alerts with deterministic verdict -> no LLM
        depth_policy = (state.get("query_depth") or QUERY_DEPTH).lower()
        use_deterministic = (
            mode == "auto" and complexity in ("fast", "standard") and depth_policy != "deep"
            and (risk is not None or state.get("pfz") is not None or state.get("geofence") is not None)
        )
        # But if synthesis required LLM (deep), allow response LLM
        if use_deterministic and not self._should_use_synthesis_llm(state):
            # Deterministic concise answer (no LLM)
            answer = self._deterministic_answer(state)
            resp_trace = AgentTrace(
                agent_name="ResponseAgent",
                action="Composed deterministic answer (fast path — no LLM)",
                result_summary=f"Answer written deterministically ({len(answer)} chars) — verdict {risk.status.value if risk else 'N/A'}",
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        else:
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
            # Enforce safety clamp on answer text? Verdict already clamped in _assemble_response, but also ensure answer reflects UNSAFE
            if risk is not None and risk.status.value == "UNSAFE" and "UNSAFE" not in answer.upper() and "DO NOT" not in answer.upper():
                answer = f"UNSAFE: {risk.headline} " + answer
        timings = dict(state.get("timings") or {})
        timings["response_ms"] = round(resp_trace.duration_ms, 1)
        response = self._assemble_response(state, answer)
        response.trace.append(resp_trace)
        return {"response": response, "traces": [resp_trace], "timings": timings}

    def _deterministic_answer(self, state: ORCAGraphState) -> str:
        """Cheap deterministic response template for simple safety/PFZ/geofence queries — no LLM."""
        risk = state.get("risk")
        ocean = state.get("ocean_state")
        pfz = state.get("pfz")
        geofence = state.get("geofence")
        route = state.get("route")
        fleet = state.get("fleet_convergence")
        context = state.get("context")
        parts: list[str] = []
        # Verdict line is authoritative and already rendered as HUD; answer complements it concisely.
        if risk is not None:
            if risk.status.value == "UNSAFE":
                # Include dominant threshold reason
                flag_txt = "; ".join(f"{f.label}: {f.detail}" for f in risk.flags[:2]) if risk.flags else risk.headline
                wave_txt = ""
                if ocean is not None:
                    wave_txt = f" Wave height {ocean.wave_height_m} m, wind gusts {ocean.wind_gust_kmh} km/h."
                parts.append(f"UNSAFE: {flag_txt}.{wave_txt} Do not venture out. {risk.headline}")
            elif risk.status.value == "CAUTION":
                parts.append(f"CAUTION: {risk.headline} Wave {ocean.wave_height_m if ocean else '?'} m / gusts {ocean.wind_gust_kmh if ocean else '?'} km/h borderline.")
            else:
                parts.append(f"SAFE: {risk.headline} Wave {ocean.wave_height_m if ocean else '?'} m and wind moderate.")
            # Exceedance windows
            for w in getattr(risk, "exceedance_windows", [])[:1]:
                parts.append(f"Conditions worsen {w.start_local}–{w.end_local} (peak {w.peak_value}{w.unit}).")
            # Marine bulletins
            for m in getattr(risk, "marine_bulletins", [])[:1]:
                parts.append(m)
        # PFZ + Fleet Convergence
        if pfz is not None:
            if fleet and fleet.get("recommendation_changed") and fleet.get("final_zone") and fleet.get("raw_best_zone"):
                raw = fleet["raw_best_zone"]
                final = fleet["final_zone"]
                sim_label = " [DEMO — SIMULATED FLEET ACTIVITY]" if fleet.get("status","").startswith("SIMULATED") else ""
                parts.append(f"🎣 Fleet convergence detected{sim_label}: Zone {raw['zone_id']} has highest raw suitability {raw['base_suitability']} but {raw['fleet_count']} ORCA vessels concentrated there (adj {raw['adjusted_suitability']}). Nearby {final['zone_id']} has raw {final['base_suitability']} with only {final['fleet_count']} vessels (adj {final['adjusted_suitability']}).")
                parts.append(f"**Recommendation: {final['zone_id']}** at {final['center_lat']:.3f}, {final['center_lon']:.3f} ({final['fleet_count']} vessels, crowding-adjusted suitability {final['adjusted_suitability']}). This may provide better effective fishing opportunity with less fleet crowding.")
                # Also list candidates briefly
                if fleet.get("candidates"):
                    for cand in fleet["candidates"][:3]:
                        parts.append(f"{cand['zone_id']}: base {cand['base_suitability']} fleet {cand['fleet_count']} adj {cand['adjusted_suitability']} {cand.get('crowding_label','')}")
            else:
                # No fleet change or no fleet data
                if fleet and fleet.get("status") == "UNAVAILABLE":
                    parts.append(f"Nearest PFZ {pfz.distance_from_reference_km:.1f} km away at {pfz.bearing_deg:.0f}° bearing (SST {pfz.sst_at_zone_celsius}°C). Fleet convergence unavailable — showing raw suitability.")
                elif fleet and fleet.get("candidates"):
                    # Show fleet counts even when no change, for transparency
                    for cand in fleet["candidates"][:2]:
                        parts.append(f"{cand['zone_id']}: base {cand['base_suitability']} fleet {cand['fleet_count']} adj {cand['adjusted_suitability']} {cand.get('crowding_label','')}")
                    # Still mention primary
                    parts.append(f"Nearest PFZ {pfz.distance_from_reference_km:.1f} km away at {pfz.bearing_deg:.0f}° bearing (SST {pfz.sst_at_zone_celsius}°C).")
                else:
                    parts.append(f"Nearest PFZ {pfz.distance_from_reference_km:.1f} km away at {pfz.bearing_deg:.0f}° bearing (SST {pfz.sst_at_zone_celsius}°C).")
                if fleet and fleet.get("status","").startswith("SIMULATED"):
                    parts.append("[DEMO — SIMULATED FLEET ACTIVITY]")
        if geofence is not None and not geofence.clear:
            for h in geofence.hits[:1]:
                parts.append(f"Boundary alert: {h.zone_name} {'inside' if h.inside_zone else f'{h.distance_to_boundary_km} km away'}.")
        elif geofence is not None and geofence.clear:
            # Only mention geofence clear for geofence intents, not for every safety check (reduces noise)
            if state.get("plan", {}).get("intent") == "geofence_check":
                parts.append("No restricted boundary within alert buffer.")
        if route is not None:
            parts.append(f"Route {route.estimated_distance_km:.0f} km via {len(route.waypoints)} waypoints avoiding {', '.join(route.avoided_zones) or 'nothing'}.")
        # Ensure language? For now English deterministic; LLM path handles i18n. Fast path keeps English concise.
        answer = " ".join(parts) if parts else (risk.headline if risk else "Assessment complete.")
        # Add provenance hint for simulated fields
        if ocean is not None and ocean.source.value == "simulated":
            answer += " [Note: some fields simulated due to live feed unavailability.]"
        # Safety note if fleet tried to override unsafe
        if fleet and fleet.get("status") != "UNAVAILABLE" and risk and risk.status.value == "UNSAFE":
            answer += " Fleet optimization did not override safety — unsafe zones remain excluded."
        return answer[:1500]

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

        device_gps = state.get("device_gps") or (
            tuple(prior.device_gps) if (prior and prior.device_gps) else None
        )
        destination = state.get("destination") or (
            Location(**prior.destination) if (prior and prior.destination) else None
        )

        # Live Device GPS resolution (P0): if query asks about current location or names no specific town,
        # and device_gps is available, bind to the user's live position directly and reverse-geocode it.
        loc_name = str(plan.get("location_name") or "").strip().lower()
        is_my_location_query = any(k in normalized_query.lower() for k in ("where am i", "my location", "my position", "current position", "here", "around me", "where i am"))
        
        if (loc_name in ("", "unknown", "same", "here", "there", "current", "my location", "where am i") or is_my_location_query) and device_gps:
            try:
                import data_connectors.geocode as geocode
                resolved_name = geocode.reverse_geocode(device_gps[0], device_gps[1])
                location = Location(name=f"Current Position ({resolved_name})", lat=device_gps[0], lon=device_gps[1])
                plan["location_name"] = location.name
            except Exception:
                location = Location(name=f"Current Position ({device_gps[0]:.3f}°N, {device_gps[1]:.3f}°E)", lat=device_gps[0], lon=device_gps[1])
                plan["location_name"] = location.name
        else:
            location = resolve_location(plan["location_name"])

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
        routing_mode = plan.get("routing_mode", plan_mode)
        complexity = plan.get("complexity", "fast")
        # Explainability for AUTO mode: which agents were selected and why (required by spec)
        auto_explain = ""
        if routing_mode == "fast-rules":
            selected_agents = self._selected_specialists(plan, live_position=bool(state.get("device_gps") or state.get("destination")))
            # Human readable agent names
            agent_names = [a.replace("_", " ").title() for a in selected_agents]
            auto_explain = f" | Auto Router selected: {' + '.join(agent_names) or '(none)'} — Reason: {plan.get('why','')} (complexity={complexity}, conf={plan.get('confidence', 0):.2f})"
        trace = AgentTrace(
            agent_name="PlanningAgent",
            action=(
                f"Parsed query [mode={plan_mode} routing={routing_mode} complexity={complexity}] intent='{plan['intent']}', "
                f"location='{location.name}', time_window='{plan['time_window']}'"
            ),
            result_summary=f"{plan['why']} Dispatching to {dispatch_chain}.{auto_explain}",
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
        # Timings and routing explainability (for frontend Auto Select display + telemetry)
        timings = dict(state.get("timings") or {})
        routing = {
            "intent": state.get("plan", {}).get("intent", "unknown"),
            "agents": self._selected_specialists(state.get("plan", {}), live_position=bool(state.get("device_gps") or state.get("destination"))),
            "routing_mode": state.get("routing_mode") or state.get("plan", {}).get("routing_mode", "rules"),
            "complexity": state.get("complexity") or state.get("plan", {}).get("complexity", "fast"),
            "reason": state.get("plan", {}).get("why", ""),
            "confidence": state.get("plan", {}).get("confidence", 0.0),
        }
        fleet_conv = state.get("fleet_convergence")

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
            timings=timings,
            routing=routing,
            fleet_convergence=fleet_conv,
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
    # Optimized: supports auto fast-path gating (conditional discussion/synthesis LLM)
    # ------------------------------------------------------------------
    def _handle_query_sequential(self, initial: dict, auto_mode: bool = False) -> OrchestratorResponse:
        state: ORCAGraphState = dict(initial)
        trace: list[AgentTrace] = []
        timings: dict = {}
        t_lang0 = time.perf_counter()
        lang_result, t = self.language_agent.run(state["raw_query"])
        timings["language_ms"] = round((time.perf_counter() - t_lang0) * 1000, 1)
        state.update(lang_result)
        trace.append(t)

        t_plan0 = time.perf_counter()
        plan, plan_mode, location, context, t = self._step_plan(
            state["normalized_query"], state["raw_query"], state
        )
        timings["planning_ms"] = round((time.perf_counter() - t_plan0) * 1000, 1)
        timings["routing_ms"] = round(float(plan.get("duration_ms", 0)), 1)
        # Propagate routing/complexity into state for gating decisions
        state.update({"plan": plan, "location": location, "context": context,
                      "routing_mode": plan.get("routing_mode", plan_mode),
                      "complexity": plan.get("complexity", "fast"),
                      "query_depth": state.get("query_depth", QUERY_DEPTH),
                      "mode": state.get("mode", "auto" if auto_mode else "panel")})
        trace.append(t)

        specialists = self._selected_specialists(
            plan,
            live_position=bool(initial.get("device_gps") or initial.get("destination")),
        )
        if not specialists:
            unsupported = self._node_unsupported(state)["response"]
            unsupported.trace = trace + unsupported.trace
            return unsupported

        # Specialists — parallel where possible even in sequential fallback (use threads for independent fetches)
        # For simplicity in fallback, run ocean->hazard sequentially, but PFZ+geofence concurrent
        # Use same parallel dispatch as graph node for consistency
        # We reuse _node_dispatch logic by constructing a mini-state
        tmp_state: ORCAGraphState = {
            "plan": plan, "context": context, "location": location,
            "device_gps": state.get("device_gps"), "destination": state.get("destination"),
            "timings": timings, "traces": trace,
            "mode": state.get("mode", "panel"), "complexity": state.get("complexity", "fast"),
            "query_depth": state.get("query_depth", QUERY_DEPTH)
        }
        dispatch_out = self._node_dispatch(tmp_state)  # type: ignore
        # Merge dispatch results
        for k in ("ocean_state", "risk", "pfz", "geofence", "route", "trend"):
            if k in dispatch_out:
                state[k] = dispatch_out[k]
        trace.extend(dispatch_out.get("traces", []))
        timings.update(dispatch_out.get("timings", {}))

        # Fleet Convergence — after PFZ/geo, before discussion
        t_fleet0 = time.perf_counter()
        fleet_demo = state.get("fleet_demo_level")
        # For sequential, also handle include_simulated logic
        pfz_for_fleet = state.get("pfz")
        if pfz_for_fleet is not None:
            try:
                # Auto-simulate if demo requested and no sim data
                if fleet_demo and pfz_for_fleet:
                    try:
                        recent_sim = fleet_engine.fleet_store.get_recent(include_simulated=True)
                        if not any(a.is_simulated for a in recent_sim):
                            fleet_engine.simulate_fleet_activity(pfz_for_fleet.center_lat, pfz_for_fleet.center_lon, level=fleet_demo)
                    except:
                        pass
                # Include simulated fleet when demo level is set
                fleet_res = fleet_engine.analyze_fleet_convergence(
                    pfz=pfz_for_fleet,
                    ocean_state=state.get("ocean_state"),
                    geofence=state.get("geofence"),
                    risk=state.get("risk"),
                    include_simulated=bool(fleet_demo),
                )
                # Convert to dict for state
                fleet_dict = {
                    "status": fleet_res.status,
                    "window_hours": fleet_res.window_hours,
                    "timestamp": fleet_res.timestamp,
                    "recommendation_changed": fleet_res.recommendation_changed,
                    "change_reason": fleet_res.change_reason,
                    "candidates": [
                        {
                            "zone_id": c.zone_id,
                            "center_lat": c.center_lat,
                            "center_lon": c.center_lon,
                            "distance_km": c.distance_km,
                            "bearing_deg": c.bearing_deg,
                            "sst_celsius": c.sst_celsius,
                            "base_suitability": c.base_suitability,
                            "fleet_count": c.fleet_count,
                            "crowding_ratio": c.crowding_ratio,
                            "crowding_penalty": c.crowding_penalty,
                            "adjusted_suitability": c.adjusted_suitability,
                            "is_safe": c.is_safe,
                            "is_legal": c.is_legal,
                            "is_recommended": c.is_recommended,
                            "source": c.source,
                        } for c in fleet_res.candidates
                    ],
                    "raw_best_zone": {
                        "zone_id": fleet_res.raw_best_zone.zone_id,
                        "center_lat": fleet_res.raw_best_zone.center_lat,
                        "center_lon": fleet_res.raw_best_zone.center_lon,
                        "base_suitability": fleet_res.raw_best_zone.base_suitability,
                        "fleet_count": fleet_res.raw_best_zone.fleet_count,
                        "adjusted_suitability": fleet_res.raw_best_zone.adjusted_suitability,
                    } if fleet_res.raw_best_zone else None,
                    "final_zone": {
                        "zone_id": fleet_res.final_zone.zone_id,
                        "center_lat": fleet_res.final_zone.center_lat,
                        "center_lon": fleet_res.final_zone.center_lon,
                        "base_suitability": fleet_res.final_zone.base_suitability,
                        "fleet_count": fleet_res.final_zone.fleet_count,
                        "adjusted_suitability": fleet_res.final_zone.adjusted_suitability,
                    } if fleet_res.final_zone else None,
                }
                for cand in fleet_dict["candidates"]:
                    ratio = cand["crowding_ratio"]
                    if ratio >= 1.5:
                        cand["crowding_label"] = "🔴 High crowding"
                    elif ratio >= 0.8:
                        cand["crowding_label"] = "🟠 Medium crowding"
                    elif ratio >= 0.3:
                        cand["crowding_label"] = "🟡 Low crowding"
                    else:
                        cand["crowding_label"] = "🟢 Minimal crowding"
                state["fleet_convergence"] = fleet_dict
                trace.append(AgentTrace(agent_name="FleetConvergence", action=f"Analyzed fleet crowding for {len(fleet_res.candidates)} zones [{fleet_res.status}]", result_summary=f"raw {fleet_res.raw_best_zone.zone_id if fleet_res.raw_best_zone else 'none'} → final {fleet_res.final_zone.zone_id if fleet_res.final_zone else 'none'} changed={fleet_res.recommendation_changed}", data_sources=[], duration_ms=(time.perf_counter()-t_fleet0)*1000))
                timings["fleet_ms"] = round((time.perf_counter()-t_fleet0)*1000, 1)
            except Exception as exc:
                trace.append(AgentTrace(agent_name="FleetConvergence", action="Fleet convergence unavailable", result_summary=str(exc), data_sources=[], duration_ms=(time.perf_counter()-t_fleet0)*1000))
                timings["fleet_ms"] = round((time.perf_counter()-t_fleet0)*1000, 1)
                state["fleet_convergence"] = {"status": "UNAVAILABLE", "reason": str(exc), "candidates": []}
        else:
            trace.append(AgentTrace(agent_name="FleetConvergence", action="Skipped fleet convergence — no PFZ", result_summary="No candidates", data_sources=[], duration_ms=(time.perf_counter()-t_fleet0)*1000))
            timings["fleet_ms"] = round((time.perf_counter()-t_fleet0)*1000, 1)
            state["fleet_convergence"] = {"status": "UNAVAILABLE", "reason": "no PFZ", "candidates": []}

        # Discussion gating
        t_disc0 = time.perf_counter()
        if auto_mode and not self._should_run_discussion(state):
            transcript = {"turns": [], "consensus": ""}
            t = AgentTrace(agent_name="DiscussionAgent", action="Skipped round-table (fast path)", result_summary="No discussion for fast query", data_sources=[], duration_ms=(time.perf_counter() - t_disc0)*1000)
            timings["discussion_ms"] = round(t.duration_ms, 1)
        else:
            transcript, t = self.discussion_agent.run(
                context, ocean_state=state.get("ocean_state"),
                risk=state.get("risk"), pfz=state.get("pfz"),
                geofence=state.get("geofence"), route=state.get("route"),
                trend=state.get("trend"),
            )
            timings["discussion_ms"] = round(t.duration_ms, 1)
        state["discussion"] = transcript
        trace.append(t)

        # Synthesis gating
        t_synth0 = time.perf_counter()
        use_llm_synth = (not auto_mode) or self._should_use_synthesis_llm(state)
        if auto_mode and not use_llm_synth:
            synthesis = self.synthesis_agent._fallback_verdict(state.get("risk"))  # type: ignore
            t = AgentTrace(agent_name="SynthesisAgent", action="Deterministic synthesis (fast path)", result_summary=f"Verdict '{synthesis['verdict']}' deterministic", data_sources=[], duration_ms=(time.perf_counter()-t_synth0)*1000)
            timings["synthesis_ms"] = round(t.duration_ms, 1)
        else:
            synthesis, t = self.synthesis_agent.run(
                context, state.get("ocean_state"), state.get("risk"),
                pfz=state.get("pfz"), geofence=state.get("geofence"),
                route=state.get("route"), trend=state.get("trend"),
                discussion=transcript,
            )
            timings["synthesis_ms"] = round(t.duration_ms, 1)
        state["synthesis"] = synthesis
        trace.append(t)

        # Response gating — deterministic for fast auto queries
        t_resp0 = time.perf_counter()
        use_deterministic = auto_mode and state.get("complexity") in ("fast", "standard") and state.get("query_depth") != "deep" and state.get("risk") is not None and not use_llm_synth
        if use_deterministic:
            answer = self._deterministic_answer(state)  # type: ignore
            t = AgentTrace(agent_name="ResponseAgent", action="Composed deterministic answer (fast path)", result_summary=f"Answer {len(answer)} chars deterministic", data_sources=[], duration_ms=(time.perf_counter()-t_resp0)*1000)
            timings["response_ms"] = round(t.duration_ms, 1)
        else:
            answer, t = self.response_agent.run(
                context, synthesis,
                ocean_state=state.get("ocean_state"), risk=state.get("risk"),
                pfz=state.get("pfz"), geofence=state.get("geofence"),
                route=state.get("route"), trend=state.get("trend"),
                discussion=transcript,
            )
            timings["response_ms"] = round(t.duration_ms, 1)
        state["traces"] = trace[:-1]  # response node appends its own
        state["timings"] = timings
        response = self._assemble_response(state, answer)
        response.trace = trace
        # Attach timings to response for telemetry serialization
        response.timings = timings  # type: ignore
        # Safety clamp
        risk = state.get("risk")
        if risk is not None and risk.status.value == "UNSAFE" and response.status.value != "UNSAFE":
            response.status = risk.status
        # Record fleet activity for future convergence (real only)
        try:
            self._record_fleet_activity(state, response)
        except:
            pass
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
    # Planning — FAST deterministic router first, LLM as fallback only when uncertain
    # ------------------------------------------------------------------
    def _plan(self, normalized_query: str, prior=None) -> tuple[dict, str]:
        """
        Routing pipeline optimized for latency:
        1. FAST deterministic router (0 LLM calls, <1ms) — handles obvious intents.
        2. LLM planner (1 structured call, low max_tokens, fast timeout) — only if fast router uncertain.
        3. Deterministic rule fallback — if LLM unavailable/failed.
        """
        start = time.perf_counter()

        # 1. Try fast deterministic router FIRST
        fast_decision = None
        if _AUTO_ROUTER_AVAILABLE and auto_router is not None:
            try:
                fast_decision = auto_router.fast_route(normalized_query)
            except Exception:
                fast_decision = None

        if fast_decision is not None and not auto_router.should_use_llm_fallback(fast_decision, normalized_query):  # type: ignore
            # Confident fast routing — no LLM needed (0-1 LLM calls saved)
            plan = {
                "intent": fast_decision.intent,
                "location_name": self._extract_place_name(normalized_query),
                "time_window": self._extract_time_window(normalized_query),
                "target_hour": self._extract_target_hour(normalized_query),
                "months_back": 6 if fast_decision.intent == Intent.TREND_ANALYSIS else None,
                "agents_needed": fast_decision.agents,
                "why": f"[fast-rules] {fast_decision.reason}",
                "duration_ms": (time.perf_counter() - start) * 1000,
                "routing_mode": fast_decision.routing_mode,
                "complexity": fast_decision.complexity,
                "confidence": fast_decision.confidence,
            }
            # Memory override for "same place" — copy prior location
            if prior is not None and prior.location_name and plan["location_name"] in ("unknown", "", "same"):
                plan["location_name"] = prior.location_name
                plan["why"] += " (location inherited from conversation memory)"
            return plan, "fast-rules"

        # 2. Fallback: LLM planner (only when fast router uncertain or unavailable)
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
                # For fast routing fallback, use low budget (fast timeout, few tokens, no retry)
                # For ambiguous queries we still want the LLM, but we don't want to wait for a retry.
                is_fallback = fast_decision is None
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
                    max_tokens=llm_client.LLM_MAX_TOKENS_ROUTING,
                    timeout=llm_client.LLM_TIMEOUT_FAST_S,
                    attempts=1,  # no retry — fall back to rules instantly rather than wait
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
                    "routing_mode": "llm-planner",
                    "complexity": "standard",
                }
                # Infer complexity for LLM-planned query
                if plan["intent"] == Intent.TREND_ANALYSIS:
                    plan["complexity"] = "deep"
                elif plan["intent"] in (Intent.ZONE_SCAN, Intent.ROUTE_PLAN) and len(plan.get("agents_needed") or []) >= 4:
                    plan["complexity"] = "complex"
                return plan, "llm-planner"
            except llm_client.LLMUnavailableError:
                pass  # fall through to rule-based planning

        # 3. Deterministic rule fallback (no LLM)
        # If fast router gave a low-confidence hint, reuse its intent to avoid re-parsing
        fallback_intent = (fast_decision.intent if fast_decision is not None else self._route_intent(normalized_query))
        plan = {
            "intent": fallback_intent,
            "location_name": self._extract_place_name(normalized_query),
            "time_window": self._extract_time_window(normalized_query),
            "target_hour": self._extract_target_hour(normalized_query),
            "months_back": 6 if "trend" in normalized_query.lower() or
                            "declined" in normalized_query.lower() else None,
            "agents_needed": (fast_decision.agents if fast_decision is not None else []),
            "why": "[rules] Rule-based keyword parsing used (fast router uncertain, LLM unavailable).",
            "duration_ms": (time.perf_counter() - start) * 1000,
            "routing_mode": "rules",
            "complexity": (fast_decision.complexity if fast_decision is not None else "fast"),
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
