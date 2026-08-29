"""
Smoke test — Task 13.

Runs 4-5 representative scenarios headless (no server, no browser) and prints PASS/FAIL.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from unittest.mock import patch, MagicMock
from models import Location, DataSource, AgentTrace, PFZRecommendation, GeofenceStatus
from orchestrator import Orchestrator
from models import SafetyStatus
import datetime

def _fake_ocean(location, time_window="today", target_hour=None, thresholds=None):
    from models import OceanStateReading
    reading = OceanStateReading(
        location=location,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        sst_celsius=28.0, chlorophyll_mg_m3=0.8, wave_height_m=1.0,
        wind_speed_kmh=12.0, wind_gust_kmh=20.0, tide_level_m=1.0,
        source=DataSource.SIMULATED, confidence=0.6, reasoning_note="wave 1",
        field_sources={k: DataSource.SIMULATED.value for k in ["sst_celsius","wave_height_m","wind_speed_kmh","wind_gust_kmh","chlorophyll_mg_m3","tide_level_m"]},
    )
    return reading, AgentTrace(agent_name="OceanStateAgent", action="fake", result_summary="wave 1", data_sources=[DataSource.SIMULATED], duration_ms=5)

def _fake_hazard(ocean_state, vessel_class="small_fishing_boat"):
    from models import RiskAssessment, HazardFlag
    risk = RiskAssessment(status=SafetyStatus.SAFE, headline="safe", flags=[], reasoning=["wave 1 safe"], evidence_sources=[ocean_state.source], confidence=0.9, reasoning_note="SAFE")
    return risk, AgentTrace(agent_name="HazardAgent", action="fake", result_summary="SAFE", data_sources=[ocean_state.source], duration_ms=2)

def _fake_trend(location, months_back=6):
    from models import TrendAnalysis, TrendPoint
    pts = [TrendPoint(date=f"2025-{m:02d}-15", sst_celsius=28.0, chlorophyll_mg_m3=0.8) for m in range(1, months_back+1)]
    trend = TrendAnalysis(location_name=location.name, window_months=months_back, points=pts, sst_trend_per_month=0.02, chl_trend_per_month=0.001, sst_chl_correlation=0.5, interpretation_note="trend", field_sources={}, reasoning_note="trend")
    return trend, AgentTrace(agent_name="TrendAgent", action="fake", result_summary="trend", data_sources=[], duration_ms=5)

SCENARIOS = [
    {
        "id": "safety_koshi_tomorrow",
        "query": "Is it safe to fish near Kochi tomorrow?",
        "mode": "auto",
        "checks": lambda r: r.status in (SafetyStatus.SAFE, SafetyStatus.CAUTION) and "SAFE" in r.answer.upper() or "CAUTION" in r.answer.upper(),
    },
    {
        "id": "pfz_koshi",
        "query": "Where is the nearest fishing zone near Kochi today?",
        "mode": "auto",
        "checks": lambda r: r.pfz is not None and r.pfz.distance_from_reference_km > 0,
    },
    {
        "id": "hazard_ratnagiri",
        "query": "Any cyclone warning near Ratnagiri?",
        "mode": "auto",
        "checks": lambda r: r.risk is not None,
    },
    {
        "id": "geofence_kochi",
        "query": "Am I near a restricted area off Kochi?",
        "mode": "auto",
        "checks": lambda r: r.geofence is not None,
    },
    {
        "id": "trend_kochi_6mo",
        "query": "Why has SST changed over the last 6 months near Kochi?",
        "mode": "auto",
        "checks": lambda r: r.trend is not None or "trend" in r.answer.lower() or r.routing.get("intent") == "trend_analysis",
    },
]

def run_smoke():
    print("="*80)
    print("SMOKE TEST — 5 representative scenarios (headless, no server)")
    print("="*80)
    results = []
    # Mock external to keep deterministic
    with patch("agents.ocean_state_agent.OceanStateAgent.run", side_effect=_fake_ocean):
        with patch("agents.hazard_agent.HazardAgent.run", side_effect=_fake_hazard):
            with patch("agents.trend_agent.TrendAgent.run", side_effect=_fake_trend):
                def fake_pfz(loc, ocean_state=None, time_window="today"):
                    pfz = PFZRecommendation(reference_location=loc, center_lat=loc.lat+0.1, center_lon=loc.lon+0.1, distance_from_reference_km=12.0, bearing_deg=45.0, sst_at_zone_celsius=27.5, chlorophyll_at_zone_mg_m3=0.8, source=DataSource.DERIVED_LIVE, confidence=0.6, reasoning_note="zone")
                    return pfz, AgentTrace(agent_name="PFZAgent", action="fake", result_summary="pfz", data_sources=[DataSource.DERIVED_LIVE], duration_ms=1)
                def fake_geo(location, device_gps=None, destination=None, hazard_zone_names=None):
                    gf = GeofenceStatus(reference_location=location, hits=[], nearest_boundary_km=999, clear=True, reasoning_note="clear")
                    return (gf, None), AgentTrace(agent_name="GeospatialAgent", action="fake", result_summary="clear", data_sources=[], duration_ms=1)
                with patch("agents.pfz_agent.PFZAgent.run", side_effect=fake_pfz):
                    with patch("agents.geospatial_agent.GeospatialAgent.run", side_effect=fake_geo):
                        o = Orchestrator()
                        for sc in SCENARIOS:
                            q = sc["query"]
                            print(f"\n[{sc['id']}] Query: {q}")
                            try:
                                resp = o.handle_query(q, mode=sc["mode"])
                                ok = False
                                try:
                                    ok = bool(sc["checks"](resp))
                                except Exception as e:
                                    print(f"  Check error: {e}")
                                    ok = False
                                status = "PASS" if ok else "FAIL"
                                print(f"  -> {status} | status={resp.status.value} | routing={resp.routing.get('intent')} | answer snippet: {resp.answer[:80]}...")
                                # Also ensure no crash and trace present
                                if not resp.trace:
                                    print("  -> FAIL (empty trace)")
                                    ok = False
                                results.append((sc["id"], ok))
                            except Exception as e:
                                print(f"  -> FAIL (exception: {e})")
                                import traceback
                                traceback.print_exc()
                                results.append((sc["id"], False))
    print("\n" + "="*80)
    print("SMOKE SUMMARY")
    for sid, ok in results:
        print(f"  {sid}: {'PASS' if ok else 'FAIL'}")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\nTotal: {passed}/{total} passed")
    if passed == total:
        print("SMOKE TEST: ALL PASS")
    else:
        print("SMOKE TEST: SOME FAIL")
    print("="*80)
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(run_smoke())

# Pytest wrapper
def test_smoke_scenarios():
    assert run_smoke() == 0
