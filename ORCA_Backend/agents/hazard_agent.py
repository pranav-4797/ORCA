"""
Hazard Agent (a.k.a. Risk Assessment Agent)

Responsibility: take an OceanStateReading and turn it into a safety verdict
with explicit reasoning -- this is where "why" comes from, not just "what".

Thresholds below are the same ones defined in the roadmap (Phase 3.1),
tuned against small-fishing-vessel safety guidance. They are intentionally
centralized in one place (THRESHOLDS) so they can be cited directly in a
pitch/Q&A and adjusted without touching the evaluation logic.
"""

from __future__ import annotations
import json
import logging
import os
import time

import data_connectors.imd_cap as imd_cap
import data_connectors.imd_live as imd_live
import llm_client
from models import (
    AgentTrace,
    DataSource,
    HazardFlag,
    OceanStateReading,
    RiskAssessment,
    SafetyStatus,
)

THRESHOLDS = {
    "wave_height_unsafe_m": 2.5,
    "wave_height_caution_m": 1.5,
    "wind_gust_unsafe_kmh": 45.0,
    "wind_gust_caution_kmh": 30.0,
}

# Per-vessel-class safety envelopes (PDF NFR: thresholds must reflect the
# craft, not one hypothetical boat). Env override:
#   ORCA_THRESHOLD_OVERRIDES={"mechanized_trawler":{"wave_height_unsafe_m":4.0}}
VESSEL_CLASSES = {
    "small_fishing_boat": dict(THRESHOLDS),
    "mechanized_trawler": {
        "wave_height_unsafe_m": 3.5,
        "wave_height_caution_m": 2.25,
        "wind_gust_unsafe_kmh": 55.0,
        "wind_gust_caution_kmh": 38.0,
    },
    "coastal_cargo": {
        "wave_height_unsafe_m": 4.5,
        "wave_height_caution_m": 3.0,
        "wind_gust_unsafe_kmh": 65.0,
        "wind_gust_caution_kmh": 45.0,
    },
}


def get_thresholds(vessel_class: str | None) -> dict:
    """Resolved threshold set for a vessel class (env overrides applied)."""
    key = (vessel_class or "small_fishing_boat").strip().lower()
    thr = dict(VESSEL_CLASSES.get(key, THRESHOLDS))
    overrides = os.getenv("ORCA_THRESHOLD_OVERRIDES", "").strip()
    if overrides:
        try:
            patch = json.loads(overrides).get(key, {})
            thr.update({k: float(v) for k, v in patch.items()})
        except (ValueError, TypeError, AttributeError):
            logging.getLogger("orca.hazard").warning(
                "ignoring malformed ORCA_THRESHOLD_OVERRIDES")
    return thr


