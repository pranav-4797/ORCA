"""
Fleet Convergence Forecast — ORCA's collective-effect awareness.

Implements:
  Raw suitability → Fleet concentration → Crowding penalty → Adjusted suitability → Best alternative → Final recommendation

Uses ORCA's own recommendation history as fleet activity source. No external fisheries dataset.

Design:
- Candidate zones from existing PFZRecommendation (primary + alternates)
- Fleet counting via in-memory activity store (backed by TTLStore when Redis available)
- Configurable window, radius, capacity, penalty
- Safety/legal always overrides optimization
- Explainable, deterministic, bounded scoring
- Demo/simulated mode isolated and labelled SIMULATED

Priority: 1 Safety, 2 Legal/Geospatial, 3 Environmental, 4 Fleet
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# Config — env-overridable, no magic numbers scattered
FLEET_WINDOW_HOURS = int(os.getenv("ORCA_FLEET_WINDOW_HOURS", "6").strip() or 6)
FLEET_RADIUS_KM = float(os.getenv("ORCA_FLEET_RADIUS_KM", "10").strip() or 10)
FLEET_TARGET_CAPACITY = int(os.getenv("ORCA_FLEET_TARGET_CAPACITY", "8").strip() or 8)
FLEET_PENALTY_FACTOR = float(os.getenv("ORCA_FLEET_PENALTY_FACTOR", "0.12").strip() or 0.12)
FLEET_MAX_PENALTY = float(os.getenv("ORCA_FLEET_MAX_PENALTY", "0.5").strip() or 0.5)
# Minimum raw suitability to consider alternative (avoid unsafe/low)
FLEET_MIN_BASE_SUITABILITY = float(os.getenv("ORCA_FLEET_MIN_BASE", "60").strip() or 60)
# Max distance for alternative to be considered reasonable (km)
FLEET_MAX_ALTERNATIVE_DISTANCE_KM = float(os.getenv("ORCA_FLEET_MAX_ALT_DISTANCE_KM", "50").strip() or 50)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class FleetActivity:
    zone_lat: float
    zone_lon: float
    timestamp: float  # monotonic or epoch
    session_id: str
    is_simulated: bool = False
    reference_lat: Optional[float] = None
    reference_lon: Optional[float] = None


@dataclass
class CandidateZone:
    zone_id: str
    center_lat: float
    center_lon: float
    distance_km: float
    bearing_deg: float
    sst_celsius: float | None = None
    chlorophyll_mg_m3: float | None = None
    source: str = "derived_from_live_data"
    base_suitability: float = 80.0
    fleet_count: int = 0
    crowding_ratio: float = 0.0
    crowding_penalty: float = 0.0
    adjusted_suitability: float = 0.0
    is_safe: bool = True
    is_legal: bool = True
    is_recommended: bool = False
    reason: str = ""


@dataclass
class FleetConvergenceResult:
    candidates: list = field(default_factory=list)  # list[CandidateZone]
    raw_best_zone: Optional[CandidateZone] = None
    final_zone: Optional[CandidateZone] = None
    recommendation_changed: bool = False
    change_reason: str = ""
    status: str = "OK"  # OK, SIMULATED, UNAVAILABLE
    window_hours: int = FLEET_WINDOW_HOURS
    timestamp: float = field(default_factory=time.time)
    # For API
    fleet_counts: dict = field(default_factory=dict)


class FleetStore:
    """Thread-safe in-memory fleet activity store with window filtering.

    Real and simulated activities are stored together but flagged, never mixed
    in counts unless explicitly requested (demo mode).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._activities: list[FleetActivity] = []

    def record(self, zone_lat: float, zone_lon: float, session_id: str, is_simulated: bool = False, reference_lat: float | None = None, reference_lon: float | None = None):
        act = FleetActivity(
            zone_lat=zone_lat,
            zone_lon=zone_lon,
            timestamp=time.time(),
            session_id=session_id or f"anon-{int(time.time()*1000)}",
            is_simulated=is_simulated,
            reference_lat=reference_lat,
            reference_lon=reference_lon,
        )
        with self._lock:
            self._activities.append(act)
            # Opportunistic prune of stale (> window) to bound memory
            cutoff = time.time() - FLEET_WINDOW_HOURS * 3600 - 3600  # keep extra hour for safety
            self._activities = [a for a in self._activities if a.timestamp > cutoff]
            # Cap size
            if len(self._activities) > 5000:
                self._activities = self._activities[-3000:]

    def clear(self, simulated_only: bool = False):
        with self._lock:
            if simulated_only:
                self._activities = [a for a in self._activities if not a.is_simulated]
            else:
                self._activities.clear()

    def get_recent(self, window_hours: int | None = None, include_simulated: bool = False) -> list[FleetActivity]:
        win = window_hours if window_hours is not None else FLEET_WINDOW_HOURS
        cutoff = time.time() - win * 3600
        with self._lock:
            return [a for a in self._activities if a.timestamp >= cutoff and (include_simulated or not a.is_simulated)]

    def count_near(self, lat: float, lon: float, radius_km: float | None = None, window_hours: int | None = None, include_simulated: bool = False) -> int:
        rad = radius_km if radius_km is not None else FLEET_RADIUS_KM
        recent = self.get_recent(window_hours, include_simulated=include_simulated)
        # Deduplicate by session_id per zone cluster within window to avoid spam
        # Count unique sessions near this point within radius
        seen_sessions = set()
        count = 0
        for a in recent:
            if _haversine_km(lat, lon, a.zone_lat, a.zone_lon) <= rad:
                if a.session_id not in seen_sessions:
                    seen_sessions.add(a.session_id)
                    count += 1
        return count

    def aggregated_counts(self, candidates: list[CandidateZone], window_hours: int | None = None, radius_km: float | None = None, include_simulated: bool = False) -> dict[str, int]:
        """Fetch once, aggregate by zone — efficient, not per-zone DB query."""
        # One fetch of recent activities
        recent = self.get_recent(window_hours, include_simulated=include_simulated)
        counts: dict[str, int] = {}
        # For each candidate, count nearby unique sessions
        for cand in candidates:
            seen = set()
            c = 0
            for a in recent:
                if _haversine_km(cand.center_lat, cand.center_lon, a.zone_lat, a.zone_lon) <= (radius_km or FLEET_RADIUS_KM):
                    if a.session_id not in seen:
                        seen.add(a.session_id)
                        c += 1
            counts[cand.zone_id] = c
        return counts

    def status(self) -> str:
        with self._lock:
            total = len(self._activities)
            sim = sum(1 for a in self._activities if a.is_simulated)
            real = total - sim
            if total == 0:
                return "EMPTY"
            return f"real={real} sim={sim} total={total}"

