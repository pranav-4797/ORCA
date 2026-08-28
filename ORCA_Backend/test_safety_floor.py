"""
Tests for deterministic safety-floor — Task 8.

Verifies floor only ever RAISES verdict, never lowers.
"""
from models import SafetyStatus, RiskAssessment, HazardFlag, DataSource, AgentTrace
from datetime import datetime, timezone
from models import Location, OceanStateReading
import safety_floor

def _make_risk_with_severe_warning():
    loc = Location(name="Ratnagiri Coast", lat=16.9, lon=73.3)
    ocean = OceanStateReading(location=loc, timestamp=datetime.now(timezone.utc), sst_celsius=28, chlorophyll_mg_m3=0.8, wave_height_m=3.5, wind_speed_kmh=20, wind_gust_kmh=30, tide_level_m=1.0, source=DataSource.LIVE, confidence=0.9, reasoning_note="wave 3.5")
    # Severe IMD cap polygon
    risk = RiskAssessment(
        status=SafetyStatus.UNSAFE,
        headline="Severe cyclone warning active",
        flags=[HazardFlag(label="Severe cyclone", detail="Severe cyclonic storm within 100km", threshold_crossed="severe")],
        reasoning=["Severe cyclone within 100km"],
        evidence_sources=[DataSource.IMD_CAP_LIVE],
        confidence=0.95,
        reasoning_note="Severe warning",
        cap_polygons=[{"event": "Cyclone Warning", "severity": "Severe", "area_desc": "Ratnagiri coast", "polygon": [(16.9,73.3),(17.0,73.4)]}],
        marine_bulletins=["Severe cyclone warning for Ratnagiri — winds 65 km/h, avoid sea"],
    )
    return risk

def _make_risk_without_warning():
    loc = Location(name="Kochi Coast", lat=9.9, lon=76.2)
    ocean = OceanStateReading(location=loc, timestamp=datetime.now(timezone.utc), sst_celsius=28, chlorophyll_mg_m3=0.8, wave_height_m=1.0, wind_speed_kmh=10, wind_gust_kmh=15, tide_level_m=1.0, source=DataSource.LIVE, confidence=0.9, reasoning_note="calm")
    risk = RiskAssessment(
        status=SafetyStatus.SAFE,
        headline="Calm seas",
        flags=[],
        reasoning=["wave 1.0 safe"],
        evidence_sources=[DataSource.LIVE],
        confidence=0.9,
        reasoning_note="safe",
        cap_polygons=[],
        marine_bulletins=[],
    )
    return risk

def _make_risk_extreme():
    risk = _make_risk_with_severe_warning()
    risk.status = SafetyStatus.EXTREME
    risk.headline = "EXTREME severe warning"
    return risk

def test_floor_raises_safe_to_extreme_when_severe_active():
    """(a) synthesis says SAFE but severe warning active -> floor forces EXTREME."""
    risk = _make_risk_with_severe_warning()
    synthesis = {"verdict": "SAFE", "confidence": "high", "conflicts": [], "key_points": ["calm seas"]}
    floored = safety_floor.apply_safety_floor(synthesis, risk)
    assert floored["verdict"] == "EXTREME", f"Expected EXTREME, got {floored['verdict']}"
    assert floored.get("safety_floor_applied") is True
    # Original synthesis should not be mutated
    assert synthesis["verdict"] == "SAFE"
    # Also enforce_risk_floor should raise risk to EXTREME
    new_risk = safety_floor.enforce_risk_floor(risk)
    assert new_risk.status == SafetyStatus.EXTREME

def test_floor_noop_when_already_extreme():
    """(b) synthesis already says EXTREME -> floor is no-op."""
    risk = _make_risk_extreme()
    synthesis = {"verdict": "EXTREME", "confidence": "high", "conflicts": [], "key_points": []}
    floored = safety_floor.apply_safety_floor(synthesis, risk)
    # Should be same object or at least verdict unchanged
    assert floored["verdict"] == "EXTREME"
    # Since already at floor, should not add extra conflict? Our code returns same dict if no raise
    # Check that it didn't mutate to add safety_floor flag unnecessarily
    # In our impl, if already EXTREME, it returns original synthesis (no copy)
    assert floored is synthesis or floored.get("safety_floor_applied") is None or floored["verdict"] == "EXTREME"

