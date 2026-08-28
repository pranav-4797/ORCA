"""
Test demo cache — Task 9.
"""
import os
from unittest.mock import patch

def test_demo_cache_disabled_by_default():
    import demo_cache
    # Ensure flag off by default
    with patch.dict(os.environ, {}, clear=False):
        # Unset
        os.environ.pop("ORCA_DEMO_CACHE", None)
        assert demo_cache.is_enabled() is False
        assert demo_cache.get_cached_response("Is it safe to fish near Ratnagiri tomorrow?") is None

def test_demo_cache_hit_when_enabled():
    import demo_cache
    from orchestrator import Orchestrator
    # Enable flag
    with patch.dict(os.environ, {"ORCA_DEMO_CACHE": "1"}):
        assert demo_cache.is_enabled() is True
        # Direct cache hit
        data = demo_cache.get_cached_response("Is it safe to fish near Ratnagiri tomorrow?")
        assert data is not None
        assert data["mode"] == "cached_demo"
        assert "answer" in data
        # Via orchestrator
        o = Orchestrator()
        resp = o.handle_query("Is it safe to fish near Ratnagiri tomorrow?", mode="auto")
        assert resp.mode == "cached_demo", f"Expected cached_demo, got {resp.mode}"
        assert "cached_demo" in resp.mode or resp.answered_by == "DemoCache (cached_demo — no live LLM)"
        # Should have DemoCache trace
        assert any("DemoCache" in t.agent_name for t in resp.trace)

def test_demo_cache_no_hit_for_unknown_query():
    import demo_cache
    with patch.dict(os.environ, {"ORCA_DEMO_CACHE": "1"}):
        data = demo_cache.get_cached_response("This is a completely unknown query not in demo list")
        assert data is None

def test_demo_cache_not_confused_with_live():
    import demo_cache
    from orchestrator import Orchestrator
    # When flag off, even demo query should go live (not cached)
    with patch.dict(os.environ, {"ORCA_DEMO_CACHE": "0"}):
        o = Orchestrator()
        # Mock live to ensure not cached
        with patch("agents.ocean_state_agent.OceanStateAgent.run") as mock_ocean:
            # If cache were hit, ocean would not be called. When off, it should be called.
            # Use side_effect to detect call
            from models import OceanStateReading, DataSource, AgentTrace, Location
            import datetime
            def fake_ocean(location, time_window="today", target_hour=None, thresholds=None):
                reading = OceanStateReading(location=location, timestamp=datetime.datetime.now(datetime.timezone.utc), sst_celsius=28, chlorophyll_mg_m3=0.8, wave_height_m=1.0, wind_speed_kmh=10, wind_gust_kmh=15, tide_level_m=1.0, source=DataSource.SIMULATED, confidence=0.6, reasoning_note="wave")
                return reading, AgentTrace(agent_name="OceanStateAgent", action="fake", result_summary="wave", data_sources=[DataSource.SIMULATED], duration_ms=5)
            mock_ocean.side_effect = fake_ocean
            # Need also mock hazard etc to avoid network
            with patch("agents.hazard_agent.HazardAgent.run") as mock_hazard:
                from models import RiskAssessment, SafetyStatus
                def fake_hazard(ocean_state, vessel_class="small_fishing_boat"):
                    risk = RiskAssessment(status=SafetyStatus.SAFE, headline="safe", flags=[], reasoning=[], evidence_sources=[ocean_state.source], confidence=0.9, reasoning_note="safe")
                    return risk, AgentTrace(agent_name="HazardAgent", action="fake", result_summary="SAFE", data_sources=[ocean_state.source], duration_ms=2)
                mock_hazard.side_effect = fake_hazard
                with patch("agents.pfz_agent.PFZAgent.run") as mock_pfz:
                    from models import PFZRecommendation
                    def fake_pfz(loc, ocean_state=None, time_window="today"):
                        pfz = PFZRecommendation(reference_location=loc, center_lat=loc.lat+0.1, center_lon=loc.lon+0.1, distance_from_reference_km=12.0, bearing_deg=45.0, sst_at_zone_celsius=27.5, chlorophyll_at_zone_mg_m3=0.8, source=DataSource.DERIVED_LIVE, confidence=0.6, reasoning_note="zone")
                        return pfz, AgentTrace(agent_name="PFZAgent", action="fake", result_summary="pfz", data_sources=[DataSource.DERIVED_LIVE], duration_ms=1)
                    mock_pfz.side_effect = fake_pfz
                    with patch("agents.geospatial_agent.GeospatialAgent.run") as mock_geo:
                        from models import GeofenceStatus
                        mock_geo.side_effect = lambda *a, **k: ((GeofenceStatus(reference_location=Location(name="Kochi", lat=9.9, lon=76.2), hits=[], nearest_boundary_km=999, clear=True), None), AgentTrace(agent_name="GeospatialAgent", action="fake", result_summary="clear", data_sources=[], duration_ms=1))
                        resp = o.handle_query("Is it safe to fish near Ratnagiri tomorrow?", mode="auto")
                        # When flag off, should NOT be cached_demo
                        assert resp.mode != "cached_demo", f"Should be live when flag off, got {resp.mode}"
