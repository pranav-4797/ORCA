"""
Deterministic safety-floor — Task 8.

Runs after Synthesis Agent, before Response Agent. Only ever RAISES the final
risk verdict, never lowers it. If an active severe IMD warning is present
(e.g., severe cyclone, extreme marine bulletin, or CAP polygon with Severe/Extreme),
the floor forces EXTREME regardless of what synthesis produced.

Implemented as a small pure function for testability and isolation — does not
modify SynthesisAgent itself.
"""
from __future__ import annotations
from typing import Optional

from models import SafetyStatus, RiskAssessment

# Rank ordering for verdicts — higher is more severe.
_VERDICT_RANK = {
    "SAFE": 0,
    "SAFE TO SAIL": 0,
    "CAUTION": 1,
    "UNSAFE": 2,
    "EXTREME": 3,
    "CRITICAL": 3,
}

def _rank(verdict: str) -> int:
    return _VERDICT_RANK.get((verdict or "").strip().upper(), 1)

def _is_severe_warning_active(risk: Optional[RiskAssessment]) -> bool:
    """Check if risk indicates an active severe IMD warning."""
    if risk is None:
        return False
    # 1. Any cap_polygon with Severe/Extreme severity
    for poly in getattr(risk, "cap_polygons", []) or []:
        sev = str(poly.get("severity", "")).lower()
        if sev in ("severe", "extreme", "very severe", "super severe"):
            return True
        # Also check event name for cyclone/storm
        event = str(poly.get("event", "")).lower()
        if any(k in event for k in ("cyclone", "super cyclone", "very severe cyclonic")):
            # If event is cyclone and severity not low, consider severe
            if sev not in ("moderate", "minor", "unknown", ""):
                return True
    # 2. Marine bulletins containing severe keywords
    for bullet in getattr(risk, "marine_bulletins", []) or []:
        low = str(bullet).lower()
        if any(k in low for k in ("severe", "extreme", "very severe", "super severe", "cyclone warning: severe")):
            return True
        # Squally wind 55+ km/h often severe, but check wording
        if "cyclone" in low and ("warning" in low or "alert" in low):
            # If bulletin explicitly mentions cyclone warning, treat as severe
            # But need to be conservative: only if contains severe/extreme or very severe
            # For this floor, we treat any cyclone warning with severity hint as severe
            # Check if risk already UNSAFE due to hazard flags — that indicates severe
            pass
    # 3. Hazard flags with severe thresholds
    for flag in getattr(risk, "flags", []) or []:
        label = str(getattr(flag, "label", "")).lower()
        detail = str(getattr(flag, "detail", "")).lower()
        thresh = str(getattr(flag, "threshold_crossed", "")).lower()
        # If flag indicates wave/wind far beyond unsafe threshold, consider severe
        # For now, treat any flag with "severe" in label/detail as severe
        if "severe" in label or "severe" in detail or "extreme" in label or "extreme" in detail:
            return True
        # Also, if risk status is UNSAFE and has multiple flags, could be severe
        # But we want explicit severe IMD warning, not just generic UNSAFE
        # Check if hazard flag is cyclone-related and risk is UNSAFE
        if "cyclone" in label or "cyclone" in detail:
            return True
    # 4. Risk status already UNSAFE with high confidence and explicit severe reasoning?
    # For safety floor, we consider UNSAFE due to IMD CAP as severe — but we already checked cap_polygons.
    # If risk has at least one cap_polygon and status UNSAFE, treat as severe
    if risk.status == SafetyStatus.UNSAFE and getattr(risk, "cap_polygons", []):
        # Any CAP polygon with UNSAFE status implies active warning
        return True
    # 5. Check risk headline for severe
    headline = str(getattr(risk, "headline", "")).lower()
    if any(k in headline for k in ("severe", "extreme", "cyclone: severe", "very severe")):
        return True
    return False

def apply_safety_floor(
    synthesis: dict,
    risk: Optional[RiskAssessment],
) -> dict:
    """
    Enforce safety floor on synthesis verdict.

    - synthesis: dict with at least "verdict" key (SAFE/CAUTION/UNSAFE/EXTREME/CRITICAL)
    - risk: RiskAssessment or None

    Returns a *new* dict (or modified copy) where verdict is raised to EXTREME
    if a severe IMD warning is active and synthesis verdict is lower.
    Never lowers verdict. Also adds a conflict/note when floor triggers.
    """
    if not isinstance(synthesis, dict):
        return synthesis
    verdict = str(synthesis.get("verdict", "CAUTION"))
    if not _is_severe_warning_active(risk):
        return synthesis
    # Severe warning active — floor to EXTREME if needed
    current_rank = _rank(verdict)
    floor_rank = _rank("EXTREME")
    if current_rank >= floor_rank:
        # Already at or above floor — no-op
        return synthesis
    # Need to raise
    new_synth = dict(synthesis)  # shallow copy
    new_synth["verdict"] = "EXTREME"
    # Also ensure confidence reflects high severity?
    # Keep original confidence but add note
    conflicts = list(new_synth.get("conflicts", []))
    conflicts.append("Safety floor: active severe IMD warning forces EXTREME regardless of reconciled verdict.")
    new_synth["conflicts"] = conflicts
    key_points = list(new_synth.get("key_points", []))
    key_points.append("Severe IMD warning active — safety floor raised verdict to EXTREME.")
    new_synth["key_points"] = key_points
    new_synth["safety_floor_applied"] = True
    new_synth["safety_floor_reason"] = "Active severe IMD CAP/marine bulletin detected."
    return new_synth

def enforce_risk_floor(risk: Optional[RiskAssessment]) -> Optional[RiskAssessment]:
    """
    Also enforce floor on RiskAssessment status directly (for response status).
    Returns same or new RiskAssessment with status raised to EXTREME if severe.
    """
    if risk is None:
        return risk
    if not _is_severe_warning_active(risk):
        return risk
    if _rank(risk.status.value) >= _rank("EXTREME"):
        return risk
    # Raise risk status
    # Create new RiskAssessment with same fields but status EXTREME
    # We mutate copy to avoid side effects on original? Return new.
    from dataclasses import replace
    try:
        new_risk = replace(risk, status=SafetyStatus.EXTREME, headline=f"[SAFETY FLOOR] {risk.headline} — SEVERE warning forces EXTREME")
        # Add a flag for floor
        from models import HazardFlag
        floor_flag = HazardFlag(label="Safety floor: severe IMD warning", detail="Active severe cyclone/marine warning — verdict forced to EXTREME", threshold_crossed="severe IMD CAP/bulletin active")
        new_flags = list(risk.flags) + [floor_flag]
        new_risk.flags = new_flags
        return new_risk
    except Exception:
        # Fallback: mutate in place
        risk.status = SafetyStatus.EXTREME
        return risk
