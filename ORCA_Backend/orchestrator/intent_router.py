"""
LLM Intent Router -- ORCA's routing brain (replaces keyword-tuple routing).

This module owns ONE stage of the pipeline: turning a raw user query into an
`IntentDecision`. Everything downstream is untouched:

    User Query
        |
    LLM Intent Router      <-- this module
        |
    IntentDecision
        |
    Existing Plan Builder  (Orchestrator._step_plan)
        |
    Existing LangGraph Dispatcher (Orchestrator._node_dispatch)
        |
    Specialist Agents -> ResponseAgent -> Frontend

Why an LLM instead of keyword tuples: the old `_route_intent()` /
`auto_router.INTENT_KEYWORDS` approach matches *vocabulary*, not *intent*, so
it fails on Hinglish ("Kal Goa ke paas machhli pakadne jana safe rahega?"),
paraphrase ("How warm is the sea?"), bare coordinates ("18.9680,72.5148
wind?") and combined asks ("Nearest PFZ and navigate me there").

Reliability model (never blindly trust the LLM):
    confidence > 0.85   -> LLM decision used as-is
    0.50 - 0.85         -> merged with the deterministic router
    < 0.50 / no LLM     -> deterministic router decides

Regex is kept for exactly three things, because they are lexical, not
semantic: coordinates, dates/time windows and vessel class. There are no
intent keyword tuples in this module.

Latency: a single forced-tool-call completion, `attempts=1`, tight timeout,
plus an in-process TTL cache so repeat/echo queries cost ~0 ms. Set
ORCA_INTENT_ROUTER=fast-first to only pay for the LLM when the deterministic
router is uncertain, or ORCA_INTENT_ROUTER=off to restore legacy routing.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import llm_client

log = logging.getLogger("orca.intent_router")

# --------------------------------------------------------------------------
# Configuration (all env-overridable, safe defaults)
# --------------------------------------------------------------------------
# llm        : LLM router runs first on every query (spec default)
# fast-first : deterministic router first, LLM only when it is uncertain
# off        : router disabled -- caller keeps legacy behaviour
ROUTER_MODE = (os.getenv("ORCA_INTENT_ROUTER", "llm").strip().lower() or "llm")
ROUTER_TIMEOUT_S = float(os.getenv("ORCA_INTENT_ROUTER_TIMEOUT_S", "3.0").strip() or 3.0)
ROUTER_MAX_TOKENS = int(os.getenv("ORCA_INTENT_ROUTER_MAX_TOKENS", "700").strip() or 700)
ROUTER_CACHE_TTL_S = int(os.getenv("ORCA_INTENT_ROUTER_CACHE_TTL_S", "300").strip() or 300)
ROUTER_CACHE_MAX = int(os.getenv("ORCA_INTENT_ROUTER_CACHE_MAX", "256").strip() or 256)

CONF_HIGH = 0.85
CONF_LOW = 0.50

# --------------------------------------------------------------------------
# Taxonomy
# --------------------------------------------------------------------------
# Router-level intents (Part 5 of the spec) -- what the LLM classifies into.
ROUTER_INTENTS = ("pfz", "ocean_state", "hazard", "geospatial", "trend", "sar", "general", "tourism")

# ORCA's existing orchestrator intents. The router ALSO emits one of these so
# the existing plan builder / dispatcher / INTENT_DEFAULT_AGENTS table keeps
# working byte-for-byte. No downstream contract changes.
ORCA_INTENTS = (
    "safety_check", "ocean_state", "pfz_lookup", "route_plan",
    "geofence_check", "hazard_alerts", "trend_analysis", "zone_scan", "poi_lookup", "unknown",
)

DISPATCHABLE_AGENTS = (
    "OceanStateAgent", "HazardAgent", "PFZAgent", "GeospatialAgent", "TrendAgent", "TourismAgent",
)

# Deterministic repair table: router intent -> (orca intent, agents).
# Used when the LLM omits orca_intent/agents or returns something unusable.
# NOTE on `sar`: the LangGraph graph has no SAR node (SARAgent is reached via
# the /sar/* authority endpoints). A distress query is therefore executed as a
# safety_check -- sea state + hazards + boundary around the last known point,
# which is what a search actually needs -- while IntentDecision.intent stays
# "sar" so the response layer can lead with emergency actions.
ROUTER_TO_ORCA: dict[str, tuple[str, list[str]]] = {
    "pfz": ("pfz_lookup", ["PFZAgent", "OceanStateAgent", "GeospatialAgent"]),
    "ocean_state": ("ocean_state", ["OceanStateAgent"]),
    "hazard": ("hazard_alerts", ["HazardAgent", "OceanStateAgent"]),
    "geospatial": ("geofence_check", ["GeospatialAgent"]),
    "trend": ("trend_analysis", ["TrendAgent"]),
    "sar": ("safety_check", ["OceanStateAgent", "HazardAgent", "GeospatialAgent"]),
    "general": ("unknown", []),
    "tourism": ("poi_lookup", ["TourismAgent", "GeospatialAgent"]),
}

# Reverse view: given an ORCA intent, which router intent describes it. Used
# when the deterministic fallback produces an ORCA intent and we need to fill
# IntentDecision.intent.
ORCA_TO_ROUTER: dict[str, str] = {
    "safety_check": "hazard",
    "ocean_state": "ocean_state",
    "pfz_lookup": "pfz",
    "route_plan": "geospatial",
    "geofence_check": "geospatial",
    "hazard_alerts": "hazard",
    "trend_analysis": "trend",
    "zone_scan": "pfz",
    "poi_lookup": "tourism",
    "unknown": "general",
}

KNOWN_TIME_WINDOWS = ("today", "tomorrow", "tomorrow_morning")


# --------------------------------------------------------------------------
# IntentDecision
# --------------------------------------------------------------------------
@dataclass
class IntentDecision:
    """One routing decision. The first nine fields are the public contract
    described in the spec; the rest are bridge fields the existing plan
    builder already expects (they all have defaults, so nothing downstream
    is forced to know about them)."""

    intent: str                                  # ROUTER_INTENTS
    agents: list                                 # DISPATCHABLE_AGENTS subset
    confidence: float                            # 0.0 - 1.0
    location_name: Optional[str] = None           # free text, or None
    coordinates: Optional[tuple] = None           # (lat, lon) or None
    relative_location: Optional[str] = None       # "near_me" or None
    time_window: str = "today"                    # KNOWN_TIME_WINDOWS
    vessel_class: Optional[str] = None             # small_fishing_boat | ...
    reason: str = ""

    # --- bridge fields (existing pipeline) ---
    orca_intent: str = "unknown"                  # ORCA_INTENTS
    router_mode: str = "rules"                    # llm | llm+rules | rules | cache | disabled
    target_hour: Optional[int] = None
    months_back: Optional[int] = None
    is_compound: bool = False
    compound_intents: Optional[list] = None
    latency_ms: float = 0.0
    llm_confidence: Optional[float] = None        # pre-merge LLM confidence

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "agents": list(self.agents or []),
            "confidence": round(float(self.confidence), 3),
            "location_name": self.location_name,
            "coordinates": (
                {"lat": self.coordinates[0], "lon": self.coordinates[1]}
                if self.coordinates else None
            ),
            "relative_location": self.relative_location,
            "time_window": self.time_window,
            "vessel_class": self.vessel_class,
            "reason": self.reason,
            "orca_intent": self.orca_intent,
            "router_mode": self.router_mode,
            "latency_ms": round(self.latency_ms, 1),
        }


# --------------------------------------------------------------------------
# Regex extraction -- coordinates, time, vessel class ONLY (Part 11)
# --------------------------------------------------------------------------
# "18.9680,72.5148" / "18.968, 72.515" / "18.9680N 72.5148E" / "lat 18.9 lon 72.5"
# Hemisphere letters must NOT be immediately followed by another letter,
# otherwise the "w" in "wind" reads as a West marker.
_COORD_PAIR = re.compile(
    r"(?<![\d.])(-?\d{1,2}(?:\.\d+)?)\s*°?\s*([NnSs](?![A-Za-z]))?\s*[,;/ ]\s*"
    r"(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([EeWw](?![A-Za-z]))?(?![\d.])"
)
_COORD_LABELLED = re.compile(
    r"lat(?:itude)?\s*[:=]?\s*(-?\d{1,2}(?:\.\d+)?).{0,12}?"
    r"lon(?:g|gitude)?\s*[:=]?\s*(-?\d{1,3}(?:\.\d+)?)",
    re.IGNORECASE,
)

_NEAR_ME_PATTERNS = (
    r"\bnear\s*me\b", r"\bnear\s*by\b", r"\bnearby\b", r"\baround\s*me\b",
    r"\bclosest\b", r"\bnearest\s+to\s+me\b", r"\bmy\s+(?:location|position)\b",
    r"\bwhere\s+am\s+i\b", r"\bhere\b", r"\bcurrent\s+position\b",
    r"\bmere\s+paas\b", r"\bmere\s+aas\s*paas\b", r"\byahan\b", r"\bidhar\b",
)

_VESSEL_PATTERNS = (
    (r"\b(?:small|chhoti|chota|country)\s*(?:boat|craft|canoe|nauka)\b", "small_fishing_boat"),
    (r"\b(?:canoe|catamaran|kattumaram|vallam)\b", "small_fishing_boat"),
    (r"\b(?:mechani[sz]ed|trawler|large|big|bada)\s*(?:boat|vessel|craft)?\b", "mechanized_trawler"),
    (r"\bmotori[sz]ed\b", "motorized_boat"),
    (r"\bsmall\s*fishing\s*boat\b", "small_fishing_boat"),
)


def extract_coordinates(query: str) -> Optional[tuple]:
    """Pull an explicit lat/lon out of the query. Lexical, not semantic --
    this is exactly the kind of thing regex should keep doing.

    Returns (lat, lon) clamped to plausible Earth ranges, else None. Never
    invents a location; a failed parse returns None so the normal location
    resolution path runs.
    """
    q = query or ""
    m = _COORD_LABELLED.search(q)
    if m:
        try:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        except ValueError:
            pass
    for m in _COORD_PAIR.finditer(q):
        raw_lat, lat_hem, raw_lon, lon_hem = m.groups()
        # Require a decimal point or a hemisphere letter somewhere, otherwise
        # "10,20 boats" and "sector 3, 4" would be read as coordinates.
        if "." not in raw_lat and "." not in raw_lon and not (lat_hem or lon_hem):
            continue
        try:
            lat, lon = float(raw_lat), float(raw_lon)
        except ValueError:
            continue
        if lat_hem and lat_hem.lower() == "s":
            lat = -abs(lat)
        if lon_hem and lon_hem.lower() == "w":
            lon = -abs(lon)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
    return None


def detect_relative_location(query: str) -> Optional[str]:
    """'near me' / 'around me' / 'nearby' / 'closest' -> "near_me"."""
    q = (query or "").lower()
    for pat in _NEAR_ME_PATTERNS:
        if re.search(pat, q):
            return "near_me"
    return None


# Cache of the known-coastal-place vocabulary, loaded lazily from the
# orchestrator gazetteer so the router and the resolver never drift apart.
_KNOWN_PLACE_KEYS: Optional[tuple] = None


def _known_place_keys() -> tuple:
    global _KNOWN_PLACE_KEYS
    if _KNOWN_PLACE_KEYS is None:
        try:
            from .state import KNOWN_LOCATIONS
            _KNOWN_PLACE_KEYS = tuple(sorted(KNOWN_LOCATIONS.keys(), key=len, reverse=True))
        except Exception:
            _KNOWN_PLACE_KEYS = ()
    return _KNOWN_PLACE_KEYS


def extract_named_place(query: str) -> Optional[str]:
    """Deterministically pull a KNOWN Indian coastal place out of the query.

    Handles bare mentions ("Mumbai"), and "near/off/around <place>" plus the
    Hinglish "<place> ke paas" / "<place> ke aas paas". This is the safeguard
    (spec Parts D/I): when the user names a coastal town, we NEVER silently
    let a 'near me'/device-GPS heuristic drag the recommendation to another
    state. Word-boundary matched for ASCII, substring for Indic scripts (where
    \\b does not work). Longest key first. Returns the canonical gazetteer
    key (e.g. "mumbai") or None.
    """
    q = (query or "").lower()
    if not q:
        return None
    for key in _known_place_keys():
        # ASCII keys can use word boundaries; Indic script keys need plain substring
        # because \\b is ASCII-only and fails for Devanagari/Tamil etc.
        if key.isascii():
            if re.search(r"\b" + re.escape(key) + r"\b", q):
                return key
        else:
            if key in q:
                return key
    return None


def extract_time_window(query: str) -> str:
    q = (query or "").lower()
    # Hindi/Hinglish "kal" is tomorrow in a forward-looking marine question.
    tomorrow = ("tomorrow" in q or re.search(r"\bkal\b", q) or "aane wale kal" in q
                or "next day" in q)
    if tomorrow:
        if any(k in q for k in ("morning", "subah", "savere", "dawn", "sunrise")):
            return "tomorrow_morning"
        return "tomorrow"
    return "today"


def extract_target_hour(query: str) -> Optional[int]:
    m = re.search(r"\bat\s+(\d{1,2})\s*(?::\d{2})?\s*(am|pm)?", (query or "").lower())
    if not m:
        return None
    hour = int(m.group(1))
    suffix = m.group(2)
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    return hour if 0 <= hour <= 23 else None


def extract_vessel_class(query: str) -> Optional[str]:
    q = (query or "").lower()
    for pat, vessel in _VESSEL_PATTERNS:
        if re.search(pat, q):
            return vessel
    return None


def extract_months_back(query: str) -> Optional[int]:
    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,2})\s*(month|months|mahine|mahina)\b",
                  (query or "").lower())
    if m:
        n = int(m.group(1))
        return max(3, min(24, n))
    m = re.search(r"\b(\d{1,2})\s*(?:month|months)\b", (query or "").lower())
    if m:
        n = int(m.group(1))
        return max(3, min(24, n))
    return None


# --------------------------------------------------------------------------
# LLM classification prompt (Part 5) + few-shot examples (Part 6)
# --------------------------------------------------------------------------
ROUTER_SYSTEM_PROMPT = """You are ORCA's routing brain. ORCA is a marine-intelligence assistant for Indian coastal fishers and authorities.