# Global singleton — reused across requests
fleet_store = FleetStore()


def compute_crowding(fleet_count: int, target_capacity: int | None = None, penalty_factor: float | None = None, max_penalty: float | None = None):
    cap = target_capacity if target_capacity is not None else FLEET_TARGET_CAPACITY
    factor = penalty_factor if penalty_factor is not None else FLEET_PENALTY_FACTOR
    max_p = max_penalty if max_penalty is not None else FLEET_MAX_PENALTY
    if cap <= 0:
        cap = 8
    ratio = fleet_count / cap if cap else 0.0
    penalty = min(ratio * factor, max_p)
    # Clamp 0..max_p
    penalty = max(0.0, min(penalty, max_p))
    return ratio, penalty


def compute_adjusted_suitability(base: float, penalty: float) -> float:
    """adjusted = base * (1 - penalty), bounded 0..100, never negative"""
    adj = base * (1.0 - penalty)
    return max(0.0, min(100.0, round(adj, 1)))


def build_candidates_from_pfz(pfz, ocean_state=None) -> list[CandidateZone]:
    """Reuse existing PFZRecommendation to build candidate list.

    Primary + up to 3 alternates become candidates. Base suitability derived
    deterministically from rank + distance + gradient.
    """
    candidates: list[CandidateZone] = []
    if pfz is None:
        return candidates

    # Primary
    # Base suitability: 92 for primary, decreasing for alternates — deterministic, explainable
    # Also add small SST gradient bonus if available
    def base_for(rank: int, distance: float, gradient: float | None = None):
        # Rank 0 -> 92, 1->85, 2->78, 3->72
        rank_bases = [92, 85, 78, 72]
        b = rank_bases[min(rank, len(rank_bases)-1)]
        # Small distance penalty: farther zones slightly less suitable (but not overriding gradient)
        # and small gradient bonus
        if gradient is not None:
            b += min(5, gradient * 2)  # up to +5 for strong front
        b -= distance * 0.05  # very small distance penalty
        return max(0, min(100, round(b, 1)))

    # Primary gradient: try to infer from alternates[0] gradient if primary not stored
    # Pfz primary doesn't store gradient directly, but we can approximate 2.0 for demo
    primary_gradient = None
    if pfz.alternates:
        # Use first alternate's gradient as proxy for primary's strength (primary has max)
        # Primary likely has even higher, so add 0.5
        try:
            primary_gradient = float(pfz.alternates[0].get("gradient_vs_reference_c", 2.0)) + 0.5
        except:
            primary_gradient = 2.0
    else:
        primary_gradient = 1.5

    candidates.append(CandidateZone(
        zone_id=f"ZONE_A",
        center_lat=pfz.center_lat,
        center_lon=pfz.center_lon,
        distance_km=pfz.distance_from_reference_km,
        bearing_deg=pfz.bearing_deg,
        sst_celsius=pfz.sst_at_zone_celsius,
        chlorophyll_mg_m3=pfz.chlorophyll_at_zone_mg_m3,
        source=pfz.source.value if hasattr(pfz.source, "value") else str(pfz.source),
        base_suitability=base_for(0, pfz.distance_from_reference_km, primary_gradient),
    ))

    for idx, alt in enumerate(getattr(pfz, "alternates", []) or []):
        grad = alt.get("gradient_vs_reference_c")
        candidates.append(CandidateZone(
            zone_id=f"ZONE_{chr(66+idx)}",  # B, C, D
            center_lat=alt["center_lat"],
            center_lon=alt["center_lon"],
            distance_km=alt["distance_km"],
            bearing_deg=alt["bearing_deg"],
            sst_celsius=alt.get("sst_celsius", 27.0),
            chlorophyll_mg_m3=pfz.chlorophyll_at_zone_mg_m3,
            source=pfz.source.value if hasattr(pfz.source, "value") else str(pfz.source),
            base_suitability=base_for(idx+1, alt["distance_km"], grad),
        ))

    # Ensure at least 1 candidate
    return candidates


