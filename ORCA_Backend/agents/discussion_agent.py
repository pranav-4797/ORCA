"""
Discussion Agent (round-table moderator)

Sits between the specialist dispatch and the Synthesis Agent. Instead of
letting every specialist report in isolation, this agent hands each one's
findings AND reasoning notes to all the others and generates a moderated
multi-turn transcript in which the agents directly address one another:
challenging numbers, defending their own data, conceding points, and
converging on a shared reading of the situation.

The transcript is NOT free-form chatter: every turn is structured as
    {speaker, addressing, stance, point}
where stance is one of "challenge" | "clarify" | "agree" | "concede".
The LLM may only cite numbers that appear in the specialists' findings.

If the LLM is unavailable, a deterministic transcript is built from the
actual findings (flagged [llm_unavailable]) so the pipeline never breaks.
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

_STANCES = ("challenge", "clarify", "agree", "concede")


class DiscussionAgent:
    name = "DiscussionAgent"

    def run(
        self,
        context: QueryContext,
        ocean_state: OceanStateReading | None = None,
        risk: RiskAssessment | None = None,
        pfz: PFZRecommendation | None = None,
        geofence: GeofenceStatus | None = None,
        route: RoutePlan | None = None,
        trend: TrendAnalysis | None = None,
    ) -> tuple[list[dict], AgentTrace]:
        """Returns {"turns": [...], "consensus": str}-shaped dict list + trace."""
        start = time.perf_counter()

        present = self._participants(ocean_state, risk, pfz, geofence, trend)
        try:
            turns, consensus = self._discuss_with_llm(
                context, ocean_state, risk, pfz, geofence, trend, present
            )
        except llm_client.LLMUnavailableError:
            turns, consensus = self._fallback_discussion(
                ocean_state, risk, pfz, geofence, trend
            )

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action=(
                f"Moderated round-table between {len(present)} agents "
                f"({', '.join(a.replace(' Agent', '') for a in present)})"
            ),
            result_summary=(
                f"{len(turns)} exchanges; consensus: {consensus[:140]}"
            ),
            data_sources=[],
            duration_ms=duration_ms,
        )
        return {"turns": turns, "consensus": consensus}, trace

    # ------------------------------------------------------------------
    def _participants(self, *results) -> list[str]:
        names = []
        labels = [
            "Ocean-State Agent", "Hazard Agent", "PFZ Agent",
            "Geospatial Agent", "Trend Agent",
        ]
        for label, res in zip(labels, results):
            if res is not None:
                names.append(label)
        return names or ["Ocean-State Agent"]

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------
    def _discuss_with_llm(
        self,
        context: QueryContext,
        ocean_state,
        risk,
        pfz,
        geofence,
        trend,
        present: list[str],
    ) -> tuple[list[dict], str]:
        sections: list[str] = []

        if ocean_state is not None:
            sections.append(
                "[Ocean-State Agent] SST "
                f"{ocean_state.sst_celsius} C, chlorophyll "
                f"{ocean_state.chlorophyll_mg_m3} mg/m3, waves "
                f"{ocean_state.wave_height_m} m, wind "
                f"{ocean_state.wind_speed_kmh} km/h (gusts "
                f"{ocean_state.wind_gust_kmh} km/h), tide "
                f"{ocean_state.tide_level_m} m at {ocean_state.location.name}. "
                f"Provenance: {ocean_state.source.value}.\n"
                f"My note: {ocean_state.reasoning_note}"
            )
        if risk is not None:
            flags_text = (
                "; ".join(f"{f.label}: {f.detail}" for f in risk.flags)
                if risk.flags else "none"
            )
            sections.append(
                f"[Hazard Agent] Verdict: {risk.status.value}. Headline: "
                f"{risk.headline}. Flags: {flags_text}. Confidence: "
                f"{risk.confidence}.\nMy note: {risk.reasoning_note}"
            )
        if trend is not None:
            corr = (trend.sst_chl_correlation
                    if trend.sst_chl_correlation is not None else "n/a")
            sections.append(
                f"[Trend Agent] {trend.window_months}-month trends at "
                f"{trend.location_name}: SST {trend.sst_trend_per_month:+.3f} "
                f"C/mo, chlorophyll {trend.chl_trend_per_month:+.3f} mg/m3/mo, "
                f"Pearson r={corr}.\nMy note: {trend.reasoning_note}"
            )
        if pfz is not None:
            sections.append(
                f"[PFZ Agent] Recommends zone centre ({pfz.center_lat}, "
                f"{pfz.center_lon}), {pfz.distance_from_reference_km} km away "
                f"bearing {pfz.bearing_deg} deg. SST there "
                f"{pfz.sst_at_zone_celsius} C, chlorophyll "
                f"{pfz.chlorophyll_at_zone_mg_m3} mg/m3.\n"
                f"My note: {pfz.reasoning_note}"
            )
        if geofence is not None:
            hits = (
                "; ".join(
                    f"{h.zone_name} ({'INSIDE' if h.inside_zone else f'{h.distance_to_boundary_km} km off'})"
                    for h in geofence.hits
                )
                if geofence.hits else "no boundary within alert buffer"
            )
            sections.append(
                f"[Geospatial Agent] Boundary check: {hits}.\n"
                f"My note: {geofence.reasoning_note}"
            )

        system_prompt = (
            "You moderate a round-table discussion between ORCA's marine "
            "specialist agents BEFORE the system answers the user. Each agent "
            "has reported findings below.\n"
            "Rules:\n"
            "1. Write 4-8 SHORT turns where the agents talk TO each other: "
            "challenge each other's numbers when they tension (e.g. PFZ "
            "optimism vs Hazard warnings), clarify provenance, defend data, "
            "or explicitly concede/adjust their position.\n"
            "2. Every turn MUST use a speaker from this exact list: "
            f"{present}. 'addressing' names the agent being spoken to "
            "(or null for the whole table).\n"
            "3. stance is one of: challenge, clarify, agree, concede.\n"
            "4. Cite ONLY figures that appear in the findings. No new data, "
            "no pleasantries -- substantive points only (max ~35 words each).\n"
            "5. End with `consensus`: 1-2 sentences stating what the table "
            "agreed on for the user's question."
        )
        user_prompt = (
            f"USER'S QUESTION (normalized English): \"{context.raw_query}\"\n\n"
            "AGENT FINDINGS & NOTES\n"
            + "\n\n".join(sections)
            + "\n\nRun the round-table now."
        )

        args = llm_client.complete_structured(
            system_prompt,
            user_prompt,
            tool_name="round_table_transcript",
            tool_description=(
                "Structured transcript of the specialist agents discussing "
                "their findings with each other before reconciliation."
            ),
            schema={
                "type": "object",
                "properties": {
                    "turns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "speaker": {"type": "string"},
                                "addressing": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}],
                                },
                                "stance": {
                                    "type": "string",
                                    "enum": list(_STANCES),
                                },
                                "point": {"type": "string"},
                            },
                            "required": ["speaker", "stance", "point"],
                        },
                    },
                    "consensus": {"type": "string"},
                },
                "required": ["turns", "consensus"],
            },
            temperature=0.3,
            max_tokens=900,
        )

        valid = set(present)
        turns: list[dict] = []
        for t in args.get("turns", []):
            speaker = str(t.get("speaker", "")).strip()
            if speaker not in valid:
                continue  # never let the LLM invent an agent that didn't run
            turns.append({
                "speaker": speaker,
                "addressing": t.get("addressing") or None,
                "stance": t.get("stance") if t.get("stance") in _STANCES else "clarify",
                "point": str(t.get("point", "")).strip(),
            })
        return (
            turns[:10],
            str(args.get("consensus", "")).strip(),
        )

    # ------------------------------------------------------------------
    # Deterministic fallback (no LLM): honest exchange from real findings
    # ------------------------------------------------------------------
    def _fallback_discussion(self, ocean_state, risk, pfz, geofence, trend):
        tag = "[llm_unavailable] "
        turns: list[dict] = []

        if ocean_state is not None:
            turns.append({
                "speaker": "Ocean-State Agent", "addressing": None,
                "stance": "clarify",
                "point": (
                    f"{tag}Measured waves {ocean_state.wave_height_m} m and "
                    f"gusts {ocean_state.wind_gust_kmh} km/h at "
                    f"{ocean_state.location.name}; source "
                    f"{ocean_state.source.value}."
                ),
            })
        if risk is not None and risk.flags:
            turns.append({
                "speaker": "Hazard Agent", "addressing": "Ocean-State Agent",
                "stance": "challenge",
                "point": (
                    f"{tag}Those readings breach thresholds: "
                    + "; ".join(f.label for f in risk.flags[:2])
                    + ". My verdict stands "
                    + risk.status.value + "."
                ),
            })
        if pfz is not None and risk is not None and risk.flags:
            turns.append({
                "speaker": "PFZ Agent", "addressing": "Hazard Agent",
                "stance": "concede",
                "point": (
                    f"{tag}Zone {pfz.distance_from_reference_km} km out still "
                    "shows productive water, but I defer to your verdict for "
                    "timing -- treat it as conditions-permitting only."
                ),
            })
        elif pfz is not None:
            turns.append({
                "speaker": "PFZ Agent", "addressing": None,
                "stance": "clarify",
                "point": (
                    f"{tag}Nearest productive zone {pfz.distance_from_reference_km} km "
                    f"away, bearing {pfz.bearing_deg} deg; no hazard objection raised."
                ),
            })
        if geofence is not None and geofence.hits:
            h = geofence.hits[0]
            turns.append({
                "speaker": "Geospatial Agent", "addressing": "PFZ Agent",
                "stance": "challenge",
                "point": (
                    f"{tag}Note the boundary constraint: {h.zone_name} at "
                    f"{h.distance_to_boundary_km} km -- any recommendation must "
                    "stay clear of it."
                ),
            })
        if trend is not None:
            turns.append({
                "speaker": "Trend Agent", "addressing": None,
                "stance": "clarify",
                "point": (
                    f"{tag}Context over {trend.window_months} months: SST "
                    f"{trend.sst_trend_per_month:+.3f} C/mo, chlorophyll "
                    f"{trend.chl_trend_per_month:+.3f} mg/m3/mo."
                ),
            })

        consensus = (
            f"{tag}Deterministic exchange; final reconciliation follows in "
            "the Synthesis Agent."
        )
        return turns[:8], consensus
