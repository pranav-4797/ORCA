"""Dispatch mixin — Task 10."""
from __future__ import annotations
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

from .state import INTENT_DEFAULT_AGENTS, Intent
from models import AgentTrace

class DispatchMixin:
    def _selected_specialists(self, plan: dict, live_position: bool = False) -> List[str]:
        requested = {a for a in (plan.get("agents_needed") or [])}
        if plan.get("is_compound"):
            chosen = set(requested)
        else:
            defaults = INTENT_DEFAULT_AGENTS.get(plan["intent"], [])
            chosen = requested & set(defaults) or set(defaults)
        if "HazardAgent" in chosen:
            chosen.add("OceanStateAgent")
        # Geospatial only runs for intents that actually ask about boundaries /
        # routes / zones — NEVER blanket-forced just because GPS was sent.
        _intent_defaults = INTENT_DEFAULT_AGENTS.get(plan.get("intent"), []) or []
        if live_position and "GeospatialAgent" in _intent_defaults:
            chosen.add("GeospatialAgent")
        nodes: List[str] = []
        if "TrendAgent" in chosen and plan["intent"] == Intent.TREND_ANALYSIS:
            nodes.append("trend")
            return nodes
        if "OceanStateAgent" in chosen:
            nodes.append("ocean_state")
        if "PFZAgent" in chosen:
            nodes.append("pfz")
        if "GeospatialAgent" in chosen:
            nodes.append("geospatial")
        return nodes

    def _should_run_discussion(self, state) -> bool:
        from .state import QUERY_DEPTH
        mode = (state.get("mode") or "auto").lower()
        if mode == "panel":
            return True
        if mode == "agent":
            return False
        complexity = (state.get("complexity") or state.get("plan", {}).get("complexity") or "fast")
        depth_policy = (state.get("query_depth") or QUERY_DEPTH).lower()
        if depth_policy == "fast":
            return False
        if depth_policy == "deep":
            return True
        if complexity in ("fast", "standard"):
            return False
        return True

    def _should_use_synthesis_llm(self, state) -> bool:
        from .state import QUERY_DEPTH
        mode = (state.get("mode") or "auto").lower()
        if mode == "panel":
            return True
        if mode == "agent":
            return False
        complexity = (state.get("complexity") or state.get("plan", {}).get("complexity") or "fast")
        depth_policy = (state.get("query_depth") or QUERY_DEPTH).lower()
        if depth_policy == "fast":
            return False
        if depth_policy == "deep":
            return True
        if complexity in ("fast", "standard"):
            return False
        return True

    def _record_telemetry(self, state, response, total_ms: float):
        try:
            import routing_telemetry
            routing_mode = state.get("routing_mode") or state.get("plan", {}).get("routing_mode", "rules")
            complexity = state.get("complexity") or state.get("plan", {}).get("complexity", "fast")
            mode = state.get("mode") or getattr(response, "mode", "auto")
            traces = list(state.get("traces") or []) + list(getattr(response, "trace", []) or [])
            discussion_ran = False
            synthesis_ran = False
            for t in traces:
                name = getattr(t, "agent_name", "") or (t.get("agent_name", "") if isinstance(t, dict) else "")
                action = getattr(t, "action", "") or (t.get("action", "") if isinstance(t, dict) else "")
                if name == "DiscussionAgent":
                    if "Skipped" not in action:
                        discussion_ran = True
                if name == "SynthesisAgent":
                    if "Skipped" not in action and "Deterministic" not in action:
                        synthesis_ran = True
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