You NEVER answer the user's question. You NEVER give marine advice, numbers or safety verdicts. You ONLY classify the query and extract parameters by calling the route_query tool.

Understand INTENT, not vocabulary. Queries arrive in English, Hindi, Hinglish, Marathi, Tamil and mixed/romanised phrasing, often paraphrased or with typos. Classify by what the user is trying to accomplish.

intent (pick the PRIMARY one):
- pfz          finding fish / potential fishing zones / where to fish
- ocean_state  sea or weather conditions: SST, wind, waves, swell, current, tide, chlorophyll
- hazard       safety of going out, cyclone/storm/warning/alert checks, "is it safe"
- geospatial   boundaries (EEZ/IMBL/MPA), "am I inside", navigation, routes, distance to a place
- trend        how something CHANGED over weeks/months and why (analytical)
- sar          a missing/overdue/lost boat or person, distress, search and rescue
- tourism      coastal POIs — beaches, lighthouses, harbours, viewpoints, places to visit/sightseeing near the coast
- general      not about the sea, fishing, weather, safety or coasts

agents = the ORCA specialists genuinely needed. Combine them for combined asks:
- OceanStateAgent  live SST/wind/waves/swell/current/tide/chlorophyll
- HazardAgent      threshold safety verdict + cyclone/marine alerts (always pair with OceanStateAgent)
- PFZAgent         potential fishing zones
- GeospatialAgent  boundary geofencing and route planning
- TrendAgent       multi-month history and correlation
- TourismAgent     nearby coastal POIs (beaches/lighthouses/harbours/viewpoints) with per-POI live safety

