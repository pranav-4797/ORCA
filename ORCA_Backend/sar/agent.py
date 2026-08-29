"""
SAR Surveillance Agent — authority/surveillance analysis stage.

This is NOT run on every fisherman query. It is invoked when:
  - authority mode is active (POST /sar/scan)
  - boundary surveillance is requested
  - scheduled surveillance runs

Keeps the fisherman-facing recommendation independent (no blocking).
Reuses the same explainability trace pattern as other agents.
"""
from __future__ import annotations

import time
from typing import Optional

from models import AgentTrace, DataSource

from .engine import run_sar_scan, SARConfig
from .matching import get_known_vessels
from .providers import get_provider


class SARAgent:
    name = "SARAgent"

    def run(
        self,
        area: Optional[dict] = None,
        provider: str = "auto",
        time_window: str = "today",
    ) -> tuple[object, AgentTrace]:
        """
        Run a SAR boundary surveillance pass.
        Returns (SARScanResult, AgentTrace) — trace makes the pipeline explainable.
        """
        t0 = time.perf_counter()
        cfg = SARConfig(provider=provider)
        result = run_sar_scan(area=area, provider=provider, config=cfg, time_window=time_window)

        duration_ms = (time.perf_counter() - t0) * 1000

        # Build human trace
        obs = result.observation
        prov_note = getattr(obs.provenance, "note", "") if hasattr(obs, "provenance") else ""
        if result.total == 0 and obs.status == "UNAVAILABLE":
            action = "SAR scan: DATA UNAVAILABLE"
            summary = f"No SAR observation available. Source={obs.source} — {prov_note}"
            sources = [DataSource.SIMULATED]
        elif obs.status == "SIMULATED":
            action = f"SAR scan complete (SIMULATED): {result.total} detections, {result.unknown} unknown near IMBL"
            summary = f"DEMO — SIMULATED SAR DATA: {result.total} vessels detected near maritime boundary; {result.known} matched to ORCA fleet, {result.unknown} UNKNOWN requiring authority verification. Dataset={obs.dataset} Product={obs.product_id} — {prov_note}"
            sources = [DataSource.SIMULATED]
        else:
            action = f"SAR scan complete: {result.total} detections, {result.unknown} unknown near IMBL"
            summary = f"REAL SAR observation: {result.total} vessels near boundary; {result.known} known, {result.unknown} UNKNOWN. Dataset={obs.dataset} Product={obs.product_id}"
            # provenance tagging — real vs derived
            sources = [DataSource.BHUVAN_LIVE if "BHUVAN" in obs.source else DataSource.LIVE]  # type: ignore

        trace = AgentTrace(
            agent_name=self.name,
            action=action,
            result_summary=summary,
            data_sources=sources,
            duration_ms=duration_ms,
        )
        return result, trace