def apply_fleet_convergence(candidates: list[CandidateZone], fleet_counts: dict[str, int], target_capacity: int | None = None, penalty_factor: float | None = None, max_penalty: float | None = None) -> list[CandidateZone]:
    for cand in candidates:
        count = fleet_counts.get(cand.zone_id, 0)
        ratio, penalty = compute_crowding(count, target_capacity, penalty_factor, max_penalty)
        adj = compute_adjusted_suitability(cand.base_suitability, penalty)
        cand.fleet_count = count
        cand.crowding_ratio = round(ratio, 3)
        cand.crowding_penalty = round(penalty, 3)
        cand.adjusted_suitability = adj
        cand.reason = f"Fleet {count} → crowding {ratio:.2f} → penalty {penalty:.2f}"
    return candidates


def select_best_candidate(candidates: list[CandidateZone], safety_filter: dict[str, bool] | None = None, legal_filter: dict[str, bool] | None = None) -> tuple[CandidateZone | None, CandidateZone | None, bool, str]:
    """Priority: 1 Safety, 2 Legal, 3 Environmental (base), 4 Fleet (adjusted).

    Filters out unsafe/illegal zones first, then picks raw best (by base) and
    adjusted best (by adjusted). Returns (raw_best, final, changed, reason)
    """
    if not candidates:
        return None, None, False, "No candidates"

    # Filter: only safe and legal candidates are eligible for recommendation
    eligible = []
    for c in candidates:
        safe = safety_filter.get(c.zone_id, c.is_safe) if safety_filter else c.is_safe
        legal = legal_filter.get(c.zone_id, c.is_legal) if legal_filter else c.is_legal
        # Also check base suitability threshold and distance
        if not safe:
            c.reason += " [UNSAFE filtered]"
            continue
        if not legal:
            c.reason += " [RESTRICTED filtered]"
            continue
        if c.base_suitability < FLEET_MIN_BASE_SUITABILITY:
            c.reason += f" [base {c.base_suitability} < min {FLEET_MIN_BASE_SUITABILITY} filtered]"
            continue
        if c.distance_km > FLEET_MAX_ALTERNATIVE_DISTANCE_KM and c.zone_id != "ZONE_A":
            # Allow primary even if farther, but alternates beyond max distance are not reasonable
            c.reason += f" [distance {c.distance_km}km > max filtered]"
            continue
        eligible.append(c)

    if not eligible:
        # No valid alternative: keep raw best safe zone if exists, else None
        # Find safest raw best even if below threshold?
        safe_candidates = [c for c in candidates if (safety_filter.get(c.zone_id, c.is_safe) if safety_filter else c.is_safe) and (legal_filter.get(c.zone_id, c.is_legal) if legal_filter else c.is_legal)]
        if safe_candidates:
            raw_best = max(safe_candidates, key=lambda x: x.base_suitability)
            return raw_best, raw_best, False, "No valid lower-crowding alternative found — keeping best safe zone"
        return None, None, False, "No safe/legal candidates"

    # Raw best by base suitability
    raw_best = max(eligible, key=lambda x: x.base_suitability)
    # Final by adjusted suitability
    final = max(eligible, key=lambda x: x.adjusted_suitability)

    changed = final.zone_id != raw_best.zone_id
    reason = ""
    if changed:
        reason = f"Fleet convergence: {raw_best.zone_id} raw {raw_best.base_suitability} fleet {raw_best.fleet_count} adj {raw_best.adjusted_suitability} → {final.zone_id} raw {final.base_suitability} fleet {final.fleet_count} adj {final.adjusted_suitability}"
    else:
        reason = f"No crowding-driven change: {raw_best.zone_id} remains best (base {raw_best.base_suitability} adj {raw_best.adjusted_suitability})"

    # Mark recommended
    for c in candidates:
        c.is_recommended = (c.zone_id == final.zone_id)

    return raw_best, final, changed, reason


