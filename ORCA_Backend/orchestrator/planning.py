"""Planning mixin — extracted from orchestrator.py for Task 10."""
from __future__ import annotations
import os
import re
import time
import llm_client
import sessions as session_store

from .state import (
    INTENT_DEFAULT_AGENTS,
    PLANNING_TOOL_SCHEMA,
    Intent,
    KNOWN_LOCATIONS,
    DEFAULT_LOCATION,
    resolve_location,
    _degraded_message_for,
    _contains_indic_script,
    _contains_romanized_regional_language,
    _detect_romanized_language,
)

from models import AgentTrace, Location, QueryContext

# Keywords that classify a query as an OCEAN_STATE / weather intent (Step 1).
# Robust to paraphrases + common typos: 'tempreture'/'temprature' contain 'temp'/'temper'
# Includes Hindi romanized coastal weather words so "mausam kaisa hai?" works without LLM.
OCEAN_STATE_KEYWORDS = (
    "weather", "forecast", "marine weather", "ocean state", "sea condition", "sea conditions",
    "marine conditions", "ocean conditions", "sea state",
    "wind", "wind speed", "wind gust", "waves", "wave", "wave height",
    "swell", "sst", "sea surface temperature", "sea temperature", "ocean temperature",
    "temperature", "temp", "temper", "chlorophyll", "tide",
    "high tide", "low tide", "current", "currents",
    "mausam", "samundar", "samudra", "hawa", "leher", "kinara",
)

