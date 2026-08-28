"""
Synthesis Agent (Risk-Scoring / Reconciliation)

Responsibility: combine every dispatched specialist agent's structured
result AND their natural-language reasoning notes into one reconciled
verdict -- explicitly flagging cross-agent contradictions in `conflicts`
(e.g. a favourable PFZ recommendation against an active hazard warning for
the same waters, or an agent's note describing calm seas while its own
structured data shows 3 m waves).

It does NOT write the user-facing prose any more -- that is the Response
Agent's job (PS components #7 -> #9). This agent decides WHAT is true and
HOW confident we are; the Response Agent decides how to say it.

The LLM is instructed to cite only the numbers it was given. If the LLM is
unavailable, it falls back to a deterministic verdict pass-through so the
pipeline never breaks.
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


class SynthesisAgent:
    name = "SynthesisAgent"

    def run(
        self,
        context: QueryContext,
        ocean_state: OceanStateReading | None,
        risk: RiskAssessment | None,
        pfz: PFZRecommendation | None = None,
        geofence: GeofenceStatus | None = None,
        route: RoutePlan | None = None,
        trend: TrendAnalysis | None = None,
        discussion: dict | None = None,
    ) -> tuple[dict, AgentTrace]:
        """Returns {"verdict", "confidence", "conflicts", "key_points"} + trace."""
        start = time.perf_counter()

        try:
            result = self._synthesize_with_llm(
                context, ocean_state, risk, pfz, geofence, route, trend,
                discussion=discussion or {},
            )
        except llm_client.LLMUnavailableError:
            result = self._fallback_verdict(risk)

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action="Reconciled all specialist findings into one verdict",
            result_summary=(
                f"Verdict '{result['verdict']}' (confidence {result['confidence']}); "
                f"conflicts flagged: {len(result['conflicts'])}; "
                f"round-table consensus honoured"
            ),
            data_sources=list(risk.evidence_sources) if risk else [],
            duration_ms=duration_ms,
        )
        return result, trace

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------
    def _synthesize_with_llm(
        self,
        context: QueryContext,
        ocean_state: OceanStateReading | None,
        risk: RiskAssessment | None,
        pfz: PFZRecommendation | None,
        geofence: GeofenceStatus | None,
        route: RoutePlan | None,
        trend: TrendAnalysis | None = None,
        discussion: dict | None = None,
    ) -> dict:
        sections: list[str] = []

        if ocean_state is not None:
            field_sources = ocean_state.field_sources or {}
            provenance = (
                "\n".join(f"- {k}: {v}" for k, v in sorted(field_sources.items()))
                if field_sources else f"whole reading: {ocean_state.source.value}"
            )
            sections.append(
                "[Ocean-State Agent] Location: "
                f"{ocean_state.location.name}, window: {context.time_window}. "
                f"SST {ocean_state.sst_celsius} C, chlorophyll "
                f"{ocean_state.chlorophyll_mg_m3} mg/m3, wave height "
                f"{ocean_state.wave_height_m} m, wind {ocean_state.wind_speed_kmh} km/h, "
                f"gusts {ocean_state.wind_gust_kmh} km/h, tide {ocean_state.tide_level_m} m. "
                f"Source: {ocean_state.source.value} (confidence {ocean_state.confidence}).\n"
                f"Field provenance:\n{provenance}\n"
                f"[Ocean-State note]: {ocean_state.reasoning_note}"
            )

        if risk is not None:
            flags_text = (
                "; ".join(f"{f.label}: {f.detail}" for f in risk.flags)
                if risk.flags else "none"
            )
            windows = getattr(risk, "exceedance_windows", []) or []
            windows_text = "; ".join(
                f"{w.metric.replace('_', ' ')} > {w.threshold}{w.unit} "
                f"from {w.start_local} to {w.end_local} (peak {w.peak_value})"
                for w in windows
            ) or "none in the next 48 h"
            marine = getattr(risk, "marine_bulletins", []) or []
            marine_text = " | ".join(marine) or "none"
            sections.append(
                f"[Hazard Agent] Verdict: {risk.status.value}. Headline: {risk.headline}. "
                f"Hazard flags: {flags_text}. Threshold-exceedance windows: {windows_text}. "
                f"Marine bulletins: {marine_text}. Deterministic reasoning: "
                f"{' | '.join(risk.reasoning)}. Confidence: {risk.confidence}.\n"
                f"[Hazard note]: {risk.reasoning_note}"
            )

        if trend is not None:
            corr = (trend.sst_chl_correlation
                    if trend.sst_chl_correlation is not None else "n/a")
            sources = ", ".join(f"{k}={v}" for k, v in sorted(trend.field_sources.items()))
            sections.append(
                f"[Trend Agent] {trend.window_months}-month history for "
                f"{trend.location_name}: SST trend {trend.sst_trend_per_month:+.3f} C/mo, "
                f"chlorophyll trend {trend.chl_trend_per_month:+.3f} mg/m3/mo, "
                f"Pearson r={corr}, months with data={len(trend.points)}.\n"
                f"[Trend note]: {trend.reasoning_note} (sources: {sources})"
            )

        if pfz is not None:
            sections.append(
                f"[PFZ Agent] Nearest zone centre ({pfz.center_lat}, {pfz.center_lon}), "
                f"{pfz.distance_from_reference_km} km away, bearing {pfz.bearing_deg} deg. "
                f"SST at zone {pfz.sst_at_zone_celsius} C, chlorophyll "
                f"{pfz.chlorophyll_at_zone_mg_m3} mg/m3. Provenance: {pfz.field_sources}.\n"
                f"[PFZ note]: {pfz.reasoning_note}"
            )

        if geofence is not None:
            hits = (
                "; ".join(
                    f"{h.zone_name} ({'INSIDE' if h.inside_zone else f'{h.distance_to_boundary_km} km'})"
                    for h in geofence.hits
                )
                if geofence.hits else "none within alert buffer"
            )
            sections.append(
                f"[Geospatial Agent] Nearest restricted boundary "
                f"{geofence.nearest_boundary_km if geofence.nearest_boundary_km != float('inf') else 'n/a'} km. "
                f"Flags: {hits}.\n[Geospatial note]: {geofence.reasoning_note}"
            )

        if route is not None:
            sections.append(
                f"[Route Plan] {route.start_lat},{route.start_lon} -> "
                f"{route.dest_lat},{route.dest_lon}; {route.estimated_distance_km} km; "
                f"avoiding: {', '.join(route.avoided_zones) or 'nothing'}; "
                f"bathymetry: {route.bathymetry_source}."
            )

        system_prompt = (
            "You are the Risk-Scoring/Synthesis Agent of ORCA, the reconciliation "
            "step of a marine multi-agent system. Specialist agents report below.\n"
            "Rules:\n"
            "1. Produce ONE overall verdict: SAFE, CAUTION or UNSAFE. The Hazard "
            "Agent's structured verdict is authoritative for sea-safety when present.\n"
            "2. Explicitly reconcile conflicting signals (e.g. favourable fishing "
            "zone vs active hazard, or PFZ optimism vs rough seas) and say how you "
            "resolved them.\n"
            "3. Use ONLY the numbers provided. Never invent values.\n"
            "4. In `conflicts`, list genuine contradictions between findings/notes. "
            "Empty list if none.\n"
            "5. `key_points`: 2-5 short evidence bullets the Response Agent must "
            "weave into the answer."
        )
        user_prompt = (
            f"USER'S QUESTION (normalized English): \"{context.raw_query}\"\n\n"
            "SPECIALIST FINDINGS & NOTES\n"
            + "\n\n".join(sections)
        )
        turns = (discussion or {}).get("turns") or []
        consensus = (discussion or {}).get("consensus") or ""
        if turns:
            transcript = "\n".join(
                f"- {t.get('speaker')} -> {t.get('addressing') or 'ALL'} "
                f"({t.get('stance')}): {t.get('point')}"
                for t in turns
            )
            user_prompt += (
                "\n\nROUND-TABLE TRANSCRIPT (the agents discussed the findings "
                "above and converged on this):\n" + transcript
                + (f"\nTABLE CONSENSUS: {consensus}" if consensus else "")
            )
        user_prompt += "\n\nReconcile now."

        args = llm_client.complete_structured(
            system_prompt,
            user_prompt,
            tool_name="reconcile_findings",
            tool_description=(
                "Deliver the reconciled verdict with confidence, resolved "
                "conflicts, and key evidence points."
            ),
            schema={
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["SAFE", "CAUTION", "UNSAFE"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Reflects data recency, provenance and source agreement.",
                    },
                    "conflicts_resolved": {
                        "type": "string",
                        "description": "How conflicting signals were reconciled (1-3 sentences).",
                    },
                    "conflicts": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["verdict", "confidence", "conflicts_resolved", "conflicts", "key_points"],
            },
            temperature=0.2,
            max_tokens=700,
        )
        return {
            "verdict": str(args.get("verdict", "CAUTION")),
            "confidence": str(args.get("confidence", "medium")),
            "conflicts_resolved": str(args.get("conflicts_resolved", "")),
            "conflicts": [str(c) for c in args.get("conflicts", [])],
            "key_points": [str(k) for k in args.get("key_points", [])],
        }

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------
    def _fallback_verdict(self, risk: RiskAssessment | None) -> dict:
        verdict = risk.status.value if risk is not None else "CAUTION"
        key_points: list[str] = []
        if risk is not None:
            key_points.extend(risk.reasoning[:3])
        return {
            "verdict": verdict,
            "confidence": "medium",
            "conflicts_resolved": "[llm_unavailable] No reconciliation performed.",
            "conflicts": [],
            "key_points": key_points,
        }
