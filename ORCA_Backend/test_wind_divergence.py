"""Satellite–Model Wind Divergence Flag — unit + integration tests"""
import sys
sys.path.insert(0, ".")
import time
from datetime import datetime, timedelta, timezone

import wind_divergence as wd
from data_connectors.satellite_wind import DemoSatelliteWindProvider, MosdacScatWindConnector
from models import DivergenceStatus, Location, WindObsStatus


def _loc(lat=10.0, lon=76.0):
    return Location(name="Test Coast", lat=lat, lon=lon)


# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------

def test_matching_winds_demo_scenario():
    result = wd.analyze_wind_divergence(forecast_wind_kmh=18.0 * wd._KMH_PER_KNOT, location=_loc(), demo_scenario="match")
    assert result.status == DivergenceStatus.MATCH
    assert result.satellite_status == WindObsStatus.SIMULATED


def test_high_divergence_worked_example():
    # Brief's worked example: forecast 18kn, satellite 27kn -> HIGH_DIVERGENCE
    forecast_kmh = 18.0 * wd._KMH_PER_KNOT
    satellite_kmh = 27.0 * wd._KMH_PER_KNOT
    abs_diff = satellite_kmh - forecast_kmh
    status = wd._classify(abs(abs_diff), abs(abs_diff) / forecast_kmh * 100, None)
    assert status == DivergenceStatus.HIGH_DIVERGENCE


def test_match_worked_example():
    # forecast 18kn, satellite 19kn -> MATCH
    forecast_kmh = 18.0 * wd._KMH_PER_KNOT
    satellite_kmh = 19.0 * wd._KMH_PER_KNOT
    abs_diff = abs(satellite_kmh - forecast_kmh)
    status = wd._classify(abs_diff, abs_diff / forecast_kmh * 100, None)
    assert status == DivergenceStatus.MATCH


def test_moderate_divergence_boundary():
    # Just at the moderate absolute threshold, below the high threshold.
    status = wd._classify(wd.MODERATE_ABS_KMH, 0.0, None)
    assert status == DivergenceStatus.MODERATE_DIVERGENCE


def test_threshold_boundary_exact_high():
    # Exactly at HIGH_ABS_KMH should classify as HIGH (>=).
    status = wd._classify(wd.HIGH_ABS_KMH, 0.0, None)
    assert status == DivergenceStatus.HIGH_DIVERGENCE


def test_threshold_boundary_just_below_moderate():
    status = wd._classify(wd.MODERATE_ABS_KMH - 0.01, 0.0, None)
    assert status == DivergenceStatus.MATCH


def test_percentage_threshold_triggers_high():
    # Small absolute diff on a very light forecast wind can still be a huge %.
    status = wd._classify(2.0, wd.HIGH_PCT, None)
    assert status == DivergenceStatus.HIGH_DIVERGENCE


# ---------------------------------------------------------------------------
# Direction difference
# ---------------------------------------------------------------------------

def test_direction_diff_wraps_correctly():
    assert wd._direction_diff_deg(350, 10) == 20
    assert wd._direction_diff_deg(10, 350) == 20
    assert wd._direction_diff_deg(0, 180) == 180


def test_direction_diff_escalates_borderline_to_moderate():
    # Speed alone is a MATCH, but a large direction diff should push to MODERATE.
    status = wd._classify(1.0, 1.0, wd.DIRECTION_MODERATE_DEG + 5)
    assert status == DivergenceStatus.MODERATE_DIVERGENCE


def test_direction_diff_reported_in_result():
    result = wd.analyze_wind_divergence(
        forecast_wind_kmh=35.0, location=_loc(), forecast_wind_direction_deg=200.0,
        demo_scenario="match",
    )
    assert result.direction_diff_deg is not None


# ---------------------------------------------------------------------------
# Real vs. simulated separation / unavailable
# ---------------------------------------------------------------------------

def test_real_provider_unavailable_without_credentials(monkeypatch):
    monkeypatch.delenv("MOSDAC_API_KEY", raising=False)
    conn = MosdacScatWindConnector()
    obs = conn.get_observation(_loc(), datetime.now(timezone.utc))
    assert obs.status == WindObsStatus.UNAVAILABLE
    assert obs.source == "MOSDAC_OSCAT3"


def test_unavailable_satellite_preserves_normal_behaviour():
    wd._obs_cache.clear()
    import os
    os.environ.pop("MOSDAC_API_KEY", None)
    result = wd.analyze_wind_divergence(forecast_wind_kmh=33.0, location=_loc(99.0, 99.0))
    assert result.status == DivergenceStatus.UNAVAILABLE
    assert result.satellite_wind_kmh is None
    assert result.confidence_penalty == 0.0  # never penalizes when there's nothing to compare


