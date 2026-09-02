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
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, List, Optional, TypedDict

import llm_client
import sessions as session_store
import fleet_convergence as fleet_engine
import wind_divergence as wind_engine
import routing_telemetry
from agents.discussion_agent import DiscussionAgent
from agents.geospatial_agent import GeospatialAgent
from agents.hazard_agent import HazardAgent, get_thresholds
from agents.language_agent import LanguageAgent
from agents.ocean_state_agent import OceanStateAgent
from agents.pfz_agent import PFZAgent
from agents.pfz_output import format_pfz_answer
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
#
# Single source of truth: the gazetteer lives in orchestrator/state.py and is
# imported here so the two copies can never drift.
from .state import KNOWN_LOCATIONS, DEFAULT_LOCATION

_geocode_cache: dict[str, Location] = {}

# Degraded-mode messages for non-English queries when LLM translation is unavailable.
# Each message honestly explains limited mode and suggests retry or English.
_DEGRADED_MESSAGES: dict[str, str] = {
    "en": "Service is running in limited mode right now, please try again shortly or ask in English.",
    "hi": "सेवा फिलहाल सीमित मोड में चल रही है। कृपया थोड़ी देर बाद पुनः प्रयास करें या अंग्रेज़ी में पूछें।",
    "mr": "सेवा सध्या मर्यादित मोडमध्ये चालू आहे. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा किंवा इंग्रजीत विचारा.",
    "ta": "சேவை தற்போது வரையறுக்கப்பட்ட முறையில் இயங்குகிறது. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும் அல்லது ஆங்கிலத்தில் கேட்கவும்.",
    "te": "సేవ ప్రస్తుతం పరిమిత మోడ్‌లో నడుస్తోంది. దయచేసి కొద్దిసేపటి తర్వాత మళ్లీ ప్రయత్నించండి లేదా ఆంగ్లంలో అడగండి.",
    "bn": "পরিষেবাটি বর্তমানে সীমিত মোডে চলছে। অনুগ্রহ করে কিছুক্ষণ পরে আবার চেষ্টা করুন বা ইংরেজিতে জিজ্ঞাসা করুন।",
    "ml": "സേവനം ഇപ്പോൾ പരിമിത മോഡിൽ പ്രവർത്തിക്കുന്നു. ദയവായി കുറച്ച് സമയത്തിന് ശേഷം വീണ്ടും ശ്രമിക്കുക അല്ലെങ്കിൽ ഇംഗ്ലീഷിൽ ചോദിക്കുക.",
    "kn": "ಸೇವೆ ಪ್ರಸ್ತುತ ಸೀಮಿತ ಮೋಡ್‌ನಲ್ಲಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿದೆ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ ಅಥವಾ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಕೇಳಿ.",
    "gu": "સેવા હાલમાં મર્યાદિત મોડમાં ચાલી રહી છે. કૃપા કરીને થોડા સમય પછી ફરી પ્રયાસ કરો અથવા અંગ્રેજીમાં પૂછો.",
    "or": "ସେବା ବର୍ତ୍ତମାନ ସୀମିତ ମୋଡରେ ଚାଲୁଛି। ଦୟାକରି କିଛି ସମୟ ପରେ ପୁନର୍ବାର ଚେଷ୍ଟା କରନ୍ତୁ କିମ୍ବା ଇଂରାଜୀରେ ପଚାରନ୍ତୁ।",
    "pa": "ਸੇਵਾ ਇਸ ਵੇਲੇ ਸੀਮਤ ਮੋਡ ਵਿੱਚ ਚੱਲ ਰਹੀ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਥੋੜ੍ਹੀ ਦੇਰ ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ ਜਾਂ ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਪੁੱਛੋ।",
}


def _degraded_message_for(lang: str) -> str:
    return _DEGRADED_MESSAGES.get(lang, _DEGRADED_MESSAGES["en"])


def _contains_indic_script(text: str) -> bool:
    """True if text contains any Indic Unicode block (Devanagari etc.)."""
    for ch in text or "":
        cp = ord(ch)
        # Devanagari 0900-097F, Bengali 0980-09FF, etc. up to Malayalam 0D7F
        if 0x0900 <= cp <= 0x0D7F:
            return True
        # also Gujarati 0A80 etc. already covered, but add Odia/others
        if 0x0A00 <= cp <= 0x0AFF or 0x0B00 <= cp <= 0x0BFF or 0x0C00 <= cp <= 0x0CFF:
            return True
    return False

# Romanized (Latin-script) regional language keywords — Task 2 extension
ROMANIZED_KEYWORDS: dict[str, list[str]] = {
    "hi": [
        "surakshit", "suraksha", "machli", "machhli", "machhara", "samundar",
        "samundra", "toofan", "khatra", "chetavni", "leher", "hawa",
        "kinara", "mausam", "jaal", "machuara",
    ],
    "mr": [
        "surakshit", "maasa", "samudra", "vadal", "dhoka", "ishara",
        "lahari", "vaara", "kinara", "maasaemari", "hawaman", "kolivada",
        "maase", "dhokadayak",
    ],
    "ta": [
        "paadukappu", "meen", "kadal", "apayam", "echcharikkai", "alai",
        "kaatru", "karai", "meenpidippu", "vaanilai", "puyal", "suzhal",
        "meenpidippa", "kadalora",
    ],
    "te": [
        "bhadrata", "chepa", "samudram", "pramadam", "hechcharika", "alalu",
        "gali", "teeram", "chepala", "vaatavaranam", "toofan", "chakravatam",
        "samudra", "chepalu",
    ],
    "bn": [
        "nirapad", "machh", "samudra", "bipad", "satarkata", "dheu",
        "hawa", "upakul", "jal", "abhawa", "jhor", "ghurnijhar",
        "machher", "samudre",
    ],
    "ml": [
        "suraksha", "meen", "kadal", "apakadam", "munnaicharika", "thira",
        "kaattu", "karavan", "meenpiditham", "kalavastha", "kottumkaatu",
        "chakravatam", "kadalora", "meenukal",
    ],
    "kn": [
        "suraksha", "meenu", "samudra", "apaya", "hechcharike", "ale",
        "gaali", "karavali", "meenugarike", "havamana", "bharane", "chakravata",
        "samudrada", "meenugalu",
    ],
    "gu": [
        "surakshit", "machhli", "samudra", "khatro", "chetavni", "lahari",
        "hawa", "kinaro", "machhimari", "havaman", "vavazodu", "chakravat",
        "dariyo", "machhal",
    ],
    "or": [
        "suraksha", "machha", "samudra", "bipad", "satarka", "dheu",
        "pabana", "kula", "jal", "panipaga", "jhada", "batya",
        "samudrakula", "macha",
    ],
    "pa": [
        "surakhia", "machhi", "samundar", "khatra", "chetavni", "lehar",
        "hawa", "kinara", "machhi", "mausam", "toofan", "chakravat",
        "jal", "samundra",
    ],
}

_ROMANIZED_WORD_TO_LANG: dict[str, str] = {}
for _lang, _words in ROMANIZED_KEYWORDS.items():
    for _w in _words:
        _lw = _w.lower()
        if _lw not in _ROMANIZED_WORD_TO_LANG:
            _ROMANIZED_WORD_TO_LANG[_lw] = _lang

def _contains_romanized_regional_language(text: str) -> bool:
    if not text or not text.strip():
        return False
    low = text.lower()
    import re
    words = set(re.findall(r"[a-zA-Z]+", low))
    for w in words:
        if w in _ROMANIZED_WORD_TO_LANG:
            return True
    for kw in _ROMANIZED_WORD_TO_LANG:
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return True
    return False

def _detect_romanized_language(text: str) -> str | None:
    if not text:
        return None
    low = text.lower()
    import re
    words = re.findall(r"[a-zA-Z]+", low)
    for w in words:
        if w in _ROMANIZED_WORD_TO_LANG:
            return _ROMANIZED_WORD_TO_LANG[w]
    for kw, lang in _ROMANIZED_WORD_TO_LANG.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return lang
    return None


