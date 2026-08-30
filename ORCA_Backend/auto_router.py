"""
Auto Router — fast deterministic intent routing BEFORE the expensive Planning LLM.

Attempts to classify query into one of 7 marine intents using keyword/regex
heuristics (0 LLM calls, <1ms). If confidence is low / ambiguous, caller
should fallback to llm planner (routing_mode = llm-planner).

Also decides query complexity (simple / complex / deep) and which specialist
agents are needed, so the orchestrator can skip Discussion/Synthesis for
fast queries.

Spec targets:
- safety_check
- pfz_lookup
- hazard_alerts
- route_plan
- geofence_check
- trend_analysis
- zone_scan (ranked good/avoid zones)
"""

from __future__ import annotations
import re
from dataclasses import dataclass


INTENT_DEFAULT_AGENTS = {
    "safety_check": ["OceanStateAgent", "HazardAgent", "GeospatialAgent"],
    "ocean_state": ["OceanStateAgent"],
    "pfz_lookup": ["PFZAgent", "OceanStateAgent", "GeospatialAgent"],
    "route_plan": ["GeospatialAgent", "OceanStateAgent", "HazardAgent"],
    "geofence_check": ["GeospatialAgent"],
    "hazard_alerts": ["HazardAgent", "OceanStateAgent"],
    "trend_analysis": ["TrendAgent"],
    "zone_scan": ["PFZAgent", "OceanStateAgent", "HazardAgent", "GeospatialAgent"],
    "unknown": [],
}

# Per-intent keyword sets — ordered by specificity (more specific first)
INTENT_KEYWORDS = {
    "trend_analysis": [
        r"why has", r"why is", r"trend", r"declined", r"change.*over",
        r"over the last", r"productivity", r"correlation", r"correlate",
        r"sst.*changed", r"chlorophyll.*changed", r"months", r"years.*change",
    ],
    "ocean_state": [
        r"\bweather\b", r"\bforecast\b", r"marine weather", r"ocean state",
        r"sea condition", r"sea conditions", r"marine conditions", r"ocean conditions", r"sea state",
        r"\bwind\b", r"wind speed", r"wind gust",
        r"\bwaves?\b", r"wave height", r"\bswell\b", r"\bsst\b",
        r"sea surface temperature", r"sea temperature", r"ocean temperature",
        r"temperature", r"temp", r"temper", r"chlorophyll", r"\btide\b",
        r"high tide", r"low tide", r"\bcurrents?\b",
    ],
    "zone_scan": [
        r"which zones", r"which regions", r"zones to avoid", r"where should i fish",
        r"good zones", r"avoid.*zone", r"seek.*zone", r"rank.*zone",
    ],
    "route_plan": [
        r"route", r"navigate", r"safest path", r"how do i get", r"safe route",
        r"waypoint", r"passage", r"\bfrom\b.{2,40}?\bto\b", r"plan.*route",
    ],
    "geofence_check": [
        r"boundary", r"border", r"restricted", r"geofence", r"imbl",
        r"mpa", r"eez", r"eez.*limit", r"near.*restricted", r"inside.*zone",
        r"am i near", r"am i inside", r"protected.*area",
    ],
    "hazard_alerts": [
        r"cyclone", r"alert", r"warning", r"depression", r"squall",
        r"storm", r"lightning", r"thunderstorm", r"rough sea", r"hazard.*alert",
    ],
    "pfz_lookup": [
        r"fishing zone", r"fish zone", r"pfz", r"where to fish", r"nearest.*fishing",
        r"productive.*zone", r"\bfish(?:ing)?\s+zone\b", r"potential fishing",
    ],
    "safety_check": [
        r"\bsafe\b", r"safety", r"go fishing", r"venture", r"risky", r"danger",
        r"should i go", r"can i go", r"is it safe",
    ],
}

# Complexity signals
COMPLEXITY_KEYWORDS_DEEP = [
    r"trend", r"over the last", r"correlation", r"why has", r"compare",
    r"comprehensive", r"detailed reasoning", r"multi-zone", r"months",
]
COMPLEXITY_KEYWORDS_COMPLEX = [
    r"route", r"zone.*avoid", r"which.*zone", r"best.*zone",
]


