"""Fleet Convergence Forecast — unit + integration tests"""
import time
import sys
sys.path.insert(0, ".")
import fleet_convergence as fc
from models import Location, PFZRecommendation, DataSource, SafetyStatus, RiskAssessment, HazardFlag, OceanStateReading
import datetime

def _make_pfz(center_lat=10.0, center_lon=76.0):
    return PFZRecommendation(
        reference_location=Location(name="Test Coast", lat=10.0, lon=76.0),
        center_lat=center_lat,
        center_lon=center_lon,
        distance_from_reference_km=12.0,
        bearing_deg=45.0,
        sst_at_zone_celsius=27.5,
        chlorophyll_at_zone_mg_m3=0.8,
        source=DataSource.DERIVED_LIVE,
        confidence=0.65,
        alternates=[
            {"center_lat": center_lat+0.15, "center_lon": center_lon+0.15, "distance_km": 18, "bearing_deg": 90, "sst_celsius": 27.0, "gradient_vs_reference_c": 1.2},
            {"center_lat": center_lat-0.15, "center_lon": center_lon-0.15, "distance_km": 22, "bearing_deg": 180, "sst_celsius": 26.8, "gradient_vs_reference_c": 0.8},
        ]
    )

def test_crowding_0():
    ratio, penalty = fc.compute_crowding(0)
    assert ratio == 0
    assert penalty == 0
    adj = fc.compute_adjusted_suitability(85, penalty)
    assert adj == 85

def test_crowding_2():
    ratio, penalty = fc.compute_crowding(2)
    assert ratio == 0.25
    assert 0 < penalty < 0.1
    adj = fc.compute_adjusted_suitability(85, penalty)
    assert 82 < adj < 85

def test_crowding_5():
    ratio, penalty = fc.compute_crowding(5)
    assert ratio == 0.625
    adj = fc.compute_adjusted_suitability(85, penalty)
    assert 78 < adj < 83

def test_crowding_10():
    ratio, penalty = fc.compute_crowding(10)
    assert ratio == 1.25
    adj = fc.compute_adjusted_suitability(85, penalty)
    assert 72 < adj < 78

def test_crowding_20():
    ratio, penalty = fc.compute_crowding(20)
    assert ratio == 2.5
    assert penalty == 0.3  # 2.5*0.12=0.3, below max 0.5
    adj = fc.compute_adjusted_suitability(85, penalty)
    assert adj == 59.5  # 85 * 0.7
    # Test max cap with larger fleet
    ratio2, penalty2 = fc.compute_crowding(40)
    assert penalty2 == fc.FLEET_MAX_PENALTY
    assert fc.compute_adjusted_suitability(85, penalty2) == 42.5

def test_ranking_b_beats_a():
    # A raw 92 fleet 18 -> adj ~67, B raw 85 fleet 4 -> adj ~79
    cands = [
        fc.CandidateZone(zone_id="ZONE_A", center_lat=10, center_lon=76, distance_km=12, bearing_deg=45, sst_celsius=28, base_suitability=92),
        fc.CandidateZone(zone_id="ZONE_B", center_lat=10.1, center_lon=76.1, distance_km=18, bearing_deg=90, sst_celsius=27, base_suitability=85),
    ]
    counts = {"ZONE_A": 18, "ZONE_B": 4}
    fc.apply_fleet_convergence(cands, counts)
    assert cands[0].adjusted_suitability == 67.2  # 92 * (1 - 0.27)
    assert cands[1].adjusted_suitability == 79.9  # 85 * (1 - 0.06)
    raw_best = max(cands, key=lambda x: x.base_suitability)
    final = max(cands, key=lambda x: x.adjusted_suitability)
    assert raw_best.zone_id == "ZONE_A"
    assert final.zone_id == "ZONE_B"

def test_safety_overrides_fleet():
    cands = [
        fc.CandidateZone(zone_id="ZONE_A", center_lat=10, center_lon=76, distance_km=12, bearing_deg=45, sst_celsius=28, base_suitability=92, is_safe=True, is_legal=True),
        fc.CandidateZone(zone_id="ZONE_B", center_lat=10.1, center_lon=76.1, distance_km=18, bearing_deg=90, sst_celsius=27, base_suitability=85, is_safe=False, is_legal=True), # unsafe alternative
    ]
    counts = {"ZONE_A": 18, "ZONE_B": 4}
    fc.apply_fleet_convergence(cands, counts)
    # B is unsafe, should be filtered out
    safety_filter = {"ZONE_A": True, "ZONE_B": False}
    raw, final, changed, reason = fc.select_best_candidate(cands, safety_filter=safety_filter)
    assert final.zone_id == "ZONE_A"
    assert not changed or final.zone_id == "ZONE_A"