orca_intent = ORCA's internal plan label. Use: ocean_state, pfz_lookup, safety_check, hazard_alerts, geofence_check, route_plan, trend_analysis, zone_scan, poi_lookup, unknown.
Use safety_check for "is it safe to go out" questions, hazard_alerts for "is there a cyclone/warning" questions, route_plan when the user wants to travel/navigate somewhere, geofence_check for boundary questions, poi_lookup for beaches/lighthouses/harbours/tourism POI queries (also covers "places to visit near the coast").

Rules:
- location_name: copy the place name as written ("Goa", "Veraval", "Kochi"). Use "same" when the user refers back to a previous location without naming one. Use "unknown" when no place is named.
- Bare coordinates are a PARAMETER, not an intent. "18.9680,72.5148 wind?" is ocean_state with OceanStateAgent only - never add GeospatialAgent just because coordinates are present.
- "near me"/"nearby"/"closest"/"mere paas" sets relative_location=near_me; it does not change the intent.
- confidence: your honest probability that this classification is right. Be low (<0.5) when the query is genuinely ambiguous or off-topic.
- reason: one short sentence.

Examples (query -> intent | agents):
"SST near me" -> ocean_state | OceanStateAgent
"How warm is the sea?" -> ocean_state | OceanStateAgent
"18.9680,72.5148 wind?" -> ocean_state | OceanStateAgent
"Chlorophyll near Veraval" -> ocean_state | OceanStateAgent
"Kal Goa ke paas machhli pakadne jana safe rahega?" -> hazard | OceanStateAgent, HazardAgent (orca_intent=safety_check, time_window=tomorrow, location_name=Goa)
"Is it safe to fish tomorrow?" -> hazard | OceanStateAgent, HazardAgent
"Any cyclone warning for Odisha?" -> hazard | HazardAgent, OceanStateAgent (orca_intent=hazard_alerts)
"Nearest PFZ" -> pfz | PFZAgent, OceanStateAgent
"Navigate to nearest PFZ" -> pfz | PFZAgent, GeospatialAgent (orca_intent=pfz_lookup)
"Marine conditions at the nearest PFZ" -> pfz | PFZAgent, OceanStateAgent
"Am I inside India's EEZ?" -> geospatial | GeospatialAgent (orca_intent=geofence_check)
"Safest route from Ratnagiri to Mumbai" -> geospatial | GeospatialAgent, OceanStateAgent, HazardAgent (orca_intent=route_plan)
"Boat missing near Kochi since morning" -> sar | OceanStateAgent, GeospatialAgent, HazardAgent (orca_intent=safety_check)
"Why has fish productivity declined over the last 6 months?" -> trend | TrendAgent (orca_intent=trend_analysis)
"Beaches near Goa" -> tourism | TourismAgent, GeospatialAgent (orca_intent=poi_lookup)
"Harbour and lighthouse near Kochi" -> tourism | TourismAgent, GeospatialAgent (orca_intent=poi_lookup)
"Who won the cricket match?" -> general | (none)
"""

ROUTER_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": list(ROUTER_INTENTS),
            "description": "Primary user intent.",
        },
        "orca_intent": {
            "type": "string",
            "enum": list(ORCA_INTENTS),
            "description": "ORCA's internal plan label for this query.",
        },
        "agents": {
            "type": "array",
            "items": {"type": "string", "enum": list(DISPATCHABLE_AGENTS)},
            "description": "Specialists genuinely needed for THIS query.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Honest probability the classification is correct.",
        },
        "location_name": {
            "type": "string",
            "description": "Place name as written, 'same' to inherit the previous location, 'unknown' if none.",
        },
        "time_window": {
            "type": "string",
            "enum": list(KNOWN_TIME_WINDOWS),
            "description": "Roughly when the user is asking about.",
        },
        "relative_location": {
            "type": "string",
            "enum": ["near_me", "none"],
            "description": "near_me when the user means their own position.",
        },
        "vessel_class": {
            "type": "string",
            "enum": ["small_fishing_boat", "motorized_boat", "mechanized_trawler", "none"],
            "description": "Vessel the user mentions, else none.",
        },
        "target_hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": "Exact local hour if the user names one. Omit otherwise.",
        },
        "months_back": {
            "type": "integer",
            "minimum": 3,
            "maximum": 24,
            "description": "For trend queries only: months of history requested. Omit otherwise.",
        },
        "reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["intent", "orca_intent", "agents", "confidence", "location_name",
                 "time_window", "reason"],
}


# --------------------------------------------------------------------------
# In-process decision cache (Part 19: no duplicate completions)
# --------------------------------------------------------------------------
_cache: "dict[str, tuple[float, IntentDecision]]" = {}
_cache_lock = threading.Lock()


def _cache_key(query: str, history_key: str) -> str:
    return f"{(query or '').strip().lower()}||{history_key}"


def _cache_get(key: str) -> Optional[IntentDecision]:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        stamp, decision = hit
        if now - stamp > ROUTER_CACHE_TTL_S:
            _cache.pop(key, None)
            return None
    # Return a copy so callers can mutate freely without poisoning the cache.
    return IntentDecision(**{**decision.__dict__, "agents": list(decision.agents or [])})


def _cache_put(key: str, decision: IntentDecision) -> None:
    with _cache_lock:
        if len(_cache) >= ROUTER_CACHE_MAX:
            # Cheap eviction: drop the oldest quarter.
            for stale in sorted(_cache, key=lambda k: _cache[k][0])[: max(1, ROUTER_CACHE_MAX // 4)]:
                _cache.pop(stale, None)
        _cache[key] = (time.time(), decision)


def clear_cache() -> None:
    """Test/ops helper."""
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------
# Deterministic layer -- reuses the EXISTING routers, adds no new keywords
# --------------------------------------------------------------------------
def _deterministic_decision(query: str) -> tuple[str, list, float, str]:
    """(orca_intent, agents, confidence, reason) from the pre-existing
    deterministic routers. This is the low-confidence fallback and the
    medium-confidence cross-check -- never the primary classifier.
    """
    try:
        import auto_router
    except Exception:
        auto_router = None  # type: ignore

    if auto_router is not None:
        try:
            d = auto_router.fast_route(query)
        except Exception:
            d = None
        if d is not None:
            return (
                d.intent,
                list(d.agents or []),
                float(d.confidence),
                f"[deterministic] {d.reason}",
            )
    # auto_router declined -> ask the orchestrator's own rule router.
    try:
        from orchestrator import Orchestrator  # local import; avoids a cycle at import time

        orca_intent = Orchestrator._route_intent(None, query)  # type: ignore[arg-type]
    except Exception:
        orca_intent = "unknown"
    agents = list(ROUTER_TO_ORCA.get(ORCA_TO_ROUTER.get(orca_intent, "general"), ("unknown", []))[1])
    if orca_intent == "safety_check":
        agents = ["OceanStateAgent", "HazardAgent", "GeospatialAgent"]
    elif orca_intent == "route_plan":
        agents = ["GeospatialAgent", "OceanStateAgent", "HazardAgent"]
    elif orca_intent == "zone_scan":
        agents = ["PFZAgent", "OceanStateAgent", "HazardAgent", "GeospatialAgent"]
    conf = 0.45 if orca_intent == "unknown" else 0.6
    return orca_intent, agents, conf, "[deterministic] rule-based intent routing."


def _repair(orca_intent: str, router_intent: str, agents: list) -> tuple[str, str, list]:
    """Make (router_intent, orca_intent, agents) mutually consistent and
    guaranteed dispatchable, without ever silently emptying the agent list."""
    if router_intent not in ROUTER_INTENTS:
        router_intent = ORCA_TO_ROUTER.get(orca_intent, "general")
    if orca_intent not in ORCA_INTENTS:
        orca_intent = ROUTER_TO_ORCA[router_intent][0]
    agents = [a for a in (agents or []) if a in DISPATCHABLE_AGENTS]
    # HazardAgent always consumes a fresh ocean reading (existing dependency).
    if "HazardAgent" in agents and "OceanStateAgent" not in agents:
        agents.append("OceanStateAgent")
    if not agents and orca_intent != "unknown":
        agents = list(ROUTER_TO_ORCA[router_intent][1])
        if "HazardAgent" in agents and "OceanStateAgent" not in agents:
            agents.append("OceanStateAgent")
    return router_intent, orca_intent, agents


# --------------------------------------------------------------------------
# LLM layer
# --------------------------------------------------------------------------
def _history_to_text(conversation_history) -> tuple[str, str]:
    """Render recent turns for the prompt + a stable cache key. Accepts a
    list of {"role","content"} dicts, a list of strings, or a SessionContext-
    like object with last_query/last_intent/location_name and rich history."""
    if not conversation_history:
        return "", ""
    lines: list[str] = []
    if isinstance(conversation_history, (list, tuple)):
        for turn in list(conversation_history)[-4:]:
            if isinstance(turn, dict):
                role = turn.get("role", "user")
                content = str(turn.get("content", "")).strip()
                if content:
                    lines.append(f"{role}: {content}")
            elif isinstance(turn, str) and turn.strip():
                lines.append(f"user: {turn.strip()}")
    else:  # object with attributes (SessionContext)
        # Prefer rich history list if present
        hist = getattr(conversation_history, "history", None)
        if hist:
            for h in list(hist)[-4:]:
                role = h.get("role", "user")
                content = str(h.get("content", "")).strip()
                intent = h.get("intent", "")
                loc = h.get("location", "")
                if content:
                    extra = ""
                    if intent:
                        extra += f" (intent {intent})"
                    if loc:
                        extra += f" @ {loc}"
                    lines.append(f"{role}: {content}{extra}")
        # Fallback to legacy single last_query fields
        if not lines:
            lq = getattr(conversation_history, "last_query", "") or ""
            li = getattr(conversation_history, "last_intent", "") or ""
            ln = getattr(conversation_history, "location_name", "") or ""
            if lq:
                lines.append(f"previous query: {lq}"
                             + (f" (intent {li})" if li else "")
                             + (f" about {ln}" if ln else ""))
        # Also add richer prior summary if available
        lv = getattr(conversation_history, "last_verdict", "") or ""
        le = getattr(conversation_history, "last_evidence", "") or ""
        lo = getattr(conversation_history, "last_ocean_summary", "") or ""
        if lv or le or lo:
            summ = []
            if lv:
                summ.append(f"verdict {lv[:50]}")
            if lo:
                summ.append(f"ocean {lo}")
            if le:
                summ.append(f"evidence {le[:80]}")
            if summ:
                lines.append("prior summary: " + "; ".join(summ))
        lt = getattr(conversation_history, "time_window", "") or ""
        if lt and lt != "today":
            lines.append(f"prior time_window: {lt}")
    text = "\n".join(lines)
    return text, text[:200]


def _llm_classify(query: str, history_text: str) -> Optional[dict]:
    if not llm_client.is_available():
        return None
    user_prompt = f'USER QUERY: "{query}"'
    if history_text:
        user_prompt += f"\n\nRECENT CONVERSATION:\n{history_text}"
    user_prompt += "\n\nClassify by calling route_query. Do not answer the question."
    try:
        return llm_client.complete_structured(
            system_prompt=ROUTER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_name="route_query",
            tool_description="Classify a marine query into intent, agents and parameters.",
            schema=ROUTER_TOOL_SCHEMA,
            temperature=0.0,
            max_tokens=ROUTER_MAX_TOKENS,
            timeout=ROUTER_TIMEOUT_S,
            attempts=1,  # never wait on a retry -- fall back to rules instantly
        )
    except llm_client.LLMUnavailableError:
        return None
    except Exception as exc:  # defensive: any parse/schema error -> rules
        log.warning("intent router LLM failed (%s); using deterministic fallback", exc)
        return None


def _decision_from_llm(args: dict, query: str) -> IntentDecision:
    router_intent = str(args.get("intent", "general")).strip().lower()
    orca_intent = str(args.get("orca_intent", "")).strip().lower()
    agents = list(args.get("agents") or [])
    try:
        conf = float(args.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    router_intent, orca_intent, agents = _repair(orca_intent, router_intent, agents)

    loc = args.get("location_name")
    loc_name = None if (not loc or str(loc).strip().lower() == "unknown") else str(loc).strip()

    rel = args.get("relative_location")
    rel = None if (not rel or str(rel).lower() == "none") else str(rel).lower()
    # Regex is the source of truth for relative location (Part 9); LLM only confirms.
    rel = detect_relative_location(query) or rel

    vessel = args.get("vessel_class")
    vessel = None if (not vessel or str(vessel).lower() == "none") else str(vessel)

    tw = str(args.get("time_window", "today")).strip().lower()
    if tw not in KNOWN_TIME_WINDOWS:
        tw = extract_time_window(query)

    target_hour = args.get("target_hour")
    if not isinstance(target_hour, int):
        target_hour = extract_target_hour(query)
    months_back = args.get("months_back")
    if not isinstance(months_back, int):
        months_back = extract_months_back(query)

    return IntentDecision(
        intent=router_intent,
        agents=agents,
        confidence=conf,
        location_name=loc_name,
        coordinates=None,  # filled by route_intent from regex
        relative_location=rel,
        time_window=tw,
        vessel_class=vessel,
        reason=str(args.get("reason", "")).strip(),
        orca_intent=orca_intent,
        router_mode="llm",
        target_hour=target_hour,
        months_back=months_back,
        llm_confidence=conf,
    )


def _decision_from_rules(query: str) -> IntentDecision:
    orca_intent, agents, conf, reason = _deterministic_decision(query)
    router_intent, orca_intent, agents = _repair(orca_intent, ORCA_TO_ROUTER.get(orca_intent, "general"), agents)
    return IntentDecision(
        intent=router_intent,
        agents=agents,
        confidence=conf,
        location_name=None,
        relative_location=detect_relative_location(query),
        time_window=extract_time_window(query),
        vessel_class=extract_vessel_class(query),
        reason=reason,
        orca_intent=orca_intent,
        router_mode="rules",
        target_hour=extract_target_hour(query),
        months_back=extract_months_back(query),
    )


def _merge_medium(llm: IntentDecision, query: str) -> IntentDecision:
    """Medium-confidence (0.50-0.85): cross-check the LLM against the
    deterministic router. When they disagree on the ORCA intent, union the
    agent lists (so nothing genuinely needed is dropped) and note it -- the
    LLM's intent label is kept but coverage is widened. Confidence is nudged
    up on agreement, down on disagreement."""
    d_intent, d_agents, d_conf, _ = _deterministic_decision(query)
    if d_intent == llm.orca_intent:
        llm.confidence = min(0.95, llm.confidence + 0.08)
        llm.router_mode = "llm+rules(agree)"
        llm.reason = (llm.reason + " (confirmed by deterministic router)").strip()
        return llm
    # Disagreement -> widen coverage rather than pick a loser.
    union: list[str] = list(llm.agents)
    for a in d_agents:
        if a in DISPATCHABLE_AGENTS and a not in union:
            union.append(a)
    _, llm.orca_intent, llm.agents = _repair(llm.orca_intent, llm.intent, union)
    if len(union) > len(llm.agents):
        llm.is_compound = True
    llm.confidence = max(CONF_LOW, llm.confidence - 0.05)
    llm.router_mode = "llm+rules(merged)"
    llm.reason = (llm.reason + f" (merged with deterministic '{d_intent}')").strip()
    return llm


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------
def route_intent(query: str, conversation_history=None) -> IntentDecision:
    """Classify a raw user query into an IntentDecision.

    This is the ONLY function the orchestrator calls. It owns the confidence
    policy (Part 7), coordinate/near-me/vessel extraction (Parts 8-9, 11) and
    the decision cache (Part 19). Everything downstream (plan builder,
    LangGraph dispatch, agents, response) is unchanged.
    """
    t0 = time.perf_counter()
    query = query or ""
    history_text, history_key = _history_to_text(conversation_history)

    # Regex parameters are always available regardless of routing path.
    coords = extract_coordinates(query)
    rel = detect_relative_location(query)
    named_place = extract_named_place(query)

    def _finish(decision: IntentDecision) -> IntentDecision:
        # Coordinates are a parameter and must NOT change the intent (Part 8):
        # an ocean_state query that carries a lat/lon stays ocean_state.
        decision.coordinates = coords
        # Named-place safeguard (Parts D/I): if the user actually named a known
        # coastal town and the router didn't capture it (LLM miss or rules
        # fallback), bind it deterministically. A named place also OUTRANKS a
        # 'near me' signal — "Mumbai ke paas" means near Mumbai, not near the
        # device — so we drop relative_location to stop a GPS/other-state jump.
        _ln = str(decision.location_name or "").strip().lower()
        if named_place and (not _ln or _ln in ("unknown", "none", "near_me")):
            decision.location_name = named_place
        _ln = str(decision.location_name or "").strip().lower()
        if named_place and _ln == named_place:
            decision.relative_location = None
            rel_local = None
        else:
            rel_local = rel
        if rel_local and not decision.relative_location:
            decision.relative_location = rel_local
        if decision.time_window not in KNOWN_TIME_WINDOWS:
            decision.time_window = extract_time_window(query)
        if not decision.vessel_class:
            decision.vessel_class = extract_vessel_class(query)
        decision.latency_ms = (time.perf_counter() - t0) * 1000
        _log_decision(query, decision)
        return decision

    # Router disabled -> deterministic only (legacy behaviour).
    if ROUTER_MODE == "off":
        d = _decision_from_rules(query)
        d.router_mode = "disabled"
        return _finish(d)

    # Cache (only when there is no rolling history to key on precisely; the
    # key includes a short history digest so context-sensitive turns differ).
    ckey = _cache_key(query, history_key)
    cached = _cache_get(ckey)
    if cached is not None:
        cached.router_mode = (cached.router_mode or "cache") + "|cache"
        return _finish(cached)

    llm_args = None
    if ROUTER_MODE == "fast-first":
        # Only pay for the LLM when the deterministic router is uncertain.
        d_intent, d_agents, d_conf, d_reason = _deterministic_decision(query)
        if d_conf >= CONF_HIGH:
            d = _decision_from_rules(query)
            _cache_put(ckey, d)
            return _finish(d)
        llm_args = _llm_classify(query, history_text)
    else:  # ROUTER_MODE == "llm" (default): LLM first on every query
        llm_args = _llm_classify(query, history_text)

    if llm_args is None:
        # No LLM available/failed -> deterministic fallback (< 0.50 path too).
        d = _decision_from_rules(query)
        _cache_put(ckey, d)
        return _finish(d)

    decision = _decision_from_llm(llm_args, query)

    # Confidence-based routing (Part 7).
    if decision.confidence >= CONF_HIGH:
        pass  # trust the LLM as-is
    elif decision.confidence >= CONF_LOW:
        decision = _merge_medium(decision, query)
    else:
        # Low confidence -> deterministic parser decides, but keep the LLM's
        # extracted parameters (location/time/vessel) which are usually fine.
        rules = _decision_from_rules(query)
        rules.location_name = decision.location_name or rules.location_name
        rules.vessel_class = decision.vessel_class or rules.vessel_class
        if decision.time_window in KNOWN_TIME_WINDOWS:
            rules.time_window = decision.time_window
        rules.target_hour = decision.target_hour or rules.target_hour
        rules.months_back = decision.months_back or rules.months_back
        rules.router_mode = "rules(llm-lowconf)"
        rules.reason = (rules.reason + f" (LLM low-confidence {decision.confidence:.2f} overridden)").strip()
        rules.llm_confidence = decision.llm_confidence
        decision = rules

    _cache_put(ckey, decision)
    return _finish(decision)


def _log_decision(query: str, d: IntentDecision) -> None:
    try:
        log.info(
            "IntentRouter[%s] intent=%s orca=%s agents=[%s] conf=%.2f "
            "loc=%s coords=%s rel=%s time=%s vessel=%s (%.0fms) :: %s",
            d.router_mode, d.intent, d.orca_intent,
            ", ".join(a.replace("Agent", "") for a in (d.agents or [])) or "-",
            d.confidence, d.location_name or "-",
            (f"{d.coordinates[0]:.4f},{d.coordinates[1]:.4f}" if d.coordinates else "-"),
            d.relative_location or "-", d.time_window, d.vessel_class or "-",
            d.latency_ms, (query[:60] + ("..." if len(query) > 60 else "")),
        )
    except Exception:
        pass
