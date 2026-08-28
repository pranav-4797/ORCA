"""
Response Agent (PS component #9)

Takes the Synthesis Agent's reconciled verdict + key evidence points and
composes the single user-facing answer: clear, conversational, with the
reasoning woven in naturally -- NOT raw agent chatter -- and written in the
language detected by the Language/Intent Agent (Indian regional languages
emphasised).

Falls back to a deterministic English template when the LLM is unavailable.
"""

from __future__ import annotations

import time

import llm_client
from models import (
    AgentTrace,
    GeofenceStatus,
    OceanStateReading,
    PFZRecommendation,
    QueryContext,
    RiskAssessment,
    RoutePlan,
    TrendAnalysis,
)

_LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil",
    "te": "Telugu", "bn": "Bengali", "ml": "Malayalam", "kn": "Kannada",
    "gu": "Gujarati", "or": "Odia", "pa": "Punjabi",
}


class ResponseAgent:
    name = "ResponseAgent"

    def run(
        self,
        context: QueryContext,
        synthesis: dict,
        ocean_state: OceanStateReading | None = None,
        risk: RiskAssessment | None = None,
        pfz: PFZRecommendation | None = None,
        geofence: GeofenceStatus | None = None,
        route: RoutePlan | None = None,
        trend: TrendAnalysis | None = None,
        discussion: dict | None = None,
    ) -> tuple[str, AgentTrace]:
        start = time.perf_counter()
        language = context.language or "en"
        lang_name = _LANGUAGE_NAMES.get(language, language)

        try:
            answer = self._compose_with_llm(
                context, synthesis, lang_name, ocean_state, pfz, geofence, route,
                trend, discussion=discussion or {},
            )
        except llm_client.LLMUnavailableError:
            answer = self._fallback_answer(context, synthesis, risk, pfz, geofence, route)

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action=f"Composed final answer in {lang_name}",
            result_summary=f"Answer written ({len(answer)} chars)",
            data_sources=[],
            duration_ms=duration_ms,
        )
        return answer, trace

    # ------------------------------------------------------------------
    def _compose_with_llm(
        self,
        context: QueryContext,
        synthesis: dict,
        lang_name: str,
        ocean_state,
        pfz,
        geofence,
        route,
        trend=None,
        discussion: dict | None = None,
    ) -> str:
        extras = []
        hour_note = (
            f"- The user asked about local hour {context.target_hour}:00; the data "
            "above is for that exact hour."
            if context.target_hour is not None else ""
        )
        if ocean_state is not None:
            # Temporal exceedance windows (P1 #10): cite WHEN it gets bad.
            for w in getattr(ocean_state, "exceedance_windows", []) or []:
                extras.append(
                    f"- Exceedance window: {w.metric.replace('_', ' ')} exceeds "
                    f"{w.threshold}{w.unit} from {w.start_local} to {w.end_local} "
                    f"(peak {w.peak_value}{w.unit})"
                )
            # Tide highs/lows (P1 #14).
            extremes = getattr(ocean_state, "tide_extremes", []) or []
            if extremes:
                tide_txt = ", ".join(
                    f"{e.kind} at {e.time_local[11:16]} ({e.height_m} m)"
                    for e in extremes[:4]
                )
                extras.append(f"- Predicted tides: {tide_txt}")
            # Ranked secondary zones (P1 #12) come via pfz below.
        if pfz is not None:
            extras.append(
                f"- PFZ zone: {pfz.distance_from_reference_km} km away, bearing "
                f"{pfz.bearing_deg} deg, centre ({pfz.center_lat}, {pfz.center_lon}); "
                f"zone position provenance: {pfz.field_sources.get('zone_position', 'simulated')}"
            )
            for i, alt in enumerate(getattr(pfz, "alternates", []) or [], start=2):
                extras.append(
                    f"- Alternative zone #{i}: {alt['distance_km']} km away, bearing "
                    f"{alt['bearing_deg']} deg (SST {alt['sst_celsius']} C)"
                )
        if geofence is not None and not geofence.clear:
            for h in geofence.hits:
                state = "INSIDE" if h.inside_zone else f"{h.distance_to_boundary_km} km from"
                extras.append(f"- Boundary flag: {state} {h.zone_name}")
        if route is not None:
            depth_txt = (
                f"; min depth along path {route.min_depth_m} m"
                if route.min_depth_m is not None else ""
            )
            extras.append(
                f"- Route ({route.algorithm}): {route.estimated_distance_km} km, "
                f"{len(route.waypoints)} waypoints{depth_txt}; bathymetry: "
                f"{route.bathymetry_source}; avoided: "
                f"{', '.join(route.avoided_zones) or 'nothing'}"
            )
        if trend is not None:
            corr = (trend.sst_chl_correlation
                    if trend.sst_chl_correlation is not None else "n/a")
            extras.append(
                f"- Trend analysis ({trend.window_months} months): SST "
                f"{trend.sst_trend_per_month:+.3f} C/month, chlorophyll "
                f"{trend.chl_trend_per_month:+.3f} mg/m3/month, correlation r={corr}."
            )
        if hour_note:
            extras.append(hour_note)

        debate_block = ""
        turns = (discussion or {}).get("turns") or []
        consensus = (discussion or {}).get("consensus") or ""
        if turns:
            transcript = "\n".join(
                f"- {t.get('speaker')} -> {t.get('addressing') or 'ALL'} "
                f"({t.get('stance')}): {t.get('point')}"
                for t in turns
            )
            debate_block = (
                "\nAGENT ROUND-TABLE (the specialists debated before the "
                "verdict was locked):\n" + transcript
                + (f"\nTABLE CONSENSUS: {consensus}" if consensus else "")
                + ("\nIn your final answer, briefly explain how this "
                   "disagreement was settled and what the agents jointly "
                   "concluded, in plain user-facing language.")
            )

        system_prompt = (
            "You are the Response Agent of ORCA, a marine-safety assistant for "
            "Indian coastal users. The specialist agents held a round-table "
            "discussion about their findings, then the Synthesis Agent "
            "reconciled everything; you write the FINAL message the user "
            "reads.\n"
            "Rules:\n"
            "1. Write in "
            f"{lang_name}. Natural, fluent {lang_name} -- never translate word-by-word.\n"
            "2. Weave the reasoning into the prose naturally. Do NOT mention agent "
            "names, 'notes', 'findings', or that agents exist.\n"
            "3. Use ONLY the numbers and place names given below. NEVER introduce "
            "locations, ports, distances or facts that are not listed -- if the "
            "user needs something not provided (e.g. nearest harbour), say it is "
            "not in the current data instead of guessing.\n"
            "4. If you cite a simulated/estimated value, say so explicitly.\n"
            "5. Be ULTRA-concise: 2-4 short sentences (max 70 words). Start with "
            "the verdict and the single decisive reason. No preamble, no bullet "
            "list unless the user asked for zones/route.\n"
            "6. For analytical/trend questions, answer the 'why' in one sentence using only the "
            "trend statistics provided."
        )
        user_prompt = (
            f"USER'S ORIGINAL QUESTION: \"{context.raw_query}\"\n\n"
            f"RECONCILED VERDICT: {synthesis['verdict']} "
            f"(confidence: {synthesis['confidence']})\n"
            f"HOW CONFLICTS WERE RESOLVED: {synthesis['conflicts_resolved']}\n"
            "KEY EVIDENCE POINTS:\n"
            + "\n".join(f"- {k}" for k in synthesis["key_points"])
            + ("\nADDITIONAL CONTEXT:\n" + "\n".join(extras) if extras else "")
            + debate_block
            + "\n\nWrite the final answer now."
        )
        # Optimized: concise answers need few tokens; fast timeout with no retry for latency
        import os
        max_tok = int(os.getenv("LLM_MAX_TOKENS_RESPONSE", "350").strip() or 350)
        timeout = float(os.getenv("LLM_TIMEOUT_FAST_S", "7").strip() or 7)
        return llm_client.complete(
            system_prompt, user_prompt, temperature=0.4, max_tokens=max_tok,
            timeout=timeout, attempts=1
        )

    # ------------------------------------------------------------------
    def _fallback_answer(self, context, synthesis, risk, pfz, geofence, route) -> str:
        parts = [f"Verdict: {synthesis['verdict']}"]
        if risk is not None:
            parts.append(risk.headline)
        if pfz is not None:
            parts.append(
                f"Nearest simulated fishing zone ~{pfz.distance_from_reference_km} km "
                f"at bearing {pfz.bearing_deg:.0f} deg."
            )
        if geofence is not None and not geofence.clear:
            parts.append("Restricted boundary nearby: " + "; ".join(h.zone_name for h in geofence.hits))
        if route is not None:
            parts.append(f"Suggested route {route.estimated_distance_km} km avoiding flagged zones.")
        parts.append("[llm_unavailable] Template response.")
        return " ".join(parts)