class PlanningMixin:
    """Planning-related helpers for Orchestrator."""

    def _extract_target_hour(self, query: str) -> int | None:
        import re
        m = re.search(r"\bat\s+(\d{1,2})\s*(:\d{2})?\s*(am|pm)?", query.lower())
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
        q = query.lower()
        hit = next((k for k in KNOWN_LOCATIONS if k in q), None)
        if hit:
            return hit
        import re
        m = re.search(r"(?:near|around|close to|off)\s+([a-z][a-z ]{2,40}?)(?:\s+(?:tomorrow|today|coast\b)|[?.!]|$)", q)
        if m:
            return " ".join(m.group(1).split()[:4])
        return "unknown"

    def _route_intent(self, query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ["beach", "harbour", "harbor", "lighthouse", "viewpoint", "touris", "sightseeing", "places to visit", "attractions", "poi"]):
            return Intent.POI_LOOKUP
        # Trend: only when analytical, not generic "why is that?" follow-ups
        if any(kw in q for kw in ["why has", "trend", "declined", "decline", "changed over", "over the last", "productivity", "correlation"]):
            return Intent.TREND_ANALYSIS
        if "why is" in q and any(x in q for x in ["trend", "changed", "declined", "productivity", "correlation", "shelf", "chlorophyll", "sst"]):
            return Intent.TREND_ANALYSIS
        if any(kw in q for kw in ["which zones", "which regions", "zones to avoid", "where should i fish", "good zones"]):
            return Intent.ZONE_SCAN
        # Ocean/weather state questions (sea conditions, wind, waves, SST,
        # chlorophyll, tide) are routed to OceanStateAgent BEFORE the PFZ
        # check so pure-conditions queries never fall through to fishing zones.
        if any(kw in q for kw in OCEAN_STATE_KEYWORDS):
            if any(kw in q for kw in ["fishing zone", "fish zone", "pfz", "where to fish", "where should i fish"]):
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

    def _plan(self, normalized_query: str, prior=None) -> tuple[dict, str]:
        from .state import QUERY_DEPTH
        try:
            import auto_router
            _AUTO = True
        except Exception:
            _AUTO = False
            auto_router = None  # type: ignore
        start = time.perf_counter()
        fast_decision = None
        if _AUTO and auto_router is not None:
            try:
                fast_decision = auto_router.fast_route(normalized_query)
            except Exception:
                fast_decision = None
        if fast_decision is not None and not auto_router.should_use_llm_fallback(fast_decision, normalized_query):  # type: ignore
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
                "is_compound": getattr(fast_decision, "is_compound", False),
                "compound_intents": getattr(fast_decision, "compound_intents", None),
            }
            if prior is not None and prior.location_name and plan["location_name"] in ("unknown", "", "same"):
                plan["location_name"] = prior.location_name
                plan["why"] += " (location inherited from conversation memory)"
            return plan, "fast-rules"
        if llm_client.is_available():
            try:
                memory_line = ""
                if prior is not None and (prior.location_name or prior.last_query):
                    # Richer memory: last 2 turns + verdict/evidence + vessel
                    hist_lines = []
                    # Include rolling history if present
                    for h in (getattr(prior, "history", []) or [])[-3:]:
                        hist_lines.append(f"{h.get('role','user')}: {h.get('content','')[:80]} (intent {h.get('intent','')} @ {h.get('location','')})")
                    hist_block = "\n".join(hist_lines) if hist_lines else ""
                    # Prior summary line
                    mem_parts = []
                    if prior.location_name:
                        mem_parts.append(f"location '{prior.location_name}'")
                    if prior.time_window and prior.time_window != "today":
                        mem_parts.append(f"time '{prior.time_window}'")
                    if prior.last_intent:
                        mem_parts.append(f"intent {prior.last_intent}")
                    if prior.last_verdict:
                        mem_parts.append(f"verdict '{prior.last_verdict[:60]}'")
                    if prior.last_vessel_class:
                        mem_parts.append(f"vessel {prior.last_vessel_class}")
                    if prior.last_ocean_summary:
                        mem_parts.append(f"ocean {prior.last_ocean_summary}")
                    mem_summary = ", ".join(mem_parts) if mem_parts else "no prior context"
                    memory_line = (
                        f"\nCONVERSATION MEMORY: previous turn was {mem_summary}. "
                        f"Last query was '{prior.last_query[:80]}'."
                    )
                    if hist_block:
                        memory_line += f"\nRecent history:\n{hist_block}"
                    if prior.last_evidence:
                        memory_line += f"\nKey evidence: '{prior.last_evidence[:150]}'"
                    memory_line += (
                        " If the user says 'same place'/'there'/'wahan'/'yahan' or asks 'what about the wind?' without a new place/time, "
                        "copy the prior location/time verbatim. If they say 'what about Goa?' keep the same intent but switch location to Goa."
                    )
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
                    attempts=1,
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
                if plan["intent"] == Intent.TREND_ANALYSIS:
                    plan["complexity"] = "deep"
                elif plan["intent"] in (Intent.ZONE_SCAN, Intent.ROUTE_PLAN) and len(plan.get("agents_needed") or []) >= 4:
                    plan["complexity"] = "complex"
                # Robustness for typos/paraphrases: LLM may return UNKNOWN for "tempreture of sea"
                # If keyword fallback has a strong signal, correct it
                if plan["intent"] == Intent.UNKNOWN:
                    _kw_intent = self._route_intent(normalized_query)
                    if _kw_intent != Intent.UNKNOWN:
                        plan["intent"] = _kw_intent
                        # Ensure at least default agents for that intent
                        if not plan.get("agents_needed"):
                            plan["agents_needed"] = INTENT_DEFAULT_AGENTS.get(_kw_intent, [])
                        plan["why"] = (plan.get("why","") + f" (corrected from UNKNOWN via keyword fallback: {_kw_intent})").strip()
                return plan, "llm-planner"
            except llm_client.LLMUnavailableError:
                pass
        fallback_intent = (fast_decision.intent if fast_decision is not None else self._route_intent(normalized_query))
        # Derive needed agents from the intent table so the rule path selects the
        # right specialist (e.g. OceanStateAgent for weather) even when the fast
        # router returned none (Step 3 — never fall through to PFZ for conditions).
        fallback_agents = INTENT_DEFAULT_AGENTS.get(fallback_intent) or []
        if not fallback_agents and fast_decision is not None:
            fallback_agents = list(fast_decision.agents or [])
        plan = {
            "intent": fallback_intent,
            "location_name": self._extract_place_name(normalized_query),
            "time_window": self._extract_time_window(normalized_query),
            "target_hour": self._extract_target_hour(normalized_query),
            "months_back": 6 if "trend" in normalized_query.lower() or "declined" in normalized_query.lower() else None,
            "agents_needed": fallback_agents,
            "why": "[rules] Rule-based keyword parsing used (fast router uncertain, LLM unavailable).",
            "duration_ms": (time.perf_counter() - start) * 1000,
            "routing_mode": "rules",
            "complexity": (fast_decision.complexity if fast_decision is not None else "fast"),
        }
        if plan["intent"] == "unknown" and prior is not None and prior.last_intent and prior.last_intent != "unknown":
            _q_low = normalized_query.lower().strip()
            if len(_q_low.split()) <= 9 and any(p in _q_low for p in ("what about", "how about", "and", "why", "that", "it", "there", "wahan", "yahan", "tithe", "ithe", "wind", "sst", "wave", "safe", "still", "tomorrow", "today")):
                plan["intent"] = prior.last_intent
                plan["agents_needed"] = INTENT_DEFAULT_AGENTS.get(prior.last_intent, plan["agents_needed"])
                plan["why"] += f" (intent inherited from prior '{prior.last_intent}' for follow-up)"
                if plan["time_window"] == "today" and prior.time_window != "today":
                    _has_time = any(k in _q_low for k in ("today", "tomorrow", "kal", "aaj", "parson", "morning", "evening"))
                    if not _has_time:
                        plan["time_window"] = prior.time_window
        return plan, "rules"

    def _step_plan(self, normalized_query: str, raw_query: str, state):
        # Degraded check
        lang = state.get("language", "en")
        lang_mode = state.get("language_mode", "")
        translation_missing = False
        if lang != "en":
            if lang_mode == "rules":
                translation_missing = True
            elif _contains_indic_script(normalized_query) or normalized_query.strip() == raw_query.strip():
                translation_missing = True
            elif not llm_client.is_available():
                translation_missing = True
        # Romanized regional language extension (Task 2 follow-up):
        # ASCII romanized queries like "kal subah machli pakadna safe hai kya"
        # are detected as "en" via fast-path, but contain distinctive transliterated
        # keywords. If LLM is unavailable, treat them as degraded same as Indic script.
        is_romanized = _contains_romanized_regional_language(raw_query) or _contains_romanized_regional_language(normalized_query)
        if lang == "en" and is_romanized and not llm_client.is_available():
            detected = _detect_romanized_language(raw_query) or _detect_romanized_language(normalized_query) or "hi"
            lang = detected
            translation_missing = True
        # Allow i18n deterministic fallback for all supported coastal languages even when LLM is down
        # (romanized or native script) — the templates via i18n.py can answer in that language without translation.
        if lang != "en" and translation_missing:
            _supported = {"hi","mr","ta","te","kn","ml","bn","gu","or","pa","kok","tcy","kfr","byr","mvv","ncr","adm"}
            if lang.lower() in _supported or lang_mode == "rules-romanized" or is_romanized:
                translation_missing = False
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
            from .state import DEFAULT_LOCATION
            location = DEFAULT_LOCATION
            from models import QueryContext
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
            try:
                import sessions as session_store
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
            from models import AgentTrace
            trace = AgentTrace(
                agent_name="PlanningAgent",
                action=f"Degraded mode — non-English query '{lang}' with LLM unavailable [routing=degraded]",
                result_summary=f"Service is in limited mode; translation unavailable. Returned localized degraded message for '{lang}'.",
                data_sources=[],
                duration_ms=0.0,
            )
            return plan, plan_mode, location, context, trace

        import sessions as session_store
        prior = session_store.get(state["session_id"])
        plan, plan_mode = self._plan(normalized_query, prior=prior)

        device_gps = state.get("device_gps") or (
            tuple(prior.device_gps) if (prior and prior.device_gps) else None
        )
        destination = state.get("destination") or (
            Location(**prior.destination) if (prior and prior.destination) else None
        )
        loc_name = str(plan.get("location_name") or "").strip().lower()
        # Word-boundary-aware detection so "here" doesn't fire inside "where"/"somewhere"
        _my_location_phrases = (
            "where am i", "my location", "my position", "current position",
            "here", "around me", "where i am", "near me", "nearby",
        )
        _q_lower = normalized_query.lower()
        is_my_location_query = any(
            re.search(r'\b' + re.escape(k) + r'\b', _q_lower) for k in _my_location_phrases
        )

        import logging as _logging
        _glog = _logging.getLogger("orca.orchestrator")
        if device_gps:
            _glog.info(
                "GPS acquired: %.4f,%.4f | Using GPS coordinates%s",
                device_gps[0], device_gps[1],
                f" for '{loc_name or 'current position'}'" if is_my_location_query else "",
            )
        else:
            _glog.info("GPS unavailable — falling back to selected location")

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
            # Keep plan's location_name as the resolved display name for consistency
            plan["location_name"] = location.name
        elif (_loc_is_empty or is_my_location_query) and device_gps:
            # No named place, or explicit my-location query with no resolvable named place -> use GPS
            if is_my_location_query and not _loc_is_empty:
                _glog.info(
                    "My-location heuristic overriding unresolved named location '%s' -> GPS %.4f,%.4f for query '%s'",
                    plan.get("location_name"), device_gps[0], device_gps[1], normalized_query,
                )
            elif _loc_is_empty and is_my_location_query:
                _glog.info(
                    "My-location query with no named place — using GPS %.4f,%.4f for '%s'",
                    device_gps[0], device_gps[1], normalized_query,
                )
            try:
                import data_connectors.geocode as geocode
                resolved_name = geocode.reverse_geocode(device_gps[0], device_gps[1])
                location = Location(name=f"Current Position ({resolved_name})", lat=device_gps[0], lon=device_gps[1])
                plan["location_name"] = location.name
            except Exception:
                location = Location(name=f"Current Position ({device_gps[0]:.3f}°N, {device_gps[1]:.3f}°E)", lat=device_gps[0], lon=device_gps[1])
                plan["location_name"] = location.name
        else:
            # No heuristic GPS — named place failed to resolve (or empty with no GPS)
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
                    # Dummy sentinel to keep context valid; response will intercept needs_location
                    from models import Location as _Loc
                    location = _Loc(name="ASK_LOCATION", lat=0, lon=0)

        from models import QueryContext
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

        import sessions as session_store
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
        auto_explain = ""
        if routing_mode == "fast-rules":
            selected_agents = self._selected_specialists(plan, live_position=bool(state.get("device_gps") or state.get("destination")))
            agent_names = [a.replace("_", " ").title() for a in selected_agents]
            auto_explain = f" | Auto Router selected: {' + '.join(agent_names) or '(none)'} — Reason: {plan.get('why','')} (complexity={complexity}, conf={plan.get('confidence', 0):.2f})"
        from models import AgentTrace
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