@dataclass
class RoutingDecision:
    intent: str
    agents: list
    complexity: str  # fast | standard | deep
    confidence: float
    routing_mode: str  # fast-rules | llm-planner
    reason: str
    is_compound: bool = False
    compound_intents: list | None = None


def _score_intents(q: str) -> dict[str, int]:
    """Count keyword hits per intent (case-insensitive)."""
    ql = q.lower()
    scores: dict[str, int] = {}
    for intent, patterns in INTENT_KEYWORDS.items():
        c = 0
        for pat in patterns:
            try:
                if re.search(pat, ql):
                    c += 1
            except re.error:
                if pat.lower() in ql:
                    c += 1
        if c > 0:
            scores[intent] = c
    return scores


def _detect_complexity(q: str, intent: str, num_agents: int) -> str:
    ql = q.lower()
    # Trend analysis is always deep
    if intent == "trend_analysis":
        return "deep"
    # Multi-agent or explicit deep keywords
    if any(re.search(p, ql) for p in COMPLEXITY_KEYWORDS_DEEP):
        return "deep"
    if intent == "zone_scan" or num_agents >= 4:
        return "complex"
    if intent == "route_plan" and ("hazard" in ql or "avoid" in ql):
        return "complex"
    if any(re.search(p, ql) for p in COMPLEXITY_KEYWORDS_COMPLEX):
        return "complex"
    # Simple: single intent, few agents, short query
    if num_agents <= 2 and len(q.split()) <= 12:
        return "fast"
    return "standard"