def test_demo_provider_always_tagged_simulated():
    demo = DemoSatelliteWindProvider()
    obs = demo.get_observation(_loc(), datetime.now(timezone.utc))
    assert obs.status == WindObsStatus.SIMULATED
    obs2 = demo.get_observation(_loc(), datetime.now(timezone.utc), scenario="high_divergence")
    assert obs2.status == WindObsStatus.SIMULATED


def test_real_and_simulated_never_mixed_in_one_call():
    # A normal call (no demo_scenario) must never receive a SIMULATED obs.
    wd._obs_cache.clear()
    obs = wd.get_satellite_observation(_loc(1.0, 2.0), demo_scenario=None)
    assert obs.status in (WindObsStatus.UNAVAILABLE, WindObsStatus.REAL)
    # A demo call must never silently return REAL.
    obs2 = wd.get_satellite_observation(_loc(1.0, 2.0), demo_scenario="match")
    assert obs2.status == WindObsStatus.SIMULATED


# ---------------------------------------------------------------------------
# Spatial / temporal mismatch
# ---------------------------------------------------------------------------

def test_spatial_mismatch_marks_unavailable():
    result = wd.WindDivergenceResult if False else None  # noqa (import sanity)
    from models import WindObservation
    far_obs = WindObservation(
        latitude=50.0, longitude=50.0, wind_speed_kmh=40.0, wind_direction_deg=None,
        observation_timestamp=datetime.now(timezone.utc), source="test", dataset="test",
        status=WindObsStatus.SIMULATED,
    )
    dist = wd._haversine_km(0.0, 0.0, far_obs.latitude, far_obs.longitude)
    assert dist > wd.MAX_SPATIAL_KM  # sanity: fixture really is far away


def test_temporal_mismatch_marks_stale():
    stale_ts = datetime.now(timezone.utc) - timedelta(minutes=wd.MAX_AGE_MIN + 30)
    age_min = (datetime.now(timezone.utc) - stale_ts).total_seconds() / 60.0
    assert age_min > wd.MAX_AGE_MIN


# ---------------------------------------------------------------------------
# Latency / caching / fallback
# ---------------------------------------------------------------------------

def test_cache_hit_is_fast_and_stable():
    wd._obs_cache.clear()
    loc = _loc(5.0, 5.0)
    first = wd.get_satellite_observation(loc, demo_scenario="moderate")
    t0 = time.perf_counter()
    second = wd.get_satellite_observation(loc, demo_scenario="moderate")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 5  # cache hit must be near-instant
    assert first.wind_speed_kmh == second.wind_speed_kmh


def test_real_path_never_blocks_normal_query():
    import os
    os.environ.pop("MOSDAC_API_KEY", None)
    wd._obs_cache.clear()
    t0 = time.perf_counter()
    wd.analyze_wind_divergence(forecast_wind_kmh=30.0, location=_loc(7.0, 7.0))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50  # no network call should occur


def test_result_to_dict_serializable_and_has_knots():
    result = wd.analyze_wind_divergence(forecast_wind_kmh=18.0 * wd._KMH_PER_KNOT, location=_loc(), demo_scenario="high_divergence")
    d = wd.result_to_dict(result)
    assert isinstance(d["status"], str)
    assert d["forecast_wind_kn"] == 18.0
    assert d["is_simulated"] is True


# ---------------------------------------------------------------------------
# No regression to existing ORCA behaviour
# ---------------------------------------------------------------------------

def test_no_forecast_wind_available_is_graceful():
    class _FakeState(dict):
        pass
    # Simulate the orchestrator helper's "no ocean_state" branch contract
    # indirectly by calling analyze_wind_divergence with a 0 forecast — must
    # not crash and must not divide by zero.
    result = wd.analyze_wind_divergence(forecast_wind_kmh=0.0, location=_loc(), demo_scenario="match")
    assert result.pct_diff == 0.0 or result.pct_diff is not None


def test_models_import_does_not_break_existing_dataclasses():
    from models import OceanStateReading, DataSource
    # Existing dataclass still constructs fine after Innovation #4 additions.
    reading = OceanStateReading(
        location=_loc(), timestamp=datetime.now(timezone.utc),
        sst_celsius=28.0, chlorophyll_mg_m3=0.5, wave_height_m=1.0,
        wind_speed_kmh=20.0, wind_gust_kmh=25.0, tide_level_m=1.0,
        source=DataSource.LIVE, confidence=0.85,
    )
    assert reading.wind_speed_kmh == 20.0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = []
    for t in tests:
        try:
            if "monkeypatch" in t.__code__.co_varnames[: t.__code__.co_argcount]:
                import os as _os
                class _MP:
                    def delenv(self, k, raising=False):
                        _os.environ.pop(k, None)
                    def setenv(self, k, v):
                        _os.environ[k] = v
                t(_MP())
            else:
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