def test_fallback_unavailable():
    # No PFZ
    res = fc.analyze_fleet_convergence(pfz=None)
    assert res.status == "UNAVAILABLE"

def test_staleness():
    fc.fleet_store.clear()
    # Old activity 7 hours ago (outside 6h window)
    old = fc.FleetActivity(zone_lat=10, zone_lon=76, timestamp=time.time() - 7*3600, session_id="old", is_simulated=False)
    with fc.fleet_store._lock:
        fc.fleet_store._activities.append(old)
    # Recent activity now
    fc.fleet_store.record(zone_lat=10, zone_lon=76, session_id="recent", is_simulated=False)
    pfz = _make_pfz()
    res = fc.analyze_fleet_convergence(pfz=pfz, include_simulated=False)
    # Should count only recent (1), not old
    for c in res.candidates:
        if c.zone_id == "ZONE_A":
            assert c.fleet_count == 1
    fc.fleet_store.clear()

def test_integration_pfz_to_fleet():
    fc.fleet_store.clear()
    pfz = _make_pfz()
    # Record 18 vessels on ZONE_A
    for i in range(18):
        fc.fleet_store.record(zone_lat=pfz.center_lat, zone_lon=pfz.center_lon, session_id=f"s{i}", is_simulated=False)
    # Record 4 on ZONE_B alternate
    alt = pfz.alternates[0]
    for i in range(4):
        fc.fleet_store.record(zone_lat=alt["center_lat"], zone_lon=alt["center_lon"], session_id=f"b{i}", is_simulated=False)
    res = fc.analyze_fleet_convergence(pfz=pfz, include_simulated=False)
    assert res.recommendation_changed == True
    assert res.raw_best_zone.zone_id == "ZONE_A"
    assert res.final_zone.zone_id != "ZONE_A"  # should switch to less crowded
    fc.fleet_store.clear()

def test_demo_mode_isolated():
    fc.fleet_store.clear()
    # Real activity
    fc.fleet_store.record(zone_lat=10, zone_lon=76, session_id="real1", is_simulated=False)
    # Simulated
    fc.simulate_fleet_activity(10, 76, level="high")
    # Without include_simulated, should count only real
    pfz = _make_pfz(10, 76)
    res_real = fc.analyze_fleet_convergence(pfz=pfz, include_simulated=False)
    res_sim = fc.analyze_fleet_convergence(pfz=pfz, include_simulated=True)
    # Simulated should have higher counts
    real_counts = sum(c.fleet_count for c in res_real.candidates)
    sim_counts = sum(c.fleet_count for c in res_sim.candidates)
    assert sim_counts > real_counts
    assert res_sim.status.startswith("SIMULATED")
    fc.fleet_store.clear()

def test_zero_vessels():
    pfz = _make_pfz()
    fc.fleet_store.clear()
    res = fc.analyze_fleet_convergence(pfz=pfz, include_simulated=False)
    for c in res.candidates:
        assert c.fleet_count == 0
        assert c.adjusted_suitability == c.base_suitability

def test_performance_single_fetch():
    # Ensure aggregated counts does one fetch, not per zone queries
    fc.fleet_store.clear()
    pfz = _make_pfz()
    for i in range(5):
        fc.fleet_store.record(zone_lat=pfz.center_lat, zone_lon=pfz.center_lon, session_id=f"s{i}")
    # This should be fast and not do per-zone DB queries
    start = time.time()
    res = fc.analyze_fleet_convergence(pfz=pfz)
    elapsed = time.time() - start
    assert elapsed < 0.5  # should be very fast
    fc.fleet_store.clear()

if __name__ == "__main__":
    tests = [v for k,v in globals().items() if k.startswith("test_")]
    failed=[]
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed.append(t.__name__)
        except Exception as e:
            print(f"[ERROR] {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed.append(t.__name__)
    if failed:
        print(f"\n{len(failed)} failed: {failed}")
        sys.exit(1)
    else:
        print(f"\nAll {len(tests)} tests passed")
