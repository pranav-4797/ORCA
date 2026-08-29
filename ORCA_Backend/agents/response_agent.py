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
from agents.pfz_output import format_pfz_answer, is_pfz_lookup_query
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

        # Official-PFZ lookups get the documented INCOIS template verbatim
        # (deterministic, no LLM needed for distance/bearing/coords facts).
        official_pfz = None
        if pfz is not None and is_pfz_lookup_query(context.raw_query):
            official_pfz = format_pfz_answer(
                pfz, verdict=(synthesis or {}).get("verdict", "CAUTION")
            )

        if official_pfz is not None:
            answer = official_pfz
        else:
            try:
                answer = self._compose_with_llm(
                    context, synthesis, lang_name, ocean_state, pfz, geofence, route,
                    trend, discussion=discussion or {},
                )
                # Guard: LLM sometimes returns a generic 30-token template without
                # quoting the live numbers we just injected. Detect and patch.
                if ocean_state is not None and ("km/h" not in answer or "°C" not in answer):
                    patch = self._fallback_answer(
                        context, synthesis, risk, pfz, geofence, route, ocean_state
                    )
                    if "km/h" in patch or "°C" in patch:
                        answer = answer.rstrip() + "\n\n" + patch
                # Readability guard: if LLM crammed everything into one line, reformat
                if ("Wind:" in answer or "SST:" in answer) and answer.count("\n") < 3:
                    import re
                    if "|" not in answer:
                        answer = re.sub(r"\s*(Wind:\s*[\d.]+[^,\n]*)\s*", r"\n- \1", answer)
                        answer = re.sub(r"\s*(Waves?:\s*[\d.]+[^,\n]*)\s*", r"\n- \1", answer)
                        answer = re.sub(r"\s*(SST:\s*[\d.]+[^\n]*)\s*", r"\n- \1", answer)
                        answer = re.sub(r"\s*(Source:\s*Official[^\n]*)\s*", r"\n\n*\1*", answer)
                        answer = re.sub(r"(Verdict:\s*CAUTION[^\n]*)(?=\s*-)", r"\1\n", answer)
                        answer = re.sub(r"(Verdict:\s*SAFE[^\n]*)(?=\s*-)", r"\1\n", answer)
                        answer = re.sub(r"(Verdict:\s*UNSAFE[^\n]*)(?=\s*-)", r"\1\n", answer)
                    # If still single paragraph with Verdict + Weather Forecast, split verdict from data
                    if "Weather Forecast" in answer and answer.count("\n") < 3:
                        answer = answer.replace("Weather Forecast", "\n### 🌊 Marine Conditions\n*Weather Forecast*")
                    answer = answer.strip()
                    if not answer.startswith("###") and not answer.startswith("**"):
                        # Promote verdict to heading
                        answer = re.sub(r"^Verdict:\s*CAUTION", "### 🟠 CAUTION", answer)
                        answer = re.sub(r"^Verdict:\s*SAFE", "### 🟢 SAFE", answer)
                        answer = re.sub(r"^Verdict:\s*UNSAFE", "### 🔴 UNSAFE", answer)
            except llm_client.LLMUnavailableError:
                answer = self._fallback_answer(
                    context, synthesis, risk, pfz, geofence, route, ocean_state
                )

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
            loc_name = getattr(getattr(ocean_state, "location", None), "name", "") or "this point"
            fs = getattr(ocean_state, "field_sources", {}) or {}
            src_val = getattr(getattr(ocean_state, "source", None), "value", "") or "live"
            def _have(field: str) -> bool:
                return str(fs.get(field, "")) != "unavailable"
            # Query-aware: only expose fields the user asked for to the LLM
            _rq = (getattr(context, "raw_query", "") or "").lower()
            _sst_kw = any(k in _rq for k in ("sst","sea surface temp","sea temp","temperature"))
            _wind_kw = any(k in _rq for k in ("wind","gust"))
            _wave_kw = any(k in _rq for k in ("wave","swell","surf"))
            _curr_kw = any(k in _rq for k in ("current","currents"))
            _chl_kw = any(k in _rq for k in ("chlorophyll","chl","productivity"))
            _tide_kw = any(k in _rq for k in ("tide","tidal"))
            _spec = _sst_kw or _wind_kw or _wave_kw or _curr_kw or _chl_kw or _tide_kw
            def _want2(f: str) -> bool:
                if not _spec: return True
                mm = {"sst_celsius": _sst_kw, "wind_speed_kmh": _wind_kw, "wave_height_m": _wave_kw, "primary_swell_height_m": _wave_kw, "surface_current_mps": _curr_kw, "chlorophyll_mg_m3": _chl_kw, "tide_level_m": _tide_kw}
                return mm.get(f, True)
            _fields: list[str] = []
            if _want2("wind_speed_kmh") and _have("wind_speed_kmh") and ocean_state.wind_speed_kmh is not None:
                _fields.append(f"Wind {ocean_state.wind_speed_kmh} km/h")
                _wdir = getattr(ocean_state, "wind_direction", None)
                if _wdir:
                    _fields.append(f"direction {_wdir}")
            if _want2("wave_height_m") and _have("wave_height_m") and ocean_state.wave_height_m is not None:
                _fields.append(f"waves {ocean_state.wave_height_m} m")
            if _want2("primary_swell_height_m") and _have("primary_swell_height_m") and getattr(ocean_state, "primary_swell_height_m", None) is not None:
                _fields.append(f"swell {ocean_state.primary_swell_height_m} m")
            if _want2("sst_celsius") and _have("sst_celsius") and ocean_state.sst_celsius is not None:
                _fields.append(f"SST {ocean_state.sst_celsius} °C")
            if _want2("chlorophyll_mg_m3") and _have("chlorophyll_mg_m3") and ocean_state.chlorophyll_mg_m3 is not None:
                _fields.append(f"chlorophyll {ocean_state.chlorophyll_mg_m3} mg/m³")
            if _want2("tide_level_m") and _have("tide_level_m") and ocean_state.tide_level_m is not None:
                _fields.append(f"tide {ocean_state.tide_level_m} m")
            if _fields:
                extras.append(
                    f"- Live ocean conditions at {loc_name}: "
                    + ", ".join(_fields)
                    + (f" (overall source: {src_val})" if src_val else "")
                )
                if src_val == "live" or any(v == "live" for v in fs.values()):
                    extras.append("- Data provenance: Official INCOIS Ocean State Forecast + OceanSat-2 + Gemini PFZ (live)")
            else:
                extras.append(f"- No live marine values are currently available at {loc_name} (INCOIS unavailable).")
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
            lc_txt = ""
            lc = getattr(pfz, "landing_center", None) or {}
            if lc:
                lc_txt = (
                    f" official INCOIS advisory via landing centre "
                    f"{lc.get('name')} (sector {lc.get('sector_id')}); zone "
                    f"{lc.get('advisory_distance_km')} km to the "
                    f"{lc.get('direction')}, depth {lc.get('advisory_depth_m')} m, "
                    f"valid {lc.get('forecast_date')} to {lc.get('valid_upto')}"
                )
                if pfz.advisory_text:
                    lc_txt += f"; sector note: {pfz.advisory_text[:220]}"
            extras.append(
                f"- PFZ zone: {pfz.distance_from_reference_km} km away, bearing "
                f"{pfz.bearing_deg} deg, centre ({pfz.center_lat}, {pfz.center_lon});"
                f"{lc_txt or ' zone position provenance: ' + pfz.field_sources.get('zone_position', 'simulated')}"
            )
            for i, alt in enumerate(getattr(pfz, "alternates", []) or [], start=2):
                extras.append(
                    f"- Alternative zone #{i}: {alt['distance_km']} km away, bearing "
                    f"{alt['bearing_deg']} deg"
                    + (f" (SST {alt['sst_celsius']} C)" if 'sst_celsius' in alt else "")
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

        # Query-aware: only include parameters the user asked about (SST vs wind vs all)
        _rq = (context.raw_query or "").lower()
        _specific = any(k in _rq for k in ("sst","wind","wave","swell","current","chlorophyll","chl","tide","sst "))
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
            "5. FORMAT for readability (MANDATORY — do not output a single paragraph):\n"
            "   - Start with a ONE-LINE verdict bold, e.g. **🟠 CAUTION — Borderline conditions**.\n"
            "   - Then a section '### 🌊 Marine Conditions — <location> (<time>)' with 📍 coordinates if provided.\n"
            "   - Under that, a markdown TABLE with Parameter | Value rows, e.g.:\n"
            "     | Parameter | Value |\n"
            "     |---|---|\n"
            "     | 🌡️ SST | **28.5°C** |\n"
            "     | 💨 Wind | **31 km/h** |\n"
            "   - CRITICAL: Only include rows for parameters the user asked about. "
            "If they asked 'sst' show ONLY SST. If 'wind' show ONLY wind. If they asked generically (ocean/marine/weather/conditions) show all available rows.\n"
            "   - After the table, a 1-sentence actionable recommendation on its own line.\n"
            "   - End with '*Source: Official INCOIS Ocean State Forecast + OceanSat-2 + Gemini PFZ*' italic line.\n"
            "   - Total length: 80-150 words. Never cram everything into one line.\n"
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
        # Structured answers need slightly more room than 70-word walls of text
        import os
        max_tok = int(os.getenv("LLM_MAX_TOKENS_RESPONSE", "600").strip() or 600)
        timeout = float(os.getenv("LLM_TIMEOUT_FAST_S", "7").strip() or 7)
        return llm_client.complete(
            system_prompt, user_prompt, temperature=0.4, max_tokens=max_tok,
            timeout=timeout, attempts=1
        )

    # ------------------------------------------------------------------
    def _fallback_answer(self, context, synthesis, risk, pfz, geofence, route, ocean_state=None) -> str:
        verdict = synthesis.get('verdict', 'CAUTION') if isinstance(synthesis, dict) else getattr(synthesis, 'verdict', 'CAUTION')
        risk_headline = risk.headline if risk else ""
        # Map verdict to readable heading
        verdict_icon = {"SAFE": "🟢 SAFE", "CAUTION": "🟠 CAUTION", "UNSAFE": "🔴 UNSAFE"}.get(verdict, verdict)
        parts = [f"### {verdict_icon} — {risk_headline or verdict}"]

        ocean = ocean_state
        if ocean is not None:
            loc = getattr(ocean, "location", None)
            loc_name = getattr(loc, "name", "") if loc else ""
            tw = getattr(context, "time_window", "today") or "today"
            coord = ""
            if loc and getattr(loc, "lat", None) is not None:
                coord = f"📍 {loc.lat:.4f}°N, {loc.lon:.4f}°E"
            fs = getattr(ocean, "field_sources", {}) or {}
            rq = (getattr(context, "raw_query", "") or "").lower()
            sst_kw = any(k in rq for k in ("sst","sea surface temp","sea temp","temperature"))
            wind_kw = any(k in rq for k in ("wind","gust"))
            wave_kw = any(k in rq for k in ("wave","swell","surf"))
            curr_kw = any(k in rq for k in ("current","currents"))
            chl_kw = any(k in rq for k in ("chlorophyll","chl","productivity"))
            tide_kw = any(k in rq for k in ("tide","tidal"))
            specific = sst_kw or wind_kw or wave_kw or curr_kw or chl_kw or tide_kw
            def _want(f: str) -> bool:
                if not specific: return True
                m = {"sst_celsius": sst_kw, "wind_speed_kmh": wind_kw, "wind_gust_kmh": wind_kw, "wave_height_m": wave_kw, "primary_swell_height_m": wave_kw, "surface_current_mps": curr_kw, "chlorophyll_mg_m3": chl_kw, "tide_level_m": tide_kw, "tide_extremes": tide_kw}
                return m.get(f, False)
            rows: list[str] = []
            if _want("sst_celsius") and getattr(ocean, "sst_celsius", None) is not None and str(fs.get("sst_celsius","")) != "unavailable":
                rows.append(f"| 🌡️ SST | **{ocean.sst_celsius}°C** |")
            if _want("wind_speed_kmh") and getattr(ocean, "wind_speed_kmh", None) is not None and str(fs.get("wind_speed_kmh","")) != "unavailable":
                wdir = getattr(ocean, "wind_direction", "") or ""
                rows.append(f"| 💨 Wind | **{ocean.wind_speed_kmh} km/h {wdir}** |".strip())
            if _want("wave_height_m") and getattr(ocean, "wave_height_m", None) is not None and str(fs.get("wave_height_m","")) != "unavailable":
                rows.append(f"| 🌊 Waves | **{ocean.wave_height_m} m** |")
            elif _want("primary_swell_height_m") and getattr(ocean, "primary_swell_height_m", None) is not None and str(fs.get("primary_swell_height_m","")) != "unavailable":
                rows.append(f"| 🌊 Swell | **{ocean.primary_swell_height_m} m** |")
            cur = getattr(ocean, "surface_current_mps", None)
            if _want("surface_current_mps") and cur is not None and str(fs.get("surface_current_mps","")) != "unavailable":
                rows.append(f"| 🌊 Current | **{cur} m/s** |")
            if _want("chlorophyll_mg_m3") and getattr(ocean, "chlorophyll_mg_m3", None) is not None and str(fs.get("chlorophyll_mg_m3","")) != "unavailable":
                rows.append(f"| 🟢 Chlorophyll | **{ocean.chlorophyll_mg_m3} mg/m³** |")
            extremes = getattr(ocean, "tide_extremes", []) or []
            if extremes:
                tide_txt = ", ".join(f"{e.kind} at {e.time_local[11:16]} ({e.height_m} m)" for e in extremes[:4])
                rows.append(f"| 🌗 Tide | {tide_txt} |")
            elif getattr(ocean, "tide_level_m", None) is not None and str(fs.get("tide_level_m","")) != "unavailable":
                rows.append(f"| 🌗 Tide | {ocean.tide_level_m} m |")
            if rows:
                block = f"### 🌊 Marine Conditions — {loc_name or 'Selected Location'} ({tw})"
                if coord:
                    block += f"  \n{coord}"
                block += "\n\n| Parameter | Value |\n|---|---|\n" + "\n".join(rows)
                parts.append(block)
                parts.append("*Source: Official INCOIS Ocean State Forecast + OceanSat-2 + Gemini PFZ*")
            else:
                parts.append(f"_{loc_name or 'Selected Location'} ({tw}): Live INCOIS value unavailable._")

        if pfz is not None:
            lc = getattr(pfz, "landing_center", None) or {}
            if lc:
                parts.append(
                    f"Official INCOIS PFZ via {lc.get('name')}: zone "
                    f"{lc.get('advisory_distance_km')} km to the {lc.get('direction')}, "
                    f"depth {lc.get('advisory_depth_m')} m; "
                    f"~{pfz.distance_from_reference_km} km from your point "
                    f"at bearing {pfz.bearing_deg:.0f} deg."
                )
            else:
                parts.append(
                    f"Nearest {'derived' if pfz.source.value == 'derived_from_live_data' else 'simulated'} "
                    f"fishing zone ~{pfz.distance_from_reference_km} km at bearing "
                    f"{pfz.bearing_deg:.0f} deg."
                )
        if geofence is not None and not geofence.clear:
            parts.append("Restricted boundary nearby: " + "; ".join(h.zone_name for h in geofence.hits))
        if route is not None:
            parts.append(f"Suggested route {route.estimated_distance_km} km avoiding flagged zones.")
        return "\n\n".join(parts)