class HazardAgent:
    name = "HazardAgent"

    def run(self, ocean_state: OceanStateReading,
            vessel_class: str = "small_fishing_boat") -> tuple[RiskAssessment, AgentTrace]:
        start = time.perf_counter()
        thr = get_thresholds(vessel_class)

        flags: list[HazardFlag] = []
        reasoning: list[str] = []

        # --- Wave height check ---
        if ocean_state.wave_height_m > thr["wave_height_unsafe_m"]:
            flags.append(HazardFlag(
                label="High wave height",
                detail=f"{ocean_state.wave_height_m} m forecast",
                threshold_crossed=(
                    f"> {thr['wave_height_unsafe_m']} m "
                    f"(unsafe for {vessel_class.replace('_', ' ')})"
                ),
            ))
        elif ocean_state.wave_height_m > thr["wave_height_caution_m"]:
            reasoning.append(
                f"Wave height {ocean_state.wave_height_m} m is moderate "
                f"(caution range starts at {thr['wave_height_caution_m']} m)"
            )
        else:
            reasoning.append(f"Wave height {ocean_state.wave_height_m} m is within normal range")

        # --- Wind gust check ---
        if ocean_state.wind_gust_kmh > thr["wind_gust_unsafe_kmh"]:
            flags.append(HazardFlag(
                label="High wind gusts",
                detail=f"{ocean_state.wind_gust_kmh} km/h forecast",
                threshold_crossed=f"> {thr['wind_gust_unsafe_kmh']} km/h (unsafe threshold)",
            ))
        elif ocean_state.wind_gust_kmh > thr["wind_gust_caution_kmh"]:
            reasoning.append(
                f"Wind gusts {ocean_state.wind_gust_kmh} km/h are moderate "
                f"(caution range starts at {thr['wind_gust_caution_kmh']} km/h)"
            )
        else:
            reasoning.append(f"Wind gusts {ocean_state.wind_gust_kmh} km/h are within normal range")

        # --- Live IMD CAP checks (Tier 1, keyless feed, ONE fetch) ---
        # The same fetched alert list feeds three checks: cyclone/depression,
        # fishermen/marine bulletins (squally wind, rough seas...), and
        # thunderstorm/lightning events. Location-aware zone coverage:
        # "affects this area" vs "active elsewhere" -- any covering polygon
        # forces UNSAFE. Unreachable feed = UNVERIFIED, never silently clear.
        cyclone_note = ""
        cyclone_evidence: list[DataSource] = []
        cap_polygons: list[dict] = []
        marine_lines: list[str] = []

        def _try_imd_live_fallback():
            """Secondary source when CAP is down. Returns
            (state, note, evidence) with state 'unverifiable' on failure."""
            try:
                fb = imd_live.fetch_cyclone_status()
            except imd_live.ImdUnavailableError as exc:
                note = (
                    "Live cyclone feeds were UNREACHABLE (CAP: unavailable; "
                    f"api.imd.gov.in: {exc}) -- cyclone risk could not be "
                    "verified and is treated as unknown, not clear."
                )
                reasoning.append(
                    "Cyclone status could NOT be verified -- live feeds "
                    "unreachable. Cyclone risk assumed unknown, not clear."
                )
                return "unverifiable", note, []
            evidence = [DataSource.IMD_LIVE]
            label = "api.imd.gov.in fallback"
            if fb.get("active"):
                name = fb.get("name") or "unknown"
                category = fb.get("category") or "unknown category"
                flags.append(HazardFlag(
                    label="Active cyclone system",
                    detail=f"{name} ({category}), {label}",
                    threshold_crossed="IMD cyclone track currently active",
                ))
                note = (
                    f"{label} shows an ACTIVE system: {name} ({category}). "
                    "This forces the verdict to UNSAFE."
                )
                return "ACTIVE", note, evidence
            note = (
                "Secondary IMD feed checked successfully after CAP was "
                "unreachable: no active cyclone system nationally."
            )
            reasoning.append(
                "Secondary IMD feed shows no active cyclone system"
            )
            return "clear", note, evidence

        try:
            cap_alerts = imd_cap.fetch_active_alerts()  # ONE network pass
            loc_pair = (ocean_state.location.lat, ocean_state.location.lon)

            # -- 1. Cyclone / depression --
            cyclone = imd_cap.fetch_cyclone_status(location=loc_pair,
                                                   alerts=cap_alerts)
            cyclone_source_label = "IMD CAP alert feed"
            cyclone_evidence = [DataSource.IMD_CAP_LIVE]
            if not cyclone.get("active"):
                cyclone_state = "clear"
                cyclone_note = (
                    "IMD CAP alert feed checked successfully: no active "
                    "cyclone/depression warning nationally."
                )
                reasoning.append(
                    "IMD CAP alert feed shows no active cyclone warning"
                )
            else:
                name = cyclone.get("name") or "unknown"
                category = cyclone.get("category") or "unknown severity"
                covering = cyclone.get("areas_covering_location") or []
                flags.append(HazardFlag(
                    label="Active cyclone system",
                    detail=f"{name} ({category}), {cyclone_source_label}",
                    threshold_crossed="active cyclone/depression CAP warning",
                ))
                cyclone_state = "ACTIVE" if covering else "ACTIVE (elsewhere)"
                if covering:
                    cyclone_note = (
                        f"{cyclone_source_label} has an ACTIVE warning affecting "
                        f"this area: {name} ({category}), zones: "
                        f"{', '.join(covering)}. This forces the verdict to UNSAFE."
                    )
                else:
                    cyclone_note = (
                        f"{cyclone_source_label} shows an ACTIVE warning: {name} "
                        f"({category}); its zone does not cover this exact point, "
                        f"but a nearby system still forces the verdict to UNSAFE."
                    )

            # -- 2. Marine bulletins (fishermen warnings, squally wind...) --
            marine_matched = imd_cap.match_alerts_by_terms(
                cap_alerts, imd_cap._MARINE_TERMS, loc_pair)
            non_cyclone_marine = [
                (a, i) for (a, i) in marine_matched["matches"]
                if not any(t in f'{i["event"]} {i["headline"]}'.lower()
                           for t in imd_cap._CYCLONE_TERMS)
            ]
            if non_cyclone_marine:
                _a, info = non_cyclone_marine[-1]
                label_txt = info["event"] or info["headline"] or "marine advisory"
                if marine_matched["covering"]:
                    flags.append(HazardFlag(
                        label="Marine warning in force",
                        detail=f"{label_txt}, zones: "
                               f"{', '.join(marine_matched['covering'])}",
                        threshold_crossed="IMD fishermen/sea-area bulletin active here",
                    ))
                    marine_lines.append(
                        f"Marine warning affecting this area: {label_txt}"
                    )
                    reasoning.append(f"Marine warning in force here: {label_txt}")
                else:
                    marine_lines.append(
                        f"Marine advisory elsewhere: {label_txt} "
                        "(its zone does not cover this point)")
                    reasoning.append(
                        f"Marine advisory active elsewhere: {label_txt}")

            # -- 3. Thunderstorm / lightning (PS 'lightning alerts') --
            light_matched = imd_cap.match_alerts_by_terms(
                cap_alerts, imd_cap._LIGHTNING_TERMS, loc_pair)
            if light_matched["matches"]:
                _a, info = light_matched["matches"][-1]
                label_txt = info["event"] or info["headline"] or "thunderstorm"
                sev = info.get("severity") or ""
                if light_matched["covering"]:
                    flags.append(HazardFlag(
                        label="Thunderstorm/lightning alert",
                        detail=f"{label_txt} ({sev}), zones: "
                               f"{', '.join(light_matched['covering'])}",
                        threshold_crossed="lightning/thunderstorm CAP warning over this area",
                    ))
                    reasoning.append(
                        f"Lightning/thunderstorm warning covers this area: {label_txt}")
                else:
                    reasoning.append(
                        f"Thunderstorm activity elsewhere ({label_txt}); "
                        "no lightning warning over this exact point")

            # -- polygons touching the point, for map overlays --
            cap_polygons = imd_cap.alerts_touching_location(cap_alerts, loc_pair)

        except imd_cap.CapUnavailableError:
            cyclone_state, cyclone_note, cyclone_evidence = _try_imd_live_fallback()
            if cyclone_state != "unverifiable":
                reasoning.append(
                    "CAP feed unreachable; secondary api.imd.gov.in feed used for "
                    "the cyclone check"
                )

        # --- Verdict ---
        if flags:
            status = SafetyStatus.UNSAFE
            headline = "Not safe to go fishing -- hazardous conditions forecast"
        elif ocean_state.wave_height_m > thr["wave_height_caution_m"] or \
                ocean_state.wind_gust_kmh > thr["wind_gust_caution_kmh"]:
            status = SafetyStatus.CAUTION
            headline = "Proceed with caution -- borderline conditions forecast"
        else:
            status = SafetyStatus.SAFE
            headline = "Safe to go fishing based on current forecast"

        confidence = min(ocean_state.confidence, 0.9)  # risk verdict never exceeds input data confidence

        risk = RiskAssessment(
            status=status,
            headline=headline,
            flags=flags,
            reasoning=reasoning,
            evidence_sources=[ocean_state.source, *cyclone_evidence],
            confidence=confidence,
            exceedance_windows=list(getattr(ocean_state, "exceedance_windows", []) or []),
            cap_polygons=cap_polygons,
            marine_bulletins=marine_lines,
        )

        # LLM layer: explain the verdict in the agent's own words, grounded
        # strictly in the deterministic computation above.
        risk.reasoning_note = self._generate_reasoning_note(
            risk, ocean_state, cyclone_note, marine_lines, thr=thr,
            vessel_class=vessel_class,
        )

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action=(
                "Applied safety thresholds to ocean-state data "
                f"+ live cyclone warning check [cyclone={cyclone_state}]"
            ),
            result_summary=(
                f"Verdict: {status.value} ({len(flags)} hazard flag(s)); "
                f"cyclone feed: {cyclone_state}"
            ),
            data_sources=[ocean_state.source, *cyclone_evidence],
            duration_ms=duration_ms,
        )
        return risk, trace

    # ------------------------------------------------------------------
    # LLM layer: a short note "reporting back" on the verdict it just
    # computed deterministically. Falls back to a template when no LLM.
    # ------------------------------------------------------------------
    def _generate_reasoning_note(
        self,
        risk: RiskAssessment,
        ocean_state: OceanStateReading,
        cyclone_note: str = "",
        marine_lines: list[str] | None = None,
        thr: dict | None = None,
        vessel_class: str = "small_fishing_boat",
    ) -> str:
        thr = thr or get_thresholds(vessel_class)
        flags_text = (
            "; ".join(f"{f.label}: {f.detail} ({f.threshold_crossed})" for f in risk.flags)
            if risk.flags
            else "none"
        )
        cyclone_line = (
            f"Live cyclone warning check result: {cyclone_note}\n"
            if cyclone_note else ""
        )
        marine_line = ""
        for m in (marine_lines or []):
            marine_line += f"Marine bulletin: {m}\n"
        exceed_line = ""
        windows = getattr(risk, "exceedance_windows", []) or []
        if windows:
            exceed_line = (
                "Threshold-exceedance time windows: "
                + "; ".join(
                    f"{w.metric.replace('_', ' ')} > {w.threshold}{w.unit} "
                    f"from {w.start_local} to {w.end_local} (peak {w.peak_value}{w.unit})"
                    for w in windows
                )
                + "\n"
            )
        system_prompt = (
            "You are the Hazard Agent in a marine-safety multi-agent system. You just "
            "computed a safety verdict using fixed numeric thresholds, and are writing "
            "a short note explaining your verdict back to a colleague agent (the "
            "Synthesis Agent), as if talking to them. Rules: your verdict is already "
            "decided -- explain it, do not second-guess or change it; use ONLY the "
            "numbers provided; do NOT invent values; keep it to 2-4 sentences. If the "
            "cyclone check could not be verified, say so honestly -- never claim the "
            "cyclone situation is clear when the feed was unreachable."
        )
        user_prompt = (
            f"Location: {ocean_state.location.name}, time window data was fetched for.\n"
            f"Input readings: wave height {ocean_state.wave_height_m} m, wind gusts "
            f"{ocean_state.wind_gust_kmh} km/h (thresholds for "
            f"{vessel_class.replace('_', ' ')}: waves unsafe > "
            f"{thr['wave_height_unsafe_m']} m, gusts unsafe > "
            f"{thr['wind_gust_unsafe_kmh']} km/h).\n"
            f"Hazard flags: {flags_text}\n"
            f"{cyclone_line}"
            f"{marine_line}"
            f"{exceed_line}"
            f"My verdict: {risk.status.value} -- {risk.headline}\n\n"
            "Write your 2-4 sentence note explaining this verdict and what drove it."
        )
        try:
            return llm_client.complete(
                system_prompt, user_prompt, temperature=0.4, max_tokens=600
            )
        except llm_client.LLMUnavailableError:
            base = (
                f"[llm_unavailable] Verdict {risk.status.value} computed from thresholds: "
                + (f"{len(risk.flags)} hazard flag(s): {flags_text}."
                   if risk.flags else
                   "no hazard flag crossed an unsafe threshold.")
            )
            if cyclone_note:
                base += f" Cyclone check: {cyclone_note}"
            for m in (marine_lines or []):
                base += f" Marine bulletin: {m}"
            return base