def resolve_location(place_name: str) -> Location | None:
    """Free-text place name -> Location or None. Never defaults to Panaji."""
    key = " ".join((place_name or "").strip().lower().split())
    bare = key[:-6].strip() if key.endswith(" coast") else key
    if bare in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[bare]
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key]
    if key in _geocode_cache:
        return _geocode_cache[key]
    if key and key != "unknown":
        try:
            import data_connectors.geocode as geocode

            hit = geocode.geocode(key)
        except Exception as exc:  # network down -> no location
            import logging

            logging.getLogger("orca.orchestrator").warning(
                "geocoding '%s' failed (%s); no location", place_name, exc,
            )
            return None
        if hit:
            lat, lon, display = hit
            loc = Location(name=display.split(",")[0].strip() + " Coast", lat=lat, lon=lon)
            _geocode_cache[key] = loc
            return loc
    return None

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
    "ocean_state": ["OceanStateAgent"],
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
                "ocean_state",     # sea/weather conditions: wind, waves, SST, tide
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
                "(fishing/boating). ocean_state = sea/weather conditions only "
                "(weather, forecast, wind, waves, swell, SST, chlorophyll, tide). "
                "pfz_lookup = finding fishing zones. "
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
    OCEAN_STATE = "ocean_state"
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
    map_point: Optional[tuple] = None
    destination: Optional[Location]
    vessel_class: str

    normalized_query: str
    language: str
    language_mode: str  # fast-path | llm | rules (from LanguageAgent)
    plan: dict
    plan_mode: str
    # Routing explainability (auto mode)
    routing_mode: str  # fast-rules | llm-planner | rules | degraded
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
    wind_divergence: Optional[dict]  # WindDivergenceResult as dict (Innovation #4)
    wind_demo_scenario: Optional[str]  # match/moderate/high_divergence for demo


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
        # Short-lived in-process response cache: identical repeated queries within
        # RESPONSE_CACHE_TTL_S return the prior OrchestratorResponse instead of
        # re-running the whole LLM pipeline. Keyed on the request signature (NOT
        # session_id, so a refresh/retry of the same question is instant).
        self._response_cache: dict[tuple, tuple[float, "OrchestratorResponse"]] = {}

    # ------------------------------------------------------------------
    # Graph assembly
    # ------------------------------------------------------------------
    def _build_graph(self):
        g = StateGraph(ORCAGraphState)
        g.add_node("language_intent", self._node_language)
        g.add_node("planning", self._node_planning)
        g.add_node("specialists", self._node_dispatch)
        g.add_node("fleet_convergence", self._node_fleet_convergence)
        g.add_node("wind_divergence", self._node_wind_divergence)
        g.add_node("discussion", self._node_discussion)
        g.add_node("synthesis", self._node_synthesis)
        g.add_node("safety_floor", self._node_safety_floor)
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
        g.add_edge("fleet_convergence", "wind_divergence")
        g.add_edge("wind_divergence", "discussion")
        g.add_edge("discussion", "synthesis")
        g.add_edge("synthesis", "safety_floor")
        g.add_edge("safety_floor", "response")
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

        Compound-intent (Task 4): when is_compound is True, requested is
        already a union of multiple intents' agents — use it directly
        (deduplicated) instead of intersecting with single intent's defaults.
        """
        requested = {a for a in (plan.get("agents_needed") or [])}
        # Compound: use union directly
        if plan.get("is_compound"):
            chosen = set(requested)
            # Still ensure hazard dependency and live_position
        else:
            defaults = INTENT_DEFAULT_AGENTS.get(plan["intent"], [])
            chosen = requested & set(defaults) or set(defaults)
        # Hazard runs implicitly for safety-oriented intents (mirrors the
        # needs_hazard logic in _node_dispatch) even if the planner named only
        # OceanStateAgent, so it must be REPORTED as a selected specialist too —
        # otherwise the reported agent list understates what actually executed.
        _intent_val = plan.get("intent")
        if ("HazardAgent" in chosen) or (
            "OceanStateAgent" in chosen
            and _intent_val in ("safety_check", "hazard_alerts", "zone_scan", "route_plan")
        ):
            chosen.add("HazardAgent")
        # Dependency repair: hazard needs an ocean reading.
        if "HazardAgent" in chosen:
            chosen.add("OceanStateAgent")
        # Fishing-suitability: a "can I go fishing here?" query is routed as a
        # safety_check/ocean_state but the answer must also weigh PROXIMITY TO A
        # PFZ. Run the PFZ agent so the summary can give a holistic go/no-go
        # (near a fishing zone + safe conditions -> go). The needs_pfz rule in
        # _node_dispatch keys off "pfz" being in the selected nodes.
        if plan.get("fishing_context") and _intent_val in ("safety_check", "ocean_state"):
            chosen.add("PFZAgent")
        # Geospatial only runs for intents that actually ask about boundaries /
        # routes / zones — NEVER blanket-forced just because GPS was sent (an
        # "SST near me" query must stay ocean_state-only).
        _intent_defaults = INTENT_DEFAULT_AGENTS.get(plan.get("intent"), []) or []
        if live_position and "GeospatialAgent" in _intent_defaults:
            chosen.add("GeospatialAgent")
        nodes: List[str] = []
        if "TrendAgent" in chosen and plan["intent"] == Intent.TREND_ANALYSIS:
            nodes.append("trend")
            return nodes
        if "OceanStateAgent" in chosen:
            nodes.append("ocean_state")
        if "HazardAgent" in chosen:
            nodes.append("hazard")
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

    def _record_telemetry(self, state: dict | ORCAGraphState, response: OrchestratorResponse, total_ms: float):
        """Lightweight routing telemetry — best-effort, never fails query."""
        try:
            routing_mode = state.get("routing_mode") or state.get("plan", {}).get("routing_mode", "rules")
            complexity = state.get("complexity") or state.get("plan", {}).get("complexity", "fast")
            mode = state.get("mode") or getattr(response, "mode", "auto")
            # Determine if discussion/synthesis LLM actually ran by inspecting traces
            traces = list(state.get("traces") or []) + list(getattr(response, "trace", []) or [])
            # Fallback: also check response.trace
            discussion_ran = False
            synthesis_ran = False
            for t in traces:
                name = getattr(t, "agent_name", "") or t.get("agent_name", "") if isinstance(t, dict) else getattr(t, "agent_name", "")
                action = getattr(t, "action", "") or t.get("action", "") if isinstance(t, dict) else getattr(t, "action", "")
                if name == "DiscussionAgent":
                    if "Skipped" not in action:
                        discussion_ran = True
                if name == "SynthesisAgent":
                    if "Skipped" not in action and "Deterministic" not in action:
                        synthesis_ran = True
            # Also respect the gating logic if traces ambiguous
            # If no Discussion trace found, infer via _should_run_discussion
            if not any(getattr(t, "agent_name", "") == "DiscussionAgent" for t in traces if hasattr(t, "agent_name")):
                try:
                    discussion_ran = self._should_run_discussion(state)  # type: ignore
                except:
                    pass
            if not any(getattr(t, "agent_name", "") == "SynthesisAgent" for t in traces if hasattr(t, "agent_name")):
                try:
                    synthesis_ran = self._should_use_synthesis_llm(state)  # type: ignore
                except:
                    pass
            routing_telemetry.record(
                routing_mode=routing_mode,
                complexity=complexity,
                discussion_ran=discussion_ran,
                synthesis_ran=synthesis_ran,
                latency_ms=total_ms,
                mode=mode,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lightweight routing debug log (Step 10) — never fails the query.
    # ------------------------------------------------------------------
    def _log_routing(self, state, plan: dict) -> None:
        try:
            import logging
            log = logging.getLogger("orca.orchestrator")
            intent = plan.get("intent", "unknown")
            agents = INTENT_DEFAULT_AGENTS.get(intent, []) or plan.get("agents_needed", [])
            sel = self._selected_specialists(
                plan,
                live_position=bool(state.get("device_gps") or state.get("destination")),
            )
            log.info(
                "Detected Intent: %s | Selected Agent(s): %s | [%s] %s",
                intent,
                ", ".join(a.replace("Agent", "").strip() for a in sel) or "(none)",
                plan.get("routing_mode", "rules"),
                plan.get("why", ""),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public entrypoint — now supports auto | panel | agent
    # ------------------------------------------------------------------
    def handle_query(
        self,
        raw_query: str,
        session_id: str | None = None,
        device_gps: tuple | None = None,
        destination: Location | None = None,
        map_point: tuple | None = None,
        mode: str = "auto",
        target_agent: str | None = None,
        vessel_class: str | None = None,
        query_depth: str | None = None,
        fleet_demo_level: str | None = None,
        wind_demo_scenario: str | None = None,
    ) -> OrchestratorResponse:
        # Normalize mode (backwards compat: panel default previously)
        mode_norm = (mode or "auto").strip().lower()
        if mode_norm not in ("auto", "panel", "agent"):
            mode_norm = "auto"
        session_id = session_id or str(uuid.uuid4())
        # Short-lived response cache: an identical repeated request (same query,
        # mode, location, vessel, depth) within RESPONSE_CACHE_TTL_S is served
        # from memory so a refresh/retry is instant instead of re-running the LLM
        # pipeline. session_id is deliberately excluded from the key.
        def _dest_sig(d):
            return (round(d.lat, 4), round(d.lon, 4)) if d is not None else None
        cache_key = (
            (raw_query or "").strip().lower(),
            mode_norm,
            device_gps,
            map_point,
            _dest_sig(destination),
            (vessel_class or "small_fishing_boat"),
            target_agent,
            (query_depth or QUERY_DEPTH),
            fleet_demo_level,
            wind_demo_scenario,
        )
        try:
            hit = self._response_cache.get(cache_key)
            if hit is not None and (time.perf_counter() - hit[0]) < RESPONSE_CACHE_TTL_S:
                return hit[1]
        except Exception:
            pass
        # Demo cache check — Task 9, feature-flagged, default off
        try:
            import demo_cache
            if demo_cache.is_enabled():
                cached = demo_cache.get_cached_orchestrator_response(raw_query, session_id)
                if cached is not None:
                    # Ensure session_id handling and mode
                    cached.mode = "cached_demo"
                    return cached
        except Exception:
            pass
        initial: ORCAGraphState = {
            "raw_query": raw_query,
            "session_id": session_id,
            "device_gps": device_gps,
            "map_point": map_point,
            "destination": destination,
            "vessel_class": vessel_class or "small_fishing_boat",
            "mode": mode_norm,
            "query_depth": (query_depth or QUERY_DEPTH).strip().lower() if query_depth else QUERY_DEPTH,
            "fleet_demo_level": (fleet_demo_level.strip().lower() if fleet_demo_level else None),
            "wind_demo_scenario": (wind_demo_scenario.strip().lower() if wind_demo_scenario else None),
            "timings": {},
            "traces": [],
        }
        if mode_norm == "agent" and target_agent in SPECIALIST_REGISTRY:
            resp = self._handle_single_agent(initial, target_agent)
        elif mode_norm == "panel":
            resp = self._handle_query_panel(initial)
        else:
            # auto is default
            resp = self._handle_query_auto(initial)
        # Populate the short-lived response cache for instant identical retries.
        try:
            self._response_cache[cache_key] = (time.perf_counter(), resp)
        except Exception:
            pass
        return resp

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
            # Telemetry: record routing/synthesis
            try:
                self._record_telemetry(final_state, response, total_ms)
            except:
                pass
            # Gap 2 — persist verdict/findings for next follow-up
            try:
                self._persist_conversation_findings(initial.get("session_id") or "", response, plan)
            except:
                pass
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
        # Telemetry
        try:
            # Build minimal state for telemetry from response trace/timings
            state = {"routing_mode": getattr(response, "routing", {}).get("routing_mode", "rules") if hasattr(response, "routing") else "rules",
                     "complexity": getattr(response, "routing", {}).get("complexity", "fast") if hasattr(response, "routing") else "fast",
                     "mode": "auto", "traces": response.trace, "timings": getattr(response, "timings", {})}
            self._record_telemetry(state, response, total_ms)
        except:
            pass
        try:
            self._persist_conversation_findings(initial.get("session_id") or "", response, getattr(response, "routing", {}) or {})
        except:
            pass
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
        """LLM must NEVER override deterministic UNSAFE/EXTREME. If hazard says UNSAFE/EXTREME, response stays there."""
        risk = state.get("risk")
        if risk is not None and hasattr(risk, "status") and risk.status.value in ("UNSAFE", "EXTREME", "CRITICAL"):
            if response.status.value not in ("UNSAFE", "EXTREME", "CRITICAL"):
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

    def _persist_conversation_findings(self, session_id: str, response: OrchestratorResponse, plan: dict | None = None) -> None:
        """Gap 2 — store the last verdict/answer/evidence so follow-ups like
        'why is that?' or 'what about the wind?' can be answered with context."""
        try:
            verdict = ""
            evidence = ""
            # Prefer synthesis verdict, fallback to response status
            synth = getattr(response, "status", None)
            if synth:
                v = getattr(synth, "value", str(synth))
                verdict = v
            # Evidence: first reasoning line or key evidence
            reasons = getattr(response, "reasoning", []) or []
            if reasons:
                evidence = str(reasons[0])[:400]
            elif getattr(response, "answer", None):
                evidence = str(response.answer)[:400]
            answer_snippet = str(getattr(response, "answer", ""))[:600]
            # Also include prior intent's evidence if available (e.g. PFZ distance)
            if plan and plan.get("intent"):
                evidence = f"[{plan.get('intent')}] {evidence}"
            session_store.upsert(
                session_id,
                last_verdict=verdict,
                last_answer=answer_snippet,
                last_evidence=evidence,
            )
        except Exception:
            pass  # never break the response on persistence failure

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
            try:
                self._record_telemetry(final_state, response, total_ms)
            except:
                pass
            try:
                self._persist_conversation_findings(initial.get("session_id") or "", response, final_state.get("plan") or {})
            except:
                pass
            return response
        response = self._handle_query_sequential(initial)
        response.mode = "panel"
        response.answered_by = "ORCA panel (specialists discussed before answering)"
        try:
            # For sequential fallback, record from response if available
            self._record_fleet_activity({"pfz": getattr(response, "pfz", None), "fleet_convergence": getattr(response, "fleet_convergence", None), "session_id": initial.get("session_id")}, response)
        except:
            pass
        try:
            state = {"routing_mode": getattr(response, "routing", {}).get("routing_mode", "rules") if hasattr(response, "routing") else "rules",
                     "complexity": getattr(response, "routing", {}).get("complexity", "fast") if hasattr(response, "routing") else "fast",
                     "mode": "panel", "traces": response.trace, "timings": getattr(response, "timings", {})}
            self._record_telemetry(state, response, 0)
        except:
            pass
        try:
            self._persist_conversation_findings(initial.get("session_id") or "", response, getattr(response, "routing", {}) or {})
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
            "language_mode": result.get("mode", "unknown"),
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
        # If location unresolved, skip all specialists — response will ask user
        if plan.get("needs_location"):
            return {"ocean_state": None, "pfz": None, "geofence": None, "route": None, "trend": None, "risk": None, "timings": {}, "traces": []}
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
            _OCEAN_FUTURE_TIMEOUT = float(os.getenv("ORCA_OCEAN_FUTURE_TIMEOUT_S", "30").strip() or 30)
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
                    # Timeout → inject an explicit "unavailable" reading so weather
                    # queries still return a structured response with a clear reason
                    # (never fabricate marine values).
                    if ocean_reading is None and "ocean_state" in selected:
                        try:
                            from models import AgentTrace as _AT
                            import time as _t
                            _s = _t.perf_counter()
                            ocean_reading = self.ocean_state_agent._unavailable_reading(
                                location,
                                reason=f"INCOIS Ocean State Forecast timed out after {_OCEAN_FUTURE_TIMEOUT:.0f}s",
                            )
                            ocean_trace = _AT(
                                agent_name=self.ocean_state_agent.name,
                                action="Ocean-State degraded fallback after timeout",
                                result_summary=(
                                    "Live INCOIS value unavailable (timeout) — no fabricated "
                                    "marine conditions; all fields unavailable"
                                ),
                                data_sources=["unavailable"],
                                duration_ms=(_t.perf_counter() - _s) * 1000,
                            )
                            traces.append(ocean_trace)
                            results["ocean_state"] = ocean_reading
                            logger.warning("ocean_state timeout fallback: unavailable reading for %s", getattr(location, "name", ""))
                        except Exception as _e2:
                            logger.warning("ocean unavailable fallback also failed: %s", _e2)
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
                    # PFZ needs longer for INCOIS fetch (500KB + inland SST ring)
                    _to = 35.0 if key == "pfz" else (15.0 if key == "geofence" else 25.0)
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

    def _compute_wind_divergence(self, state: ORCAGraphState) -> tuple[dict, AgentTrace]:
        """Shared by the graph node and the sequential fallback (Innovation #4).

        Non-blocking by construction: the real satellite provider isn't
        activated (instant local check), and the demo path is deterministic
        -- neither ever waits on a network call, so normal ORCA queries are
        never slowed down by this check.
        """
        t0 = time.perf_counter()
        ocean = state.get("ocean_state")
        location = state.get("location")
        demo_scenario = state.get("wind_demo_scenario")
        if ocean is None or location is None:
            trace = AgentTrace(
                agent_name="WindDivergence",
                action="Skipped wind divergence — no forecast wind for this query",
                result_summary="No ocean-state reading available",
                data_sources=[], duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return {"status": "UNAVAILABLE", "reason": "no forecast wind"}, trace
        try:
            result = wind_engine.analyze_wind_divergence(
                forecast_wind_kmh=ocean.wind_speed_kmh,
                location=location,
                demo_scenario=demo_scenario,
            )
            result_dict = wind_engine.result_to_dict(result)
            trace = AgentTrace(
                agent_name="WindDivergence",
                action=f"Compared forecast vs satellite wind [{result_dict['status']}]",
                result_summary=(
                    f"forecast {result_dict['forecast_wind_kn']}kn vs satellite "
                    f"{result_dict.get('satellite_wind_kn')}kn — {result.warning} "
                    f"(satellite: {result_dict['satellite_status']})"
                ),
                data_sources=[], duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return result_dict, trace
        except Exception as exc:
            import logging
            logging.getLogger("orca.orchestrator").warning("wind divergence failed: %s", exc)
            trace = AgentTrace(
                agent_name="WindDivergence",
                action="Wind divergence unavailable — normal forecast behaviour preserved",
                result_summary=str(exc), data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return {"status": "UNAVAILABLE", "reason": str(exc)}, trace

    def _node_wind_divergence(self, state: ORCAGraphState) -> dict:
        result_dict, trace = self._compute_wind_divergence(state)
        timings = dict(state.get("timings") or {})
        timings["wind_divergence_ms"] = round(trace.duration_ms, 1)
        return {"wind_divergence": result_dict, "traces": [trace], "timings": timings}

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

    def _node_safety_floor(self, state: ORCAGraphState) -> dict:
        """Deterministic safety-floor pass — Task 8. Only ever RAISES verdict."""
        t0 = time.perf_counter()
        synthesis = state.get("synthesis") or {}
        risk = state.get("risk")
        # Import here to avoid circular and keep fallback light
        try:
            import safety_floor
            new_synthesis = safety_floor.apply_safety_floor(synthesis, risk)
            new_risk = safety_floor.enforce_risk_floor(risk)
            # Check if floor triggered
            floor_triggered = new_synthesis is not synthesis or new_synthesis.get("safety_floor_applied")
            # Also check verdict raised
            if floor_triggered or new_synthesis.get("verdict") != synthesis.get("verdict"):
                trace = AgentTrace(
                    agent_name="SafetyFloor",
                    action="Applied safety floor — raised verdict to EXTREME due to severe IMD warning",
                    result_summary=f"Synthesis verdict '{synthesis.get('verdict')}' -> '{new_synthesis.get('verdict')}' (severe warning active)",
                    data_sources=list(risk.evidence_sources) if risk else [],
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )
                timings = dict(state.get("timings") or {})
                timings["safety_floor_ms"] = round(trace.duration_ms, 1)
                return {"synthesis": new_synthesis, "risk": new_risk, "traces": [trace], "timings": timings}
            # No floor needed
            trace = AgentTrace(
                agent_name="SafetyFloor",
                action="Safety floor check — no severe warning, verdict unchanged",
                result_summary=f"Verdict '{synthesis.get('verdict')}' remains (no severe IMD warning)",
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["safety_floor_ms"] = round(trace.duration_ms, 1)
            return {"synthesis": synthesis, "risk": risk, "traces": [trace], "timings": timings}
        except Exception as exc:
            # Never break pipeline on floor failure
            import logging
            logging.getLogger("orca.orchestrator").warning("safety floor failed: %s", exc)
            trace = AgentTrace(
                agent_name="SafetyFloor",
                action="Safety floor check failed — pipeline continued",
                result_summary=str(exc)[:200],
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["safety_floor_ms"] = round(trace.duration_ms, 1)
            return {"synthesis": synthesis, "risk": risk, "traces": [trace], "timings": timings}

    def _node_response(self, state: ORCAGraphState) -> dict:
        t0 = time.perf_counter()
        # Location unresolved → ask user (never default to Panaji)
        plan = state.get("plan") or {}
        if plan.get("needs_location"):
            ask_msg = plan.get("ask_message") or "I couldn't determine your location. Please enable GPS or tell me a coastal location such as Ratnagiri, Veraval, Kochi, or coordinates."
            resp_trace = AgentTrace(
                agent_name="ResponseAgent",
                action="Location unresolved — asked user for location",
                result_summary="No GPS, map selection, or chat location; prompted user.",
                data_sources=[],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            timings = dict(state.get("timings") or {})
            timings["response_ms"] = round(resp_trace.duration_ms, 1)
            response = self._assemble_response(state, ask_msg)
            response.trace.append(resp_trace)
            # Override assembled answer with ask message
            response.answer = ask_msg
            return {"response": response, "traces": [resp_trace], "timings": timings}
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
        # PFZ lookups: documented template (official or estimated) — always show Target Coordinates
        # unless fleet convergence actively changed the recommendation. This one
        # block stays structured on purpose: the coordinates, distance/bearing and
        # source chip ARE the answer to "where are the fish" and a skipper steers
        # by them. The prose above it is still AI-written and varies per query.
        if (state.get("plan", {}).get("intent") == "pfz_lookup"
                and pfz is not None
                and not (fleet and fleet.get("recommendation_changed"))):
            verdict = ((state.get("synthesis") or {}).get("verdict")
                       or (risk.status.value if risk else "CAUTION"))
            # Query-specific AI narrative REPLACES the templated intro sentence
            # (spec Parts B/C) -- same helper used on the LLM response path, so
            # PFZ answers read conversationally without repeating "The nearest
            # official INCOIS PFZ is ...". Cards/coordinates/scores untouched.
            narrative = None
            try:
                from agents.response_agent import _pfz_narrative
                narrative = _pfz_narrative(context, pfz, state.get("language", "en"))
            except Exception:
                narrative = None
            formatted = format_pfz_answer(pfz, verdict=verdict, narrative=narrative,
                                          language=state.get("language", "en"))
            if formatted:
                return formatted[:1500]
        # ---- Narrative mode (default) ---------------------------------------
        # One AI pass writes the entire answer as varied prose — no fixed
        # headings, no "| Parameter | Value |" table, a different structure each
        # time. The verdict badge and the metric tiles are rendered by the UI
        # from the STRUCTURED response fields, so nothing is lost by dropping
        # the markdown scaffolding here. Falls through to the deterministic
        # template below whenever the LLM is down or the guards reject the text.
        try:
            _narr_text = self._narrative_answer(
                state, risk=risk, ocean=ocean, pfz=pfz,
                geofence=geofence, route=route, trend=state.get("trend"),
            )
        except Exception:
            _narr_text = None
        if _narr_text:
            _out = [_narr_text]
            # Fleet convergence genuinely CHANGES the recommendation — keep it.
            if fleet and fleet.get("recommendation_changed") and fleet.get("final_zone"):
                _f = fleet["final_zone"]
                _sim = " [DEMO — SIMULATED FLEET ACTIVITY]" if str(fleet.get("status", "")).startswith("SIMULATED") else ""
                _out.append(
                    f"🎣 Fleet convergence{_sim}: {_f['zone_id']} at "
                    f"{_f['center_lat']:.3f}, {_f['center_lon']:.3f} is the less "
                    f"crowded pick ({_f['fleet_count']} vessels, adjusted "
                    f"suitability {_f['adjusted_suitability']})."
                )
            try:
                from agents.response_agent import _source_line as _src_line
                _out.append(_src_line(state.get("language", "en")))
            except Exception:
                _out.append("*Source: Official INCOIS Ocean State Forecast + OceanSat-2 + Gemini PFZ*")
            return "\n\n".join(_out)[:1500]
        # Verdict line is authoritative and already rendered as HUD; answer complements it concisely.
        if risk is not None:
            if risk.status.value == "UNSAFE":
                flag_txt = "; ".join(f"{f.label}: {f.detail}" for f in risk.flags[:2]) if risk.flags else risk.headline
                wave_txt = ""
                if ocean is not None:
                    wh = f"{ocean.wave_height_m} m" if getattr(ocean, "wave_height_m", None) is not None else "—"
                    gs = f"{ocean.wind_gust_kmh} km/h" if getattr(ocean, "wind_gust_kmh", None) is not None else "—"
                    wave_txt = f"  \nWave: {wh} · Gusts: {gs}"
                parts.append(f"### 🔴 UNSAFE — Do not venture out\n**{flag_txt}.**{wave_txt}  \n{risk.headline}")
            elif risk.status.value == "CAUTION":
                wv = f"{ocean.wave_height_m} m" if ocean and getattr(ocean, "wave_height_m", None) is not None else "—"
                gs = f"{ocean.wind_gust_kmh} km/h" if ocean and getattr(ocean, "wind_gust_kmh", None) is not None else "—"
                parts.append(f"### 🟠 CAUTION — Borderline conditions\n**{risk.headline}**  \nWave: {wv} · Gusts: {gs}")
            else:
                wh = f"{ocean.wave_height_m} m" if ocean and getattr(ocean, "wave_height_m", None) is not None else "—"
                parts.append(f"### 🟢 SAFE — {risk.headline}  \nWave: {wh} · Wind moderate")
            for w in getattr(risk, "exceedance_windows", [])[:1]:
                parts.append(f"⏰ Conditions worsen {w.start_local}–{w.end_local} (peak {w.peak_value}{w.unit}).")
            for m in getattr(risk, "marine_bulletins", [])[:1]:
                parts.append(f"⚠️ {m}")
        # Ocean State — live marine weather (inserted before PFZ so weather queries are not empty)
        if ocean is not None:
            loc = getattr(ocean, "location", None)
            loc_name = getattr(loc, "name", "") if loc else ""
            # Prefer a short display name (Ratnagiri, Mumbai) over "Unknown Coast"
            short_name = loc_name.split(" (")[0].split(" Coast")[0].strip() if loc_name else "this location"
            tw = getattr(context, "time_window", None) or (state.get("plan", {}) or {}).get("time_window") or "today"
            tw_label = tw.replace("_", " ")
            fs = getattr(ocean, "field_sources", {}) or {}
            src_val = getattr(getattr(ocean, "source", None), "value", "") or "live"
            def _sim(field: str) -> str:
                # No simulated / derived labels ever reach the answer.
                return ""

            # Filter to fields that are truly available (not None/unavailable
            # placeholders). Unavailable fields are simply omitted (never shown
            # as a fabricated number); the footer still states the live source.
            def _have(field_key: str) -> bool:
                if str(fs.get(field_key, "")) == "unavailable":
                    return False
                return True

            marine_note = getattr(ocean, "marine_location_note", "") or ""
            header = f"### 🌊 Marine Conditions — {short_name} ({tw_label})"
            coord_line = ""
            if loc and getattr(loc, "lat", None) is not None:
                coord_line = f"📍 {loc.lat:.4f}°N, {loc.lon:.4f}°E"
            # Query-aware filtering: only show fields the user asked for
            raw_q = (getattr(context, "raw_query", "") or state.get("plan", {}).get("raw_query", "") or "").lower()
            def _wants(field: str) -> bool:
                if not raw_q:
                    return True
                sst_kw = any(k in raw_q for k in ("sst", "sea surface temp", "sea temp", "temperature"))
                wind_kw = any(k in raw_q for k in ("wind", "gust"))
                wave_kw = any(k in raw_q for k in ("wave", "swell", "surf"))
                curr_kw = any(k in raw_q for k in ("current", "currents"))
                chl_kw = any(k in raw_q for k in ("chlorophyll", "chl", "productivity"))
                tide_kw = any(k in raw_q for k in ("tide", "tidal"))
                specific = sst_kw or wind_kw or wave_kw or curr_kw or chl_kw or tide_kw
                if not specific:
                    return True
                mapping = {"sst_celsius": sst_kw, "wind_speed_kmh": wind_kw, "wind_gust_kmh": wind_kw,
                           "wave_height_m": wave_kw, "primary_swell_height_m": wave_kw,
                           "surface_current_mps": curr_kw, "chlorophyll_mg_m3": chl_kw, "tide_level_m": tide_kw, "tide_extremes": tide_kw}
                return mapping.get(field, False)
            detail: list[str] = []
            if _have("sst_celsius") and getattr(ocean, "sst_celsius", None) is not None and _wants("sst_celsius"):
                detail.append(f"| 🌡️ SST | **{ocean.sst_celsius}°C** |")
            w_dir = getattr(ocean, "wind_direction", None)
            if _have("wind_speed_kmh") and getattr(ocean, "wind_speed_kmh", None) is not None and _wants("wind_speed_kmh"):
                wdtxt = f" {w_dir}" if w_dir else ""
                detail.append(f"| 💨 Wind | **{ocean.wind_speed_kmh} km/h{wdtxt}** |")
            cur = getattr(ocean, "surface_current_mps", None)
            if _have("surface_current_mps") and cur is not None and _wants("surface_current_mps"):
                detail.append(f"| 🌊 Current | **{cur} m/s** |")
            swell_val = getattr(ocean, "primary_swell_height_m", None) if hasattr(ocean, "primary_swell_height_m") else getattr(ocean, "wave_height_m", None)
            if _have("primary_swell_height_m") and swell_val is not None and _wants("primary_swell_height_m"):
                detail.append(f"| 🌊 Swell | **{swell_val} m** |")
            elif _have("wave_height_m") and getattr(ocean, "wave_height_m", None) is not None and _wants("wave_height_m"):
                detail.append(f"| 🌊 Waves | **{ocean.wave_height_m} m** |")
            extremes = getattr(ocean, "tide_extremes", []) or []
            if extremes and _wants("tide_extremes"):
                tide_txt = ", ".join(f"{e.kind} at {e.time_local[11:16]} ({e.height_m} m)" for e in extremes[:4])
                detail.append(f"| 🌗 Tide | {tide_txt} |")
            elif _have("tide_level_m") and getattr(ocean, "tide_level_m", None) not in (None, 0.0) and _wants("tide_level_m"):
                detail.append(f"| 🌗 Tide | {ocean.tide_level_m} m |")
            if _have("chlorophyll_mg_m3") and getattr(ocean, "chlorophyll_mg_m3", None) is not None and _wants("chlorophyll_mg_m3"):
                detail.append(f"| 🟢 Chlorophyll | **{ocean.chlorophyll_mg_m3} mg/m³** |")

            debug_lines = getattr(ocean, "debug_incois", None) or {}
            _DEBUG = os.getenv("ORCA_DEBUG_INCOIS", "").strip().lower() in ("1", "true", "yes")
            if detail:
                table = "| Parameter | Value |\n|---|---|\n" + "\n".join(detail)
                block = header
                if coord_line:
                    block += f"  \n{coord_line}"
                block += f"\n\n{table}"
                parts.append(block)
                if marine_note:
                    parts.append(f"_{marine_note}_")
                if _DEBUG and debug_lines:
                    dbg = "\n".join(f"- {_k}: {debug_lines[_k]}" for _k in ("SST", "Wind", "Current", "Swell", "Chlorophyll") if _k in debug_lines)
                    parts.append(f"**Debug INCOIS**\n{dbg}")
                try:
                    from agents.response_agent import _source_line as _src_line
                    parts.append(_src_line(state.get("language", "en")))
                except Exception:
                    parts.append("*Source: Official INCOIS Ocean State Forecast + OceanSat-2 + Gemini PFZ*")
            else:
                # No live ocean fields — honest unavailability, never fabricated numbers
                unavailable_reason = getattr(ocean, "unavailable_reason", None) or ""
                _is_current_loc = bool(state.get("device_gps")) and not state.get("map_point")
                _hint = (
                    " If you are inland, select an offshore point on the map or "
                    "specify a coastal location for live marine data."
                    if _is_current_loc else ""
                )
                parts.append(
                    f"{header}: Live INCOIS value unavailable.{_hint}"
                    + (f" ({unavailable_reason})" if unavailable_reason else "")
                )
        # PFZ + Fleet Convergence
        if pfz is not None:
            # For a fishing-suitability question (safety_check/ocean_state with a
            # fishing intent) the PFZ ran only to feed the holistic AI summary
            # below — suppress the raw English "Nearest PFZ …/ZONE_A base…" lines
            # so the answer stays "only imp info + summary". A genuine fleet
            # RECOMMENDATION CHANGE is still surfaced (it materially changes advice).
            _plan = state.get("plan", {}) or {}
            _fish_suppress = bool(_plan.get("fishing_context")) and _plan.get("intent") in ("safety_check", "ocean_state")
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
                if _fish_suppress:
                    pass  # AI summary carries PFZ proximity for fishing queries
                elif fleet and fleet.get("status") == "UNAVAILABLE":
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

        # Context-aware summary (spec Parts 12-16): replace the old generic
        # recommendation string with ONE query-specific line generated from
        # the structured live data. This is what made every SST query end with
        # "Monitor the sea-surface temperature closely...". Fast + defensive:
        # on any LLM failure we simply omit it (the table above already stands
        # on its own), so no generic filler is ever repeated.
        try:
            summary = self._context_summary(state, risk=risk, ocean=ocean, pfz=pfz,
                                             geofence=geofence, route=route,
                                             trend=state.get("trend"))
            if summary:
                parts.append(summary)
        except Exception:
            pass

        answer = "\n\n".join(parts) if parts else (risk.headline if risk else "Assessment complete.")
        # Safety note if fleet tried to override unsafe
        if fleet and fleet.get("status") != "UNAVAILABLE" and risk and risk.status.value == "UNSAFE":
            answer += " Fleet optimization did not override safety — unsafe zones remain excluded."
        return answer[:1500]

    def _context_summary(self, state, risk=None, ocean=None, pfz=None,
                         geofence=None, route=None, trend=None):
        """Build structured dicts from live specialist findings and ask the
        ResponseAgent's LLM summary generator for ONE query-specific line
        (spec Parts 12-16). Returns None when the LLM is unavailable so the
        caller simply omits the paragraph — never a generic template."""
        from agents.response_agent import generate_context_summary
        context = state.get("context")
        plan = state.get("plan") or {}
        user_query = getattr(context, "raw_query", "") or state.get("raw_query", "")
        intent = plan.get("intent", "unknown")
        language = getattr(context, "language", None) or state.get("language", "en")
        d = self._summary_dicts(state, risk=risk, ocean=ocean, pfz=pfz,
                                geofence=geofence, route=route, trend=trend)
        return generate_context_summary(
            user_query=user_query, intent=intent,
            ocean_state=d["ocean"], pfz=d["pfz"], hazard=d["hazard"],
            geospatial=d["geospatial"], trend=d["trend"], language=language,
        )

    def _summary_dicts(self, state, risk=None, ocean=None, pfz=None,
                       geofence=None, route=None, trend=None) -> dict:
        """Flatten the live specialist findings into plain dicts of ONLY the
        fields that are actually available. Shared by the one-line context
        summary and the full narrative composer so both see identical data and
        neither can reference a field the pipeline never produced."""
        context = state.get("context")
        plan = state.get("plan") or {}

        ocean_d = None
        if ocean is not None:
            fs = getattr(ocean, "field_sources", {}) or {}
            def _v(field, attr):
                return getattr(ocean, attr, None) if str(fs.get(field, "")) != "unavailable" else None
            loc = getattr(ocean, "location", None)
            ocean_d = {
                "location": getattr(loc, "name", None) if loc else None,
                "time_window": getattr(context, "time_window", None) or plan.get("time_window"),
                "sst_celsius": _v("sst_celsius", "sst_celsius"),
                "wind_speed_kmh": _v("wind_speed_kmh", "wind_speed_kmh"),
                "wind_direction": getattr(ocean, "wind_direction", None),
                "wave_height_m": _v("wave_height_m", "wave_height_m"),
                "swell_height_m": _v("primary_swell_height_m", "primary_swell_height_m"),
                "surface_current_mps": _v("surface_current_mps", "surface_current_mps"),
                "chlorophyll_mg_m3": _v("chlorophyll_mg_m3", "chlorophyll_mg_m3"),
                "tide_level_m": _v("tide_level_m", "tide_level_m"),
            }
            ocean_d = {k: v for k, v in ocean_d.items() if v is not None}
        pfz_d = None
        if pfz is not None:
            lc = getattr(pfz, "landing_center", None) or {}
            pfz_d = {
                "distance_km": getattr(pfz, "distance_from_reference_km", None),
                "bearing_deg": getattr(pfz, "bearing_deg", None),
                "sst_at_zone_celsius": getattr(pfz, "sst_at_zone_celsius", None),
                "landing_centre": lc.get("name") if lc else None,
                "nearest_landmark": getattr(pfz, "nearest_landmark", None),
            }
            pfz_d = {k: v for k, v in pfz_d.items() if v is not None}
        hazard_d = None
        if risk is not None:
            hazard_d = {
                "verdict": getattr(getattr(risk, "status", None), "value", None),
                "headline": getattr(risk, "headline", None),
                "marine_bulletins": "; ".join(getattr(risk, "marine_bulletins", []) or [])[:200] or None,
            }
            hazard_d = {k: v for k, v in hazard_d.items() if v is not None}
        geo_d = None
        if geofence is not None:
            if getattr(geofence, "clear", True):
                geo_d = {"boundary_status": "clear of IMBL/MPA within buffer"}
            else:
                geo_d = {"boundary_flags": "; ".join(
                    f"{'inside ' if h.inside_zone else f'{h.distance_to_boundary_km} km from '}{h.zone_name}"
                    for h in getattr(geofence, "hits", [])[:2])}
        if route is not None:
            geo_d = geo_d or {}
            geo_d["route_km"] = getattr(route, "estimated_distance_km", None)
            geo_d["avoided"] = ", ".join(getattr(route, "avoided_zones", []) or []) or "nothing"
        trend_d = None
        if trend is not None:
            trend_d = {
                "window_months": getattr(trend, "window_months", None),
                "sst_trend_per_month": getattr(trend, "sst_trend_per_month", None),
                "chl_trend_per_month": getattr(trend, "chl_trend_per_month", None),
                "sst_chl_correlation": getattr(trend, "sst_chl_correlation", None),
            }
            trend_d = {k: v for k, v in trend_d.items() if v is not None}

        return {"ocean": ocean_d, "pfz": pfz_d, "hazard": hazard_d,
                "geospatial": geo_d, "trend": trend_d}

    def _narrative_answer(self, state, risk=None, ocean=None, pfz=None,
                          geofence=None, route=None, trend=None) -> str | None:
        """Compose the WHOLE answer as AI-written prose instead of the fixed
        heading/table scaffolding (see agents/narrative.py). Returns None on any
        failure so `_deterministic_answer` falls back to its template."""
        from agents import narrative as _narr
        if not _narr.is_enabled():
            return None
        context = state.get("context")
        plan = state.get("plan") or {}
        d = self._summary_dicts(state, risk=risk, ocean=ocean, pfz=pfz,
                                geofence=geofence, route=route, trend=trend)
        verdict = ((state.get("synthesis") or {}).get("verdict")
                   or getattr(getattr(risk, "status", None), "value", None))
        return _narr.compose_narrative(
            user_query=getattr(context, "raw_query", "") or state.get("raw_query", ""),
            intent=plan.get("intent", "unknown"),
            language=getattr(context, "language", None) or state.get("language", "en"),
            verdict=verdict,
            ocean=d["ocean"], pfz=d["pfz"], hazard=d["hazard"],
            geospatial=d["geospatial"], trend=d["trend"],
            fishing_context=bool(plan.get("fishing_context")),
        )

    def _node_unsupported(self, state: ORCAGraphState) -> dict:
        plan = state.get("plan") or {}
        # Handle degraded non-English + LLM outage case with honest localized message
        if plan.get("degraded"):
            lang = plan.get("degraded_language") or state.get("language", "en")
            degraded_msg = plan.get("degraded_message") or _degraded_message_for(lang)
            trace = AgentTrace(
                agent_name="Orchestrator",
                action=f"Degraded mode response for non-English query (lang={lang}, LLM unavailable)",
                result_summary=f"Returned honest limited-mode message in '{lang}' instead of attempting regex on untranslated text.",
                data_sources=[],
                duration_ms=0.0,
            )
            return {
                "response": OrchestratorResponse(
                    answer=degraded_msg,
                    status=SafetyStatus.CAUTION,
                    reasoning=[f"LLM unavailable — could not translate query from '{lang}'. Service is in limited mode."],
                    evidence_sources=[],
                    trace=list(state.get("traces") or []) + [trace],
                    language=lang,
                    routing={"intent": "unknown", "agents": [], "routing_mode": "degraded", "complexity": "fast", "reason": plan.get("why",""), "confidence": 0.0},
                ),
                "traces": [trace],
            }
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
        # CRITICAL CORRECTNESS GAP FIX: non-English query + full LLM outage.
        # LanguageAgent falls back to script detection (correctly identifies language)
        # but does NOT translate — normalized_query stays in original language.
        # English-only regex in auto_router / _plan would produce zero hits and
        # silently yield a wrong/empty plan. Detect this explicitly and short-
        # circuit to a clear honest degraded-mode response in the detected language.
        lang = state.get("language", "en")
        lang_mode = state.get("language_mode", "")
        # Determine if translation could not be performed
        translation_missing = False
        if lang != "en":
            if lang_mode == "rules":
                translation_missing = True
            elif _contains_indic_script(normalized_query) or normalized_query.strip() == raw_query.strip():
                translation_missing = True
            elif not llm_client.is_available():
                translation_missing = True
        # Romanized extension
        is_romanized = _contains_romanized_regional_language(raw_query) or _contains_romanized_regional_language(normalized_query)
        if lang == "en" and is_romanized and not llm_client.is_available():
            detected = _detect_romanized_language(raw_query) or _detect_romanized_language(normalized_query) or "hi"
            lang = detected
            translation_missing = True
        if lang != "en" and translation_missing:
            degraded_msg = _degraded_message_for(lang)
            plan = {
                "intent": "unknown",
                "location_name": "unknown",
                "time_window": "today",
                "target_hour": None,
                "months_back": None,
                "agents_needed": [],
                "why": f"[degraded] LLM unavailable — non-English query in '{lang}' could not be translated. Returning honest limited-mode message.",
                "duration_ms": 0.0,
                "routing_mode": "degraded",
                "complexity": "fast",
                "confidence": 0.0,
                "degraded": True,
                "degraded_language": lang,
                "degraded_message": degraded_msg,
            }
            plan_mode = "degraded"
            location = DEFAULT_LOCATION
            context = QueryContext(
                raw_query=raw_query,
                location=location,
                time_window=plan["time_window"],
                session_id=state["session_id"],
                language=lang,
                device_gps=state.get("device_gps"),
                destination=state.get("destination"),
                target_hour=None,
                vessel_class=state.get("vessel_class") or "small_fishing_boat",
            )
            # Still persist language for next turn (but not a bogus location)
            try:
                session_store.upsert(
                    state["session_id"],
                    location_name="",
                    lat=location.lat, lon=location.lon,
                    time_window=plan["time_window"],
                    language=lang,
                    last_intent=plan["intent"],
                    last_query=raw_query,
                )
            except Exception:
                pass
            trace = AgentTrace(
                agent_name="PlanningAgent",
                action=f"Degraded mode — non-English query '{lang}' with LLM unavailable [routing=degraded]",
                result_summary=f"Service is in limited mode; translation unavailable. Returned localized degraded message for '{lang}'.",
                data_sources=[],
                duration_ms=0.0,
            )
            return plan, plan_mode, location, context, trace

        prior = session_store.get(state["session_id"])
        plan, plan_mode = self._plan(normalized_query, prior=prior)
        self._log_routing(state, plan)

        device_gps = state.get("device_gps") or (
            tuple(prior.device_gps) if (prior and prior.device_gps) else None
        )
        map_point = state.get("map_point") or (
            tuple(getattr(prior, "map_point", None)) if (prior and getattr(prior, "map_point", None)) else None
        )
        destination = state.get("destination") or (
            Location(**prior.destination) if (prior and prior.destination) else None
        )

        # Live Device GPS resolution (P0): if query asks about current location or names no specific town,
        # and device_gps is available, bind to the user's live position directly and reverse-geocode it.
        loc_name = str(plan.get("location_name") or "").strip().lower()
        # Word-boundary-aware detection so "here" doesn't fire inside "where"/"somewhere"
        import re as _re_fix
        _my_location_phrases = (
            "where am i", "my location", "my position", "current position",
            "here", "around me", "where i am", "near me", "nearby",
        )
        _q_lower = normalized_query.lower()
        is_my_location_query = any(
            _re_fix.search(r'\b' + _re_fix.escape(k) + r'\b', _q_lower) for k in _my_location_phrases
        )
        # Intent router (Part 9): an explicit relative_location=near_me is an
        # authoritative "use my position" signal even if the phrase heuristic
        # above missed the exact wording (e.g. romanised "mere paas").
        if str(plan.get("router_relative_location") or "") == "near_me":
            is_my_location_query = True

        _glog = logging.getLogger("orca.orchestrator")

        # Typed coordinates (Part 8): the intent router extracted a lat/lon from
        # the query text. Treat them like a map tap — bind the location directly,
        # never snap — but they yield to an explicit map_point selection below.
        router_coords = plan.get("router_coordinates") or None
        _router_bound_coords = False
        if router_coords and map_point is None:
            try:
                rc_lat, rc_lon = float(router_coords["lat"]), float(router_coords["lon"])
                _glog.info("Typed coordinate selected (intent router): %.4f,%.4f", rc_lat, rc_lon)
                location = Location(
                    name=f"Selected Location ({rc_lat:.4f}°N, {rc_lon:.4f}°E)",
                    lat=rc_lat, lon=rc_lon,
                )
                plan["location_name"] = location.name
                device_gps = (rc_lat, rc_lon)
                _router_bound_coords = True
            except (KeyError, TypeError, ValueError):
                pass


        # Map-tap selection (Part A2 — highest priority): the user explicitly
        # tapped a coastal/offshore point. Used directly, never snapped, and it
        # wins over GPS / typed / PFZ coordinates.
        if map_point is not None and len(map_point) >= 2:
            mp_lat, mp_lon = float(map_point[0]), float(map_point[1])
            _glog.info("Map tap coordinate selected: %.4f,%.4f", mp_lat, mp_lon)
            location = Location(
                name=f"Selected Location ({mp_lat:.4f}°N, {mp_lon:.4f}°E)",
                lat=mp_lat, lon=mp_lon,
            )
            plan["location_name"] = location.name
            # Propagate to device_gps so every downstream consumer (Geospatial,
            # PFZ reference, ocean) resolvs against the selected point.
            device_gps = (mp_lat, mp_lon)

        if device_gps:
            _glog.info(
                "GPS acquired: %.4f,%.4f | Using GPS coordinates%s",
                device_gps[0], device_gps[1],
                f" for '{loc_name or 'current position'}'" if is_my_location_query else "",
            )
        else:
            _glog.info("GPS unavailable — falling back to selected location")

        # Handle "same" from LLM — inherit prior location before any other logic
        if loc_name in ("same",) and prior is not None and prior.location_name:
            plan["location_name"] = prior.location_name
            loc_name = prior.location_name.lower()

        if map_point is not None and len(map_point) >= 2:
            pass  # location already bound above (highest priority)
        elif _router_bound_coords:
            pass  # typed coordinates already bound above (Part 8) — do not re-resolve
        else:
            # Structural safeguard: if a named place was extracted and resolves to a real
            # location, it always wins over the my-location heuristic. Only when
            # location_name is empty/unknown do we allow the heuristic to force GPS.
            _loc_is_empty = loc_name in ("", "unknown", "same", "here", "there", "current", "my location", "where am i")
            _resolved_named = None
            if not _loc_is_empty:
                try:
                    _resolved_named = resolve_location(plan.get("location_name"))
                except Exception:
                    _resolved_named = None
                if _resolved_named is not None and is_my_location_query and device_gps:
                    _glog.info(
                        "Named location '%s' resolved to %.4f,%.4f — ignoring my-location heuristic (is_my_location_query=True) for query '%s'",
                        plan.get("location_name"), _resolved_named.lat, _resolved_named.lon, normalized_query,
                    )
            if _resolved_named is not None:
                location = _resolved_named
                plan["location_name"] = location.name
            elif (_loc_is_empty or is_my_location_query) and device_gps:
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
            if location is None:
                if device_gps:
                    try:
                        import data_connectors.geocode as geocode
                        resolved_name = geocode.reverse_geocode(device_gps[0], device_gps[1])
                        location = Location(name=f"Current Position ({resolved_name})", lat=device_gps[0], lon=device_gps[1])
                        plan["location_name"] = location.name
                        _glog.info("Geocode failed for '%s' — falling back to GPS %.4f,%.4f", plan.get("location_name"), device_gps[0], device_gps[1])
                    except Exception:
                        location = Location(name=f"Current Position ({device_gps[0]:.3f}°N, {device_gps[1]:.3f}°E)", lat=device_gps[0], lon=device_gps[1])
                        plan["location_name"] = location.name
                else:
                    ask_msg = "I couldn't determine your location. Please enable GPS or tell me a coastal location such as Ratnagiri, Veraval, Kochi, or coordinates."
                    _glog.warning("Location unresolved — asking user for location")
                    plan["needs_location"] = True
                    plan["ask_message"] = ask_msg
                    location = Location(name="ASK_LOCATION", lat=0, lon=0)

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

        # Fishing-suitability detection: a "can I go fishing here?" question is a
        # safety_check whose answer must also weigh PROXIMITY TO A PFZ, not just
        # wind/SST/waves. Flag it so _selected_specialists also runs the PFZ agent
        # and the narrative composer gives a holistic go/no-go. Vocabulary is
        # shared with the Response Agent (agents/narrative.py) so both paths agree.
        try:
            from agents.narrative import is_fishing_query as _is_fishing
            plan["fishing_context"] = _is_fishing(raw_query, normalized_query)
        except Exception:
            plan["fishing_context"] = False

        # Persist the turn for the next follow-up.
        # Always store the resolved location's name (not the raw plan's "same"/"unknown")
        # so the next turn's prior.location_name is actually useful.
        resolved_name = location.name if location and location.name not in ("ASK_LOCATION",) else ""
        if resolved_name in ("", "unknown", "same") and prior is not None and prior.location_name:
            resolved_name = prior.location_name
        session_store.upsert(
            state["session_id"],
            location_name=resolved_name,
            lat=location.lat, lon=location.lon,
            time_window=plan["time_window"],
            target_hour=plan.get("target_hour"),
            language=state.get("language", "en"),
            device_gps=list(device_gps) if device_gps else None,
            map_point=list(map_point) if map_point else None,
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
        unavailable_tag = "unavailable"
        tide_tag = "tide_gauge_model"
        liveish = [s for s in sources if s and s not in (sim_tagged, unavailable_tag, tide_tag)]
        live_fraction = (len(liveish) / len(sources)) if sources else 0.0

        verdict_conf = (
            risk.confidence if risk is not None and risk.confidence is not None
            else (ocean.confidence if ocean is not None else 0.5)
        )
        agreement = 1.0 if not conflicts else 0.5
        score = round(min(1.0, 0.55 * live_fraction + 0.30 * float(verdict_conf)
                          + 0.15 * agreement), 2)
        # Innovation #4: a HIGH satellite-vs-forecast wind divergence flags
        # the forecast as less trustworthy — reduce confidence, never claim
        # the satellite disproves the forecast or touch the safety verdict.
        wind_div = state.get("wind_divergence") or {}
        penalty = float(wind_div.get("confidence_penalty") or 0.0)
        if penalty:
            score = round(max(0.0, score - penalty), 2)
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
        wind_div = state.get("wind_divergence")
        if wind_div and wind_div.get("status") == "HIGH_DIVERGENCE":
            reasoning.append(
                f"Wind validation: forecast {wind_div.get('forecast_wind_kn')}kn vs "
                f"satellite {wind_div.get('satellite_wind_kn')}kn — {wind_div.get('warning')}"
            )

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
            wind_divergence=wind_div,
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
        # Preserve orchestrator mode — language result's "mode" is language_mode (fast-path/llm/rules)
        state["language"] = lang_result.get("language", "en")
        state["normalized_query"] = lang_result.get("normalized_query", state["raw_query"])
        state["language_mode"] = lang_result.get("mode", "unknown")
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

        # Wind Divergence (Innovation #4) — cheap/instant, never blocks
        wind_dict, wind_trace = self._compute_wind_divergence(state)
        state["wind_divergence"] = wind_dict
        trace.append(wind_trace)
        timings["wind_divergence_ms"] = round(wind_trace.duration_ms, 1)

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

        # Safety floor — Task 8: deterministic pass after synthesis, before response. Only raises.
        t_floor0 = time.perf_counter()
        try:
            import safety_floor
            new_synthesis = safety_floor.apply_safety_floor(synthesis, state.get("risk"))
            new_risk = safety_floor.enforce_risk_floor(state.get("risk"))
            if new_synthesis is not synthesis or new_synthesis.get("verdict") != synthesis.get("verdict") or new_risk is not state.get("risk"):
                # Floor triggered
                synthesis = new_synthesis
                state["synthesis"] = synthesis
                if new_risk is not state.get("risk"):
                    state["risk"] = new_risk
                t_floor = AgentTrace(
                    agent_name="SafetyFloor",
                    action="Applied safety floor — raised verdict to EXTREME due to severe IMD warning",
                    result_summary=f"Synthesis verdict '{synthesis.get('verdict')}' after floor (severe warning active)",
                    data_sources=list(new_risk.evidence_sources) if new_risk else [],
                    duration_ms=(time.perf_counter() - t_floor0) * 1000,
                )
                timings["safety_floor_ms"] = round(t_floor.duration_ms, 1)
                trace.append(t_floor)
            else:
                t_floor = AgentTrace(
                    agent_name="SafetyFloor",
                    action="Safety floor check — no severe warning, verdict unchanged",
                    result_summary=f"Verdict '{synthesis.get('verdict')}' remains",
                    data_sources=[],
                    duration_ms=(time.perf_counter() - t_floor0) * 1000,
                )
                timings["safety_floor_ms"] = round(t_floor.duration_ms, 1)
                trace.append(t_floor)
        except Exception as exc:
            import logging
            logging.getLogger("orca.orchestrator").warning("safety floor failed: %s", exc)
            t_floor = AgentTrace(agent_name="SafetyFloor", action="Safety floor check failed", result_summary=str(exc)[:200], data_sources=[], duration_ms=(time.perf_counter() - t_floor0)*1000)
            timings["safety_floor_ms"] = round(t_floor.duration_ms, 1)
            trace.append(t_floor)

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
        # Safety clamp (existing, keeps UNSAFE from being overridden) — floor already raised to EXTREME if needed
        risk = state.get("risk")
        if risk is not None and risk.status.value in ("UNSAFE", "EXTREME", "CRITICAL") and response.status.value not in ("UNSAFE", "EXTREME", "CRITICAL"):
            response.status = risk.status
        # Record fleet activity for future convergence (real only)
        try:
            self._record_fleet_activity(state, response)
        except:
            pass
        # Gap 2 — persist verdict/findings for next follow-up
        try:
            self._persist_conversation_findings(state.get("session_id") or initial.get("session_id") or "", response, state.get("plan") or {})
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
        state["language"] = lang_result.get("language", "en")
        state["normalized_query"] = lang_result.get("normalized_query", state["raw_query"])
        state["language_mode"] = lang_result.get("mode", "unknown")
        trace.append(t)

        plan, plan_mode, location, context, t = self._step_plan(
            state["normalized_query"], state["raw_query"], state
        )
        state.update({"plan": plan, "location": location, "context": context})
        trace.append(t)
        # Handle degraded non-English + LLM outage for direct mode as well
        if plan.get("degraded"):
            unsupported = self._node_unsupported(state)["response"]
            unsupported.trace = trace + unsupported.trace
            unsupported.mode = "agent"
            unsupported.answered_by = f"{spec['name']} (direct -- degraded mode)"
            return unsupported

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
        # Safety floor for direct mode
        try:
            import safety_floor
            new_synth = safety_floor.apply_safety_floor(synthesis, state.get("risk"))
            new_risk = safety_floor.enforce_risk_floor(state.get("risk"))
            if new_synth is not synthesis or new_synth.get("verdict") != synthesis.get("verdict"):
                synthesis = new_synth
                state["synthesis"] = synthesis
                if new_risk is not state.get("risk"):
                    state["risk"] = new_risk
                trace.append(AgentTrace(agent_name="SafetyFloor", action="Applied safety floor — raised verdict to EXTREME", result_summary=f"Verdict -> {new_synth.get('verdict')}", data_sources=[], duration_ms=0.1))
            else:
                trace.append(AgentTrace(agent_name="SafetyFloor", action="Safety floor check — no severe warning", result_summary=f"Verdict '{synthesis.get('verdict')}' remains", data_sources=[], duration_ms=0.1))
        except Exception:
            pass

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
        try:
            # Agent mode: discussion never, synthesis always (LLM)
            st = {"routing_mode": plan.get("routing_mode","rules"), "complexity": plan.get("complexity","fast"), "mode": "agent", "traces": trace, "timings": {}}
            self._record_telemetry(st, response, 0)
        except:
            pass
        try:
            self._persist_conversation_findings(state.get("session_id") or "", response, plan)
        except:
            pass
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

        # 0. LLM Intent Router (new routing brain) — replaces keyword routing as
        # the PRIMARY intent stage while leaving the plan builder, LangGraph
        # dispatcher and every agent unchanged. It emits an ORCA-native plan
        # dict, so nothing downstream needs to know it exists. Disabled with
        # ORCA_INTENT_ROUTER=off (falls straight through to the legacy path).
        try:
            from orchestrator import intent_router
        except Exception:
            intent_router = None  # type: ignore
        if intent_router is not None and intent_router.ROUTER_MODE != "off":
            try:
                decision = intent_router.route_intent(normalized_query, conversation_history=prior)
            except Exception:
                decision = None
            if decision is not None and decision.orca_intent != "unknown":
                _loc = decision.location_name
                if (not _loc or _loc.lower() in ("same", "unknown")) and prior is not None and prior.location_name:
                    _loc = prior.location_name
                complexity = "fast"
                if decision.orca_intent == Intent.TREND_ANALYSIS:
                    complexity = "deep"
                elif decision.is_compound or len(decision.agents) >= 4:
                    complexity = "complex"
                elif len(decision.agents) >= 2:
                    complexity = "standard"
                # Honour the router's explicit agent selection: if it picked
                # agents outside this intent's default set (e.g. PFZ+Geospatial
                # for "navigate to nearest PFZ"), flag compound so
                # _selected_specialists uses the union directly instead of
                # intersecting it away.
                _defaults = set(INTENT_DEFAULT_AGENTS.get(decision.orca_intent, []))
                _use_union = decision.is_compound or (
                    bool(decision.agents) and not set(decision.agents).issubset(_defaults)
                )
                plan = {
                    "intent": decision.orca_intent,
                    "location_name": _loc or "unknown",
                    "time_window": decision.time_window,
                    "target_hour": decision.target_hour,
                    "months_back": decision.months_back
                        or (6 if decision.orca_intent == Intent.TREND_ANALYSIS else None),
                    "agents_needed": list(decision.agents),
                    "why": f"[intent-router:{decision.router_mode}] {decision.reason}".strip(),
                    "duration_ms": (time.perf_counter() - start) * 1000,
                    "routing_mode": "intent-router",
                    "complexity": complexity,
                    "confidence": decision.confidence,
                    "is_compound": _use_union,
                    "compound_intents": decision.compound_intents,
                    # Router-extracted parameters (Part 8/9) consumed by _step_plan.
                    "router_coordinates": (
                        {"lat": decision.coordinates[0], "lon": decision.coordinates[1]}
                        if decision.coordinates else None
                    ),
                    "router_relative_location": decision.relative_location,
                    "router_intent": decision.intent,
                    "vessel_class": decision.vessel_class,
                }
                return plan, "intent-router"

        # 1. Try fast deterministic router FIRST

        fast_decision = None
        if _AUTO_ROUTER_AVAILABLE and auto_router is not None:
            try:
                fast_decision = auto_router.fast_route(normalized_query)
            except Exception:
                fast_decision = None

        # Gap 1 — lightweight pronoun follow-up heuristic for the fast path:
        # If the query is short and pronoun-heavy ("why though?", "is it safe now?",
        # "what about the wind?") and we have prior context, force the LLM path
        # where memory_line can resolve "that"/"it"/"why" — don't let fast-router
        # guess with zero context.
        if_prior_followup = False
        if prior is not None and (prior.last_query or prior.location_name):
            _q_low = normalized_query.lower().strip()
            # Short + contains a follow-up pronoun / anaphor
            _pronouns = ("why", "that", "it", "this", "is it", "is that", "what about", "how about", "and the", "still")
            if len(_q_low.split()) <= 8 and any(p in _q_low for p in _pronouns):
                if_prior_followup = True

        # If it's a follow-up and fast-router is not high-confidence, use LLM
        if if_prior_followup and fast_decision is not None and fast_decision.confidence < 0.92:
            fast_decision = None  # force fallback to LLM where memory_line lives

        if fast_decision is not None and not auto_router.should_use_llm_fallback(fast_decision, normalized_query):  # type: ignore
            # Confident fast routing — no LLM needed (0-1 LLM calls saved)
            _raw_loc = self._extract_place_name(normalized_query)
            # Handle "same" immediately — inherit prior location before plan is built
            if _raw_loc in ("same", "unknown", "") and prior is not None and prior.location_name:
                # For follow-ups like "what about the wind?" with no place name,
                # inherit the prior location; for explicit "same" also inherit.
                _raw_loc = prior.location_name
            plan = {
                "intent": fast_decision.intent,
                "location_name": _raw_loc,
                "time_window": self._extract_time_window(normalized_query),
                "target_hour": self._extract_target_hour(normalized_query),
                "months_back": 6 if fast_decision.intent == Intent.TREND_ANALYSIS else None,
                "agents_needed": fast_decision.agents,
                "why": f"[fast-rules] {fast_decision.reason}",
                "duration_ms": (time.perf_counter() - start) * 1000,
                "routing_mode": fast_decision.routing_mode,
                "complexity": fast_decision.complexity,
                "confidence": fast_decision.confidence,
                "is_compound": getattr(fast_decision, "is_compound", False),
                "compound_intents": getattr(fast_decision, "compound_intents", None),
            }
            # Memory override for "same place" — copy prior location (redundant with above, but keep for safety)
            if prior is not None and prior.location_name and plan["location_name"] in ("unknown", "", "same"):
                plan["location_name"] = prior.location_name
                plan["why"] += " (location inherited from conversation memory)"
            # Gap 2 — even on fast path, inherit prior intent when the follow-up
            # is pronoun-heavy and the fast router guessed "unknown" with low signal.
            # This keeps "why is that?" anchored to the previous intent.
            if if_prior_followup and plan["intent"] == "unknown" and prior is not None and prior.last_intent and prior.last_intent != "unknown":
                plan["intent"] = prior.last_intent
                # Also inherit agents from the prior intent's default set
                from orchestrator.state import INTENT_DEFAULT_AGENTS as _IDA
                plan["agents_needed"] = _IDA.get(prior.last_intent, plan["agents_needed"])
                plan["why"] += f" (intent inherited from prior '{prior.last_intent}' for follow-up)"
            return plan, "fast-rules"

        # 2. Fallback: LLM planner (only when fast router uncertain or unavailable)
        if llm_client.is_available():
            try:
                memory_line = ""
                if prior is not None and (prior.location_name or prior.last_query):
                    # Gap 1 + 2: include last query/intent and last verdict/evidence so
                    # follow-ups like "why is that?", "what about the wind?", "is it
                    # still the case?" can be resolved without repeating location/time.
                    q_part = f"'{prior.last_query}'" if prior.last_query else "—"
                    intent_part = f" (intent: {prior.last_intent})" if prior.last_intent else ""
                    loc_part = f"'{prior.location_name}'" if prior.location_name else "unknown location"
                    time_part = f"'{prior.time_window}'" if prior.time_window else "'today'"
                    memory_line = (
                        f"\nCONVERSATION MEMORY: previous turn was {q_part}{intent_part} about "
                        f"{loc_part} at {time_part}."
                    )
                    if prior.last_verdict:
                        memory_line += f" Verdict was '{prior.last_verdict}'."
                    if prior.last_evidence:
                        # Keep it short — first evidence line is enough for "why?"
                        ev = prior.last_evidence[:220]
                        memory_line += f" Key evidence: '{ev}'."
                    memory_line += (
                        " If this turn is a follow-up referring to 'that', 'it', 'why', "
                        "or asking about one specific field from the same location/time "
                        "without repeating it, resolve accordingly."
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
                # Handle "same" from LLM — inherit prior location
                if plan.get("location_name") in ("same", "unknown", "") and prior is not None and prior.location_name:
                    plan["location_name"] = prior.location_name
                    plan["why"] = plan.get("why", "") + " (location inherited from conversation memory)"
                return plan, "llm-planner"
            except llm_client.LLMUnavailableError:
                pass  # fall through to rule-based planning

        # 3. Deterministic rule fallback (no LLM)
        # If fast router gave a low-confidence hint, reuse its intent to avoid re-parsing
        fallback_intent = (fast_decision.intent if fast_decision is not None else self._route_intent(normalized_query))
        # Derive agents from the intent table so the rule path selects the right
        # specialist (e.g. OceanStateAgent for weather) even when fast routing
        # returned none — never fall through to PFZ for a conditions query.
        fallback_agents = INTENT_DEFAULT_AGENTS.get(fallback_intent) or []
        if not fallback_agents and fast_decision is not None:
            fallback_agents = list(fast_decision.agents or [])
        _raw_loc2 = self._extract_place_name(normalized_query)
        if _raw_loc2 in ("same", "unknown", "") and prior is not None and prior.location_name:
            _raw_loc2 = prior.location_name
        plan = {
            "intent": fallback_intent,
            "location_name": _raw_loc2,
            "time_window": self._extract_time_window(normalized_query),
            "target_hour": self._extract_target_hour(normalized_query),
            "months_back": 6 if "trend" in normalized_query.lower() or
                            "declined" in normalized_query.lower() else None,
            "agents_needed": fallback_agents,
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
        # Ocean/weather state questions route to OceanStateAgent BEFORE the
        # PFZ check so pure sea-conditions queries never fall through to PFZ.
        OCEAN_STATE_KEYWORDS = (
            "weather", "forecast", "marine weather", "ocean state", "sea condition",
            "wind", "wind speed", "wind gust", "waves", "wave", "wave height",
            "swell", "sst", "sea surface temperature", "chlorophyll", "tide",
            "high tide", "low tide", "current", "currents",
        )
        if any(kw in q for kw in OCEAN_STATE_KEYWORDS):
            if any(kw in q for kw in ["fishing zone", "fish zone", "pfz",
                                      "where to fish", "where should i fish"]):
                return Intent.PFZ_LOOKUP
            return Intent.OCEAN_STATE
        if any(kw in q for kw in ["fishing zone", "fish zone", "pfz", "where to fish"]):
            return Intent.PFZ_LOOKUP
        if any(kw in q for kw in ["route", "navigate", "safest path", "how do i get"]):
            return Intent.ROUTE_PLAN
        if any(kw in q for kw in ["boundary", "border", "restricted", "geofence", "imbl", "eez", "mpa"]):
            return Intent.GEOFENCE_CHECK
        if any(kw in q for kw in ["alert", "cyclone", "cyclone warning", "lightning"]):
            return Intent.HAZARD_ALERTS
        if any(kw in q for kw in ["safe", "safety", "go fishing", "venture", "risky", "danger"]):
            return Intent.SAFETY_CHECK
        return Intent.UNKNOWN

    def _extract_time_window(self, query: str) -> str:
        q = query.lower()
        if "tomorrow" in q:
            return "tomorrow_morning" if "morning" in q else "tomorrow"
        return "today"