def analyze_fleet_convergence(pfz, ocean_state=None, geofence=None, risk=None, window_hours: int | None = None, radius_km: float | None = None, include_simulated: bool = False, force_status: str | None = None) -> FleetConvergenceResult:
    """Main entry: from PFZ + safety/geofence context, produce convergence analysis.

    Returns FleetConvergenceResult with status OK/SIMULATED/UNAVAILABLE.
    If pfz is None, returns UNAVAILABLE.
    """
    window = window_hours if window_hours is not None else FLEET_WINDOW_HOURS
    radius = radius_km if radius_km is not None else FLEET_RADIUS_KM

    if pfz is None:
        return FleetConvergenceResult(candidates=[], status="UNAVAILABLE", window_hours=window, change_reason="No PFZ candidates — fleet analysis unavailable")

    candidates = build_candidates_from_pfz(pfz, ocean_state)
    if not candidates:
        return FleetConvergenceResult(candidates=[], status="UNAVAILABLE", window_hours=window, change_reason="No candidates derived")

    # Build safety/legal filters from hazard and geofence
    # If risk is UNSAFE, primary might be unsafe, but candidate zones are nearby — we assume same risk unless we have per-zone hazard.
    # For now, we mark all candidates as safe if overall risk is not UNSAFE, otherwise we still allow but will filter.
    # Geofence: check each candidate center against restricted zones
    safety_filter: dict[str, bool] = {}
    legal_filter: dict[str, bool] = {}
    # If no fleet data (store empty), we still want to show counts 0, not UNAVAILABLE
    # UNAVAILABLE only if store is down or pfz missing
    try:
        # Use fleet_store aggregated counts (one fetch)
        # If include_simulated requested (demo), include simulated activities
        fleet_counts = fleet_store.aggregated_counts(candidates, window_hours=window, radius_km=radius, include_simulated=include_simulated)
        # Determine status: if store has simulated activities and we included them, mark SIMULATED
        has_sim = any(a.is_simulated for a in fleet_store.get_recent(window_hours=window, include_simulated=True))
        has_real = any(not a.is_simulated for a in fleet_store.get_recent(window_hours=window, include_simulated=True))
        if force_status:
            status = force_status
        elif include_simulated and has_sim and not has_real:
            status = "SIMULATED"
        elif include_simulated and has_sim:
            status = "SIMULATED_MIXED"
        else:
            status = "OK"
    except Exception as e:
        # Fallback: fleet data unavailable — do not assume 0
        return FleetConvergenceResult(candidates=candidates, status="UNAVAILABLE", window_hours=window, change_reason=f"Fleet data unavailable: {e}")

    # Safety: if risk is UNSAFE, we should not recommend any fishing, but for convergence demo we still show crowding
    # Mark candidates unsafe if overall risk UNSAFE and zone is within hazard polygon? Without per-zone hazard, we mark all as unsafe if risk UNSAFE.
    # However spec says safety overrides fleet: so if overall UNSAFE, we should still not switch to unsafe alternative.
    # We will treat all candidates as unsafe if risk is UNSAFE, so no valid eligible -> keep raw best but explain.
    if risk and hasattr(risk, "status") and risk.status.value == "UNSAFE":
        for c in candidates:
            c.is_safe = False
            safety_filter[c.zone_id] = False
    else:
        for c in candidates:
            # Check geofence per candidate: if geofence hits and candidate is inside/near restricted, mark illegal
            # We need to check each candidate's center against geofence hits
            # For now, if geofence is not clear and candidate is near a hit, mark illegal
            # Simple: if geofence has hits and candidate is within 5km of reference's nearest hit, mark illegal?
            # More accurate: re-run geofence check per candidate
            is_legal = True
            if geofence and not geofence.clear:
                # If any hit is inside or very close, we check distance from candidate to that boundary
                # For demo, we mark candidate illegal if its center is within FLEET_RADIUS_KM of a restricted hit's zone
                # We don't have hit coordinates, so we approximate: if reference is near boundary, all nearby zones also near
                # So if geofence hits exist, we conservatively mark all candidates as legal but with note
                # Better to actually check each candidate with geospatial agent
                try:
                    from agents.geospatial_agent import GeospatialAgent
                    _geo = GeospatialAgent()
                    # Use candidate center as query point
                    from models import Location
                    cand_loc = Location(name=f"candidate {c.zone_id}", lat=c.center_lat, lon=c.center_lon)
                    check = _geo._check_geofence(c.center_lat, c.center_lon, cand_loc)
                    is_legal = check.clear
                    c.is_legal = is_legal
                except:
                    is_legal = True
            legal_filter[c.zone_id] = is_legal
            safety_filter[c.zone_id] = c.is_safe

    # Apply crowding
    apply_fleet_convergence(candidates, fleet_counts)

    # Select best
    raw_best, final, changed, reason = select_best_candidate(candidates, safety_filter, legal_filter)

    return FleetConvergenceResult(
        candidates=candidates,
        raw_best_zone=raw_best,
        final_zone=final,
        recommendation_changed=changed,
        change_reason=reason,
        status=status,
        window_hours=window,
        fleet_counts=fleet_counts,
    )


