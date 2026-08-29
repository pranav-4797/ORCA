"""SAR-Based Dark Vessel Detection — comprehensive tests
Unit + integration + demo + safety/logic tests
"""
import sys
import time
sys.path.insert(0, ".")

import math
from datetime import datetime, timezone, timedelta

# -- imports after path insert --
from sar.models import SARDetection, SARSource, SARStatus, MatchStatus, AlertLevel
from sar.boundary import distance_to_boundary, is_near_boundary, get_boundary_info
from sar.providers import DemoSARProvider, BhoonidhiSARProvider, get_provider
from sar.matching import (
    validate_coordinates, validate_confidence,
    find_match, classify_detection, compute_age_minutes, is_stale, dedupe_detections,
    get_known_vessels, SAR_MATCH_RADIUS_KM, SAR_MATCH_WINDOW_MINUTES,
)
from sar.store import sar_store
from sar.engine import run_sar_scan, SARConfig
from sar.models import KnownVessel

def _now_iso(minutes_ago=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()

# ---------------------------------------------------------------------------
# Unit: coordinate validation
# ---------------------------------------------------------------------------
def test_coordinate_validation():
    validate_coordinates(10.0, 76.0)
    try:
        validate_coordinates(91, 0)
        assert False, "should reject lat>90"
    except ValueError:
        pass
    try:
        validate_coordinates(0, 181)
        assert False, "should reject lon>180"
    except ValueError:
        pass
    # edge valid
    validate_coordinates(90, 180)
    validate_coordinates(-90, -180)

def test_confidence_validation():
    validate_confidence(0.0)
    validate_confidence(1.0)
    validate_confidence(0.5)
    try:
        validate_confidence(-0.1)
        assert False
    except ValueError:
        pass
    try:
        validate_confidence(1.5)
        assert False
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Unit: boundary distance
# ---------------------------------------------------------------------------
def test_boundary_distance_near_imbl():
    # Point very close to India-Sri Lanka Palk Strait IMBL (near 79.9, 9.93)
    dist, name, ztype = distance_to_boundary(9.94, 79.92)
    assert dist < 5.0, f"expected near IMBL, got {dist}"
    assert "IMBL" in name or ztype == "IMBL"

def test_boundary_distance_far():
    # Far from any boundary (e.g., Arabian Sea off Mumbai)
    dist, _, _ = distance_to_boundary(18.9, 72.0)
    assert dist > 100, f"expected far, got {dist}"

def test_boundary_distance_inside_mpa():
    # Inside Malvan MPA approx 16.05, 73.5
    dist, name, ztype = distance_to_boundary(16.05, 73.50)
    assert dist == 0.0, f"inside MPA should be 0, got {dist}"
    assert ztype == "MPA"

def test_is_near_boundary():
    assert is_near_boundary(9.94, 79.92, radius_km=10) is True
    assert is_near_boundary(18.9, 72.0, radius_km=10) is False

def test_boundary_info():
    info = get_boundary_info()
    assert info["feature_count"] >= 5
    assert info["is_demo"] is True
    assert "NOT FOR NAVIGATION" in info["disclaimer"]

def test_boundary_invalid_coords():
    try:
        distance_to_boundary(100, 0)
        assert False
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Unit: provider abstraction
# ---------------------------------------------------------------------------
def test_demo_provider_deterministic():
    p1 = DemoSARProvider()
    p2 = DemoSARProvider()
    obs1 = p1.fetch_observation()
    obs2 = p2.fetch_observation()
    assert len(obs1.detections) == 5
    assert len(obs2.detections) == 5
    for d1, d2 in zip(obs1.detections, obs2.detections):
        assert abs(d1.latitude - d2.latitude) < 1e-6
        assert abs(d1.confidence - d2.confidence) < 1e-6
        assert d1.detection_id == d2.detection_id
    assert obs1.provenance.status == SARStatus.SIMULATED.value
    assert obs1.provenance.source == SARSource.ORCA_SIMULATION.value
    assert "DEMO — SIMULATED" in obs1.provenance.note

def test_demo_provider_area_filter():
    p = DemoSARProvider()
    # Area that excludes all demo points
    obs = p.fetch_observation(area={"lat_min": 20, "lat_max": 21, "lon_min": 70, "lon_max": 71})
    assert len(obs.detections) == 0
    # Area that includes just one
    obs2 = p.fetch_observation(area={"lat_min": 9.9, "lat_max": 10.0, "lon_min": 79.9, "lon_max": 80.0})
    assert 1 <= len(obs2.detections) <= 5

def test_bhoonidhi_provider_no_credentials():
    # Without env, should be UNAVAILABLE, not crash
    import os
    os.environ.pop("BHOONIDHI_API_KEY", None)
    os.environ.pop("BHOONIDHI_USERNAME", None)
    # Recreate to pick up env
    b = BhoonidhiSARProvider()
    b.api_key = ""
    b.username = ""
    b.password = ""
    assert b.is_available() is False
    obs = b.fetch_observation()
    assert obs.status == SARStatus.UNAVAILABLE.value
    assert "credentials not configured" in obs.provenance.note.lower()

def test_provider_factory():
    demo = get_provider("demo")
    assert demo.name == "demo"
    bhoo = get_provider("bhoonidhi")
    assert bhoo.name == "bhoonidhi"
    auto = get_provider("auto")
    assert auto.name in ("demo", "bhoonidhi")

def test_provenance_never_mixed():
    p = DemoSARProvider()
    obs = p.fetch_observation()
    for d in obs.detections:
        assert d.status == SARStatus.SIMULATED.value
        assert d.source == SARSource.ORCA_SIMULATION.value
    # Real provider without creds returns UNAVAILABLE, not SIMULATED
    b = BhoonidhiSARProvider()
    b.api_key = ""
    b.username = ""
    b.password = ""
    obs2 = b.fetch_observation()
    assert obs2.status == SARStatus.UNAVAILABLE.value
    for d in obs2.detections:
        assert d.status != SARStatus.REAL.value

# ---------------------------------------------------------------------------
# Unit: matching — spatial + temporal
# ---------------------------------------------------------------------------
def test_spatial_matching_exact():
    det = SARDetection(
        detection_id="T1",
        latitude=10.0, longitude=76.0,
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    kv = KnownVessel(vessel_id="V1", latitude=10.001, longitude=76.001, timestamp=time.time() - 8*60)
    match = find_match(det, [kv], match_radius_km=2.0, match_window_minutes=60)
    assert match is not None
    assert match.vessel_id == "V1"

def test_spatial_matching_too_far():
    det = SARDetection(
        detection_id="T1",
        latitude=10.0, longitude=76.0,
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    kv = KnownVessel(vessel_id="V1", latitude=11.0, longitude=77.0, timestamp=time.time() - 8*60)
    match = find_match(det, [kv], match_radius_km=2.0, match_window_minutes=60)
    assert match is None

def test_temporal_matching_too_old():
    det = SARDetection(
        detection_id="T1",
        latitude=10.0, longitude=76.0,
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    # Vessel 3 hours ago, window 60 min -> no match
    kv = KnownVessel(vessel_id="V1", latitude=10.001, longitude=76.001, timestamp=time.time() - 3*3600)
    match = find_match(det, [kv], match_radius_km=2.0, match_window_minutes=60)
    assert match is None

def test_temporal_matching_within_window():
    det = SARDetection(
        detection_id="T1",
        latitude=10.0, longitude=76.0,
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    kv = KnownVessel(vessel_id="V1", latitude=10.001, longitude=76.001, timestamp=time.time() - 20*60)
    match = find_match(det, [kv], match_radius_km=2.0, match_window_minutes=60)
    assert match is not None

def test_matching_no_identity_match_alone():
    # Even if vessel_id is close string, distance far -> no match
    det = SARDetection(
        detection_id="T1",
        latitude=10.0, longitude=76.0,
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    kv = KnownVessel(vessel_id="T1", latitude=11.0, longitude=76.0, timestamp=time.time() - 5*60)
    match = find_match(det, [kv], match_radius_km=2.0, match_window_minutes=60)
    assert match is None

# ---------------------------------------------------------------------------
# Unit: unknown classification
# ---------------------------------------------------------------------------
def test_known_vessel_not_unknown():
    # Near boundary, high conf, but matched -> KNOWN, LOW alert
    det = SARDetection(
        detection_id="K1",
        latitude=9.94, longitude=79.92,  # near IMBL
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    kv = KnownVessel(vessel_id="V1", latitude=9.942, longitude=79.918, timestamp=time.time() - 5*60)
    classified = classify_detection(det, [kv], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert classified.match_status == MatchStatus.KNOWN.value
    assert classified.alert_level == AlertLevel.LOW.value
    assert classified.matched_vessel_id is not None
    assert classified.is_near_boundary is True

def test_unknown_vessel_near_boundary():
    det = SARDetection(
        detection_id="U1",
        latitude=9.94, longitude=79.92,  # near IMBL
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    classified = classify_detection(det, [], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert classified.match_status == MatchStatus.UNKNOWN.value
    assert classified.alert_level == AlertLevel.HIGH.value  # high conf + very close
    assert classified.is_near_boundary is True
    assert classified.matched_vessel_id is None

def test_unknown_vessel_far_from_boundary():
    det = SARDetection(
        detection_id="U2",
        latitude=18.9, longitude=72.8,  # far from IMBL
        acquisition_timestamp=_now_iso(10),
        confidence=0.91,
    )
    classified = classify_detection(det, [], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert classified.match_status == MatchStatus.NOT_NEAR_BOUNDARY.value
    assert classified.alert_level == AlertLevel.NONE.value

def test_low_confidence_not_unknown():
    det = SARDetection(
        detection_id="L1",
        latitude=9.94, longitude=79.92,
        acquisition_timestamp=_now_iso(10),
        confidence=0.30,
    )
    classified = classify_detection(det, [], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert classified.match_status == MatchStatus.LOW_CONFIDENCE.value
    assert classified.alert_level == AlertLevel.NONE.value

def test_high_conf_very_close_is_high():
    det = SARDetection(
        detection_id="H1",
        latitude=9.94, longitude=79.92,
        acquisition_timestamp=_now_iso(5),
        confidence=0.95,
    )
    c = classify_detection(det, [], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert c.alert_level == AlertLevel.HIGH.value

def test_medium_unknown():
    det = SARDetection(
        detection_id="M1",
        latitude=9.94, longitude=79.92,
        acquisition_timestamp=_now_iso(5),
        confidence=0.65,  # moderate
    )
    c = classify_detection(det, [], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert c.alert_level == AlertLevel.MEDIUM.value

def test_unknown_does_not_claim_illegal():
    # Every unknown alert must say "Requires authority verification" and must NOT say illegal
    from sar.engine import run_sar_scan
    sar_store.clear()
    scan = run_sar_scan(provider="demo", use_cache=False)
    for alert in scan.alerts:
        assert "Requires authority verification" in alert["message"]
        assert "illegal" not in alert["message"].lower()
        # also check recommendation field
        assert "illegal" not in alert.get("recommendation", "").lower()
        # Must clarify unknown / unmatched, not illegal fishing
        assert "Unknown / unmatched" in alert["message"] or "Unknown" in alert["title"]

# ---------------------------------------------------------------------------
# Unit: freshness / stale
# ---------------------------------------------------------------------------
def test_freshness_recent_not_stale():
    iso = _now_iso(10)
    assert is_stale(iso, stale_minutes=120) is False
    age = compute_age_minutes(iso)
    assert 9 <= age <= 11

def test_freshness_old_is_stale():
    iso = _now_iso(180)
    assert is_stale(iso, stale_minutes=120) is True

def test_stale_display():
    iso = _now_iso(180)
    det = SARDetection(
        detection_id="S1",
        latitude=9.94, longitude=79.92,
        acquisition_timestamp=iso,
        confidence=0.91,
    )
    assert compute_age_minutes(det.acquisition_timestamp) > 120

# ---------------------------------------------------------------------------
# Unit: dedupe
# ---------------------------------------------------------------------------
def test_dedupe_keeps_higher_confidence():
    iso = _now_iso(5)
    d1 = SARDetection(detection_id="A", latitude=10.0, longitude=76.0, acquisition_timestamp=iso, confidence=0.91)
    d2 = SARDetection(detection_id="B", latitude=10.0001, longitude=76.0001, acquisition_timestamp=iso, confidence=0.60)
    kept = dedupe_detections([d1, d2], radius_km=0.5)
    assert len(kept) == 1
    assert kept[0].detection_id == "A"

def test_dedupe_far_keeps_both():
    iso = _now_iso(5)
    d1 = SARDetection(detection_id="A", latitude=10.0, longitude=76.0, acquisition_timestamp=iso, confidence=0.91)
    d2 = SARDetection(detection_id="B", latitude=11.0, longitude=77.0, acquisition_timestamp=iso, confidence=0.60)
    kept = dedupe_detections([d1, d2], radius_km=0.5)
    assert len(kept) == 2

def test_invalid_coordinates_rejected():
    det = SARDetection(detection_id="BAD", latitude=100, longitude=0, acquisition_timestamp=_now_iso(5), confidence=0.91)
    try:
        classify_detection(det, [])
        assert False, "should reject invalid lat"
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Integration: full pipeline SAR observation → boundary → matching → unknown → alert
# ---------------------------------------------------------------------------
def test_integration_demo_pipeline():
    sar_store.clear()
    scan = run_sar_scan(provider="demo", use_cache=False)
    assert scan.total == 5
    assert scan.known + scan.unknown <= scan.total
    assert scan.unknown == 1, f"demo must have exactly 1 unknown, got {scan.unknown} (known={scan.known})"
    assert scan.known == 4
    # Alerts: exactly 1 HIGH (or MEDIUM) for the unknown
    assert len(scan.alerts) == 1
    alert = scan.alerts[0]
    assert alert["type"] == "UNKNOWN_VESSEL_NEAR_BOUNDARY"
    assert alert["alert_level"] in ("HIGH", "MEDIUM")
    assert "Requires authority verification" in alert["message"]
    # Unknown detection details
    unknowns = [d for d in scan.detections if d.match_status == "UNKNOWN"]
    assert len(unknowns) == 1
    u = unknowns[0]
    assert u.distance_to_boundary_km <= 10
    assert u.confidence > 0.80
    assert u.status == SARStatus.SIMULATED.value
    # Provenance
    assert scan.observation.provenance.status == SARStatus.SIMULATED.value
    assert scan.observation.provenance.source == SARSource.ORCA_SIMULATION.value

def test_integration_cache():
    sar_store.clear()
    scan1 = run_sar_scan(provider="demo", use_cache=True)
    assert scan1.cache_hit is False
    scan2 = run_sar_scan(provider="demo", use_cache=True)
    assert scan2.cache_hit is True
    assert scan2.total == scan1.total
    # Clear and scan with no cache
    sar_store.clear()
    scan3 = run_sar_scan(provider="demo", use_cache=False)
    assert scan3.cache_hit is False
    sar_store.clear()

def test_integration_reuse_known_vessels():
    # Seed fleet with a vessel near demo unknown location so it becomes KNOWN (no unknowns)
    sar_store.clear()
    # Find the demo unknown location (SAR-DEMO-001 9.950,79.920)
    import fleet_convergence as fc
    fc.fleet_store.clear(simulated_only=False)
    # Record a real vessel right at the unknown location, within match radius and window
    fc.fleet_store.record(zone_lat=9.950, zone_lon=79.920, session_id="test-real-vessel", is_simulated=False)
    # Allow timestamp to be recent (just recorded)
    scan = run_sar_scan(provider="demo", use_cache=False)
    # Because we now have a known vessel matching SAR-DEMO-001, unknown should be 0
    # Note: engine's demo fallback synthetic vessels only inject when fleet_store empty; now that we have one real,
    # the engine will still supplement synthetic for other detections, but the unknown location now has a match
    assert scan.unknown == 0, f"with real vessel at unknown spot, unknown should be 0, got {scan.unknown}"
    assert scan.known == 5
    fc.fleet_store.clear(simulated_only=False)
    sar_store.clear()

def test_demo_deterministic():
    sar_store.clear()
    s1 = run_sar_scan(provider="demo", use_cache=False)
    sar_store.clear()
    s2 = run_sar_scan(provider="demo", use_cache=False)
    assert s1.total == s2.total
    assert s1.unknown == s2.unknown
    ids1 = sorted(d.detection_id for d in s1.detections)
    ids2 = sorted(d.detection_id for d in s2.detections)
    assert ids1 == ids2
    sar_store.clear()

def test_safety_low_low_not_high():
    det = SARDetection(
        detection_id="LOW1",
        latitude=9.94, longitude=79.92,
        acquisition_timestamp=_now_iso(5),
        confidence=0.40,
    )
    c = classify_detection(det, [], boundary_radius_km=10, match_radius_km=2.0, match_window_minutes=60)
    assert c.match_status == MatchStatus.LOW_CONFIDENCE.value
    assert c.alert_level == AlertLevel.NONE.value

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = []
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
    # cleanup
    try:
        sar_store.clear()
        import fleet_convergence as fc
        fc.fleet_store.clear(simulated_only=False)
    except:
        pass
    if failed:
        print(f"\n{len(failed)} failed: {failed}")
        sys.exit(1)
    else:
        print(f"\nAll {len(tests)} tests passed")