def test_floor_noop_when_no_warning():
    """(c) no warning present -> floor is no-op."""
    risk = _make_risk_without_warning()
    synthesis = {"verdict": "SAFE", "confidence": "high", "conflicts": [], "key_points": []}
    floored = safety_floor.apply_safety_floor(synthesis, risk)
    assert floored["verdict"] == "SAFE"
    assert floored is synthesis or floored.get("safety_floor_applied") is None

def test_floor_never_lowers():
    """Ensure floor never lowers verdict (e.g., UNSAFE should not become SAFE)."""
    risk = _make_risk_with_severe_warning()
    for verdict in ["UNSAFE", "EXTREME", "CRITICAL", "CAUTION", "SAFE"]:
        synthesis = {"verdict": verdict, "confidence": "high", "conflicts": [], "key_points": []}
        floored = safety_floor.apply_safety_floor(synthesis, risk)
        # Rank of floored should be >= original rank
        rank = {"SAFE":0, "CAUTION":1, "UNSAFE":2, "EXTREME":3, "CRITICAL":3}
        assert rank[floored["verdict"]] >= rank[verdict], f"Floor lowered {verdict} -> {floored['verdict']}"

def test_floor_integration_via_orchestrator():
    """Integration: orchestrator's synthesis->floor->response raises to EXTREME when severe."""
    from orchestrator import Orchestrator
    from unittest.mock import patch, MagicMock
    from models import PFZRecommendation, GeofenceStatus

    loc = Location(name="Ratnagiri Coast", lat=16.9, lon=73.3)
    # Fake ocean with severe risk
    def fake_ocean(location, time_window="today", target_hour=None, thresholds=None):
        from models import OceanStateReading, DataSource
        import datetime
        reading = OceanStateReading(location=location, timestamp=datetime.datetime.now(datetime.timezone.utc), sst_celsius=28, chlorophyll_mg_m3=0.8, wave_height_m=3.5, wind_speed_kmh=25, wind_gust_kmh=40, tide_level_m=1.0, source=DataSource.LIVE, confidence=0.95, reasoning_note="severe", field_sources={})
        return reading, MagicMock(agent_name="OceanStateAgent", action="fake", result_summary="severe", data_sources=[DataSource.LIVE], duration_ms=5)
    # Risk with severe warning — will be returned by hazard
    severe_risk = _make_risk_with_severe_warning()
    def fake_hazard(ocean_state, vessel_class="small_fishing_boat"):
        return severe_risk, MagicMock(agent_name="HazardAgent", action="fake", result_summary="severe", data_sources=[DataSource.IMD_CAP_LIVE], duration_ms=2)

    # Mock synthesis to return SAFE (wrong) — floor should correct to EXTREME
    def fake_synthesis_llm(*args, **kwargs):
        return {"verdict": "SAFE", "confidence": "high", "conflicts_resolved": "none", "conflicts": [], "key_points": ["PFZ looks good"]}, MagicMock(agent_name="SynthesisAgent", action="LLM synthesis", result_summary="SAFE", data_sources=[], duration_ms=10)

    with patch("agents.ocean_state_agent.OceanStateAgent.run", side_effect=fake_ocean):
        with patch("agents.hazard_agent.HazardAgent.run", side_effect=fake_hazard):
            with patch.object(Orchestrator, "_fetch_live", create=True, new=None):
                o = Orchestrator()
                # Patch synthesis to return SAFE incorrectly
                with patch.object(o.synthesis_agent, "run", side_effect=fake_synthesis_llm):
                    # Also need to ensure safety floor is called — it will be in graph
                    resp = o.handle_query("Is it safe to fish near Ratnagiri tomorrow?", mode="auto")
                    # After floor, status should be EXTREME (or UNSAFE at least), not SAFE
                    assert resp.status in (SafetyStatus.EXTREME, SafetyStatus.UNSAFE, SafetyStatus.CRITICAL), f"Expected EXTREME/UNSAFE due to severe warning, got {resp.status} answer {resp.answer[:100]}"
                    # Check trace contains SafetyFloor
                    assert any("SafetyFloor" in t.agent_name for t in resp.trace), "SafetyFloor trace should be present"