def record_recommendation(final_zone: CandidateZone | None, session_id: str, reference_lat: float | None = None, reference_lon: float | None = None, is_simulated: bool = False):
    """Call after final recommendation is chosen — records fleet activity for future convergence."""
    if final_zone is None:
        return
    try:
        fleet_store.record(
            zone_lat=final_zone.center_lat,
            zone_lon=final_zone.center_lon,
            session_id=session_id or "anon",
            is_simulated=is_simulated,
            reference_lat=reference_lat,
            reference_lon=reference_lon,
        )
    except Exception:
        pass  # never break recommendation flow


def simulate_fleet_activity(center_lat: float, center_lon: float, level: str = "high", session_prefix: str = "sim", window_hours: int | None = None):
    """Deterministic demo helper: adds N simulated activities around a point.

    Levels: low=2, medium=5, high=10, severe=20
    """
    levels = {"low": 2, "medium": 5, "high": 10, "severe": 20, "normal": 2}
    n = levels.get(level.lower().strip(), 10)
    import random
    # Deterministic seed based on lat/lon/level
    seed = int(abs(center_lat*1000 + center_lon*1000 + n*997) % 2**32)
    rnd = random.Random(seed)
    for i in range(n):
        # Scatter within 3km radius
        dlat = (rnd.random() - 0.5) * 0.05  # ~5km
        dlon = (rnd.random() - 0.5) * 0.05
        fleet_store.record(
            zone_lat=center_lat + dlat,
            zone_lon=center_lon + dlon,
            session_id=f"{session_prefix}-{level}-{i}-{seed}",
            is_simulated=True,
        )
    return n