def fast_route(normalized_query: str) -> RoutingDecision | None:
    """
    Try deterministic routing. Returns RoutingDecision if confident,
    else None (caller should fallback to LLM planner).
    Never invents values — only uses keyword hits.
    """
    q = (normalized_query or "").strip()
    if not q:
        return None
    # Very short / ambiguous queries -> fallback
    if len(q.split()) < 2 and "safe" not in q.lower():
        return None

    scores = _score_intents(q)
    if not scores:
        return None

    # Pick top intent by score, tie -> ambiguous (single-intent fast path)
    sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_intent, top_score = sorted_intents[0]
    second_score = sorted_intents[1][1] if len(sorted_intents) > 1 else 0

    # --- Compound-intent handling (Task 4) ---
    # If two or more intents score above shared confidence threshold (0.78),
    # union their agent lists instead of only top intent's list.
    # Threshold corresponds to: score>=2 (0.92) OR score==1 with len>=3 (0.78)
    # This is more conservative than raw score>=1, avoids false compound from
    # weak single-hit short queries. Trend weak single-hit is excluded.
    _qualifying = []
    _qualifying_conf = {}
    for intent, sc in scores.items():
        if sc >= 2:
            # For trend, even score 2 is considered qualifying (needs 2 keywords)
            # No extra filter needed for sc>=2
            _qualifying.append(intent)
            _qualifying_conf[intent] = 0.92
        elif sc == 1:
            if len(q.split()) < 3:
                continue  # 0.55 <0.6, not qualifying
            if intent == "trend_analysis":
                # Single trend word alone is weak — require explicit "trend" or "why has"
                if "trend" not in q.lower() and "why has" not in q.lower():
                    continue
            _qualifying.append(intent)
            _qualifying_conf[intent] = 0.78
    # If compound, union agents and force at least complex
    if len(_qualifying) >= 2:
        # Use top intent for primary intent field, but union agents
        # Deduplicate preserving order: qualifying sorted by score desc
        _qualifying_sorted = sorted(_qualifying, key=lambda x: scores[x], reverse=True)
        union_agents: list[str] = []
        seen: set[str] = set()
        for intent in _qualifying_sorted:
            for a in INTENT_DEFAULT_AGENTS.get(intent, []):
                if a not in seen:
                    seen.add(a)
                    union_agents.append(a)
        # Complexity: at least complex for compound
        base_complexity = _detect_complexity(q, top_intent, len(union_agents))
        if base_complexity in ("fast", "standard"):
            compound_complexity = "complex"
        else:
            compound_complexity = base_complexity  # keep deep/complex
        # Confidence: conservative min of qualifying (at least 0.78)
        compound_confidence = min(_qualifying_conf[i] for i in _qualifying)
        # Trend always deep; ensure deep if trend in qualifying
        if "trend_analysis" in _qualifying and compound_complexity != "deep":
            # Trend analysis compound should be deep per spec
            # But keep at least complex; _detect_complexity already makes trend deep
            pass
        reason = f"Compound intent ({', '.join(_qualifying_sorted)}) — union of {len(union_agents)} agents."
        return RoutingDecision(
            intent=top_intent,  # keep top for backwards compat, agents are unioned
            agents=union_agents,
            complexity=compound_complexity,
            confidence=compound_confidence,
            routing_mode="fast-rules",
            reason=reason,
            is_compound=True,
            compound_intents=_qualifying_sorted,
        )

    # Confidence logic (single-intent fast path):
    #  - top_score >=2 and gap >=1 => high confidence (0.92)
    #  - top_score ==1 and no tie => medium-high (0.78) — still usable for fast path
    #  - tie or top_score==1 with tie => low (fallback to LLM)
    if top_score >= 2 and (top_score - second_score) >= 1:
        confidence = 0.92
    elif top_score == 1 and second_score == 0:
        # Single keyword but unambiguous — medium-high confidence
        # Allow fast-rules for clearly named intents like "pfz_lookup" etc.
        # Give slightly lower confidence so caller can still decide to fallback for edge cases
        confidence = 0.78 if len(q.split()) >= 3 else 0.55
        if confidence < 0.6:
            return None
    else:
        # Tie or weak signal -> uncertain, let LLM decide
        return None

    # Special handling: trend_analysis needs at least 2 trend keywords OR explicit months/why
    if top_intent == "trend_analysis" and top_score < 2:
        # Single "trend" word alone is weak — fallback to LLM for ambiguous trend queries
        if "trend" not in q.lower() and "why has" not in q.lower():
            return None

    agents = list(INTENT_DEFAULT_AGENTS.get(top_intent, []))
    complexity = _detect_complexity(q, top_intent, len(agents))

    # Map complexity to internal mode name
    # fast = skip discussion/synthesis LLM, standard = deterministic synthesis, deep = full deliberation
    reason_map = {
        "trend_analysis": "Analytical question about change over time requires historical correlation.",
        "ocean_state": "Sea/weather conditions (wind, waves, SST, tide) require the Ocean State Agent.",
        "zone_scan": "Ranked zone comparison requires multiple specialists.",
        "route_plan": "Navigation request requires route+sea-state+hazards.",
        "geofence_check": "Boundary proximity check requires geospatial.",
        "hazard_alerts": "Cyclone/storm warning check requires current hazards.",
        "pfz_lookup": "Official PFZ advisory lookup via nearest INCOIS landing centre.",
        "safety_check": "Safety question requires current sea-state and hazard thresholds.",
    }

    return RoutingDecision(
        intent=top_intent,
        agents=agents,
        complexity=complexity,
        confidence=confidence,
        routing_mode="fast-rules",
        reason=reason_map.get(top_intent, f"Deterministic keyword routing to {top_intent}."),
    )


def should_use_llm_fallback(decision: RoutingDecision | None, normalized_query: str) -> bool:
    """True if fast router is uncertain and LLM should be tried."""
    if decision is None:
        return True
    if decision.confidence < 0.6:
        return True
    # Very ambiguous queries (unknown intent) -> LLM
    if decision.intent == "unknown":
        return True
    return False


# For testing / explainability
def explain_routing(decision: RoutingDecision) -> str:
    return (f"Auto Router [{decision.routing_mode}] selected: "
            f"{', '.join(decision.agents) or '(no specialist)'} — {decision.reason} "
            f"(intent={decision.intent}, complexity={decision.complexity}, conf={decision.confidence:.2f})")
