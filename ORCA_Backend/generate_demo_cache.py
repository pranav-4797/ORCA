"""
Generate demo cache fixtures for Task 9.
"""
import json
import hashlib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from unittest.mock import patch, MagicMock

from models import Location, DataSource, AgentTrace, PFZRecommendation, GeofenceStatus
from orchestrator import Orchestrator

# Use same fakes as tests for deterministic fixtures
def _fake_ocean(location, time_window="today", target_hour=None, thresholds=None):
    from models import OceanStateReading, DataSource
    import datetime
    wave = 1.0
    reading = OceanStateReading(
        location=location,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        sst_celsius=28.0,
        chlorophyll_mg_m3=0.8,
        wave_height_m=wave,
        wind_speed_kmh=12.0,
        wind_gust_kmh=20.0,
        tide_level_m=1.0,
        source=DataSource.SIMULATED,
        confidence=0.6,
        reasoning_note=f"Wave height {wave} m",
        field_sources={k: DataSource.SIMULATED.value for k in ["sst_celsius","wave_height_m","wind_speed_kmh","wind_gust_kmh","chlorophyll_mg_m3","tide_level_m"]},
    )
    trace = AgentTrace(agent_name="OceanStateAgent", action="fake", result_summary=f"wave {wave}m", data_sources=[DataSource.SIMULATED], duration_ms=5)
    return reading, trace

def _fake_hazard(ocean_state, vessel_class="small_fishing_boat"):
    from agents.hazard_agent import get_thresholds
    from models import RiskAssessment, HazardFlag, SafetyStatus
    thr = get_thresholds(vessel_class)
    risk = RiskAssessment(status=SafetyStatus.SAFE, headline="safe", flags=[], reasoning=[f"wave {ocean_state.wave_height_m}"], evidence_sources=[ocean_state.source], confidence=0.9, reasoning_note=f"Verdict SAFE")
    trace = AgentTrace(agent_name="HazardAgent", action="fake hazard", result_summary=f"Verdict SAFE", data_sources=[ocean_state.source], duration_ms=2)
    return risk, trace

def _fake_trend(location, months_back=6):
    from models import TrendAnalysis, TrendPoint
    points = [TrendPoint(date=f"2025-{m:02d}-15", sst_celsius=28.0, chlorophyll_mg_m3=0.8) for m in range(1, months_back+1)]
    trend = TrendAnalysis(location_name=location.name, window_months=months_back, points=points, sst_trend_per_month=0.02, chl_trend_per_month=0.001, sst_chl_correlation=0.5, interpretation_note="warming", field_sources={}, reasoning_note="trend")
    return trend, AgentTrace(agent_name="TrendAgent", action="fake trend", result_summary="trend", data_sources=[], duration_ms=5)

DEMO_QUERIES = [
    "Is it safe to fish near Ratnagiri tomorrow?",
    "Where is the nearest fishing zone near Kochi today?",
    "Is it safe to fish near Kochi and what's the safest route avoiding restricted zones?",
    "Why has SST changed over the last 6 months near Kochi?",
    "Am I near a restricted area off Kochi?",
]

def _normalize(q):
    return " ".join(q.strip().lower().split())

def main():
    import demo_cache
    cache_dir = Path(__file__).resolve().parent / "demo_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Generating demo cache in {cache_dir}")

    with patch("agents.ocean_state_agent.OceanStateAgent.run", side_effect=_fake_ocean):
        with patch("agents.hazard_agent.HazardAgent.run", side_effect=_fake_hazard):
            with patch("agents.trend_agent.TrendAgent.run", side_effect=_fake_trend):
                def fake_pfz(loc, ocean_state=None, time_window="today"):
                    pfz = PFZRecommendation(reference_location=loc, center_lat=loc.lat+0.1, center_lon=loc.lon+0.1, distance_from_reference_km=12.0, bearing_deg=45.0, sst_at_zone_celsius=27.5, chlorophyll_at_zone_mg_m3=0.8, source=DataSource.DERIVED_LIVE, confidence=0.6, reasoning_note="zone 12 km away")
                    return pfz, AgentTrace(agent_name="PFZAgent", action="fake", result_summary="pfz", data_sources=[DataSource.DERIVED_LIVE], duration_ms=1)
                def fake_geo(location, device_gps=None, destination=None, hazard_zone_names=None):
                    gf = GeofenceStatus(reference_location=location, hits=[], nearest_boundary_km=999, clear=True, reasoning_note="clear")
                    return (gf, None), AgentTrace(agent_name="GeospatialAgent", action="fake", result_summary="clear", data_sources=[], duration_ms=1)
                with patch("agents.pfz_agent.PFZAgent.run", side_effect=fake_pfz):
                    with patch("agents.geospatial_agent.GeospatialAgent.run", side_effect=fake_geo):
                        o = Orchestrator()
                        for q in DEMO_QUERIES:
                            print(f"\nGenerating for: {q}")
                            # Mock LLM to avoid network — force deterministic
                            with patch("llm_client.is_available", return_value=False):
                                with patch("agents.language_agent.llm_client.is_available", return_value=False):
                                    with patch("orchestrator.llm_client.is_available", return_value=False):
                                        resp = o.handle_query(q, mode="auto")
                                        # Serialize via dataclass asdict logic similar to main._serialize
                                        from dataclasses import asdict
                                        def convert(obj):
                                            if hasattr(obj, "__dataclass_fields__"):
                                                return {k: convert(v) for k, v in asdict(obj).items()}
                                            if isinstance(obj, list):
                                                return [convert(v) for v in obj]
                                            if hasattr(obj, "value"):
                                                return obj.value
                                            return obj
                                        data = convert(resp)
                                        # Ensure discussion and trace etc are included
                                        # Add raw query for matching
                                        data["demo_query"] = q
                                        data["demo_normalized"] = _normalize(q)
                                        # Mark as cached_demo for fixture (but when serving, mode will be overwritten to cached_demo)
                                        data["mode"] = "cached_demo"
                                        data["cached_demo"] = True
                                        # Write file
                                        h = hashlib.sha256(_normalize(q).encode()).hexdigest()[:12]
                                        path = cache_dir / f"{h}.json"
                                        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
                                        print(f"  Wrote {path} ({len(json.dumps(data, default=str))} chars)")
                                        print(f"  Status {resp.status} mode {resp.mode} answer {resp.answer[:80]}...")
    print("\nDone. Demo cache files:")
    for p in cache_dir.glob("*.json"):
        print(" ", p.name)

if __name__ == "__main__":
    main()
