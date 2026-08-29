"""
SAR Vessel Matching — spatial + temporal matching against ORCA's known activity.

A detection is matched when a known vessel is sufficiently close BOTH
spatially and temporally. Identity matching alone is NOT used.

Config (env-overridable, not scattered):
  ORCA_SAR_MATCH_RADIUS_KM       default 2.0
  ORCA_SAR_MATCH_WINDOW_MINUTES  default 60
  ORCA_SAR_MIN_CONFIDENCE        default 0.50  (below: LOW_CONFIDENCE, not UNKNOWN)

Unknown vessel classification:
  if detection is near boundary AND no valid match -> UNKNOWN_VESSEL_NEAR_BOUNDARY
  Do NOT claim "illegal" — only "Unknown / unmatched — requires authority verification."

Alert priority (explainable):
  LOW    = known vessel near boundary
  MEDIUM = unknown vessel, moderate confidence or farther from boundary
  HIGH   = high-confidence unknown vessel very close to boundary
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from typing import Optional

from .models import SARDetection, KnownVessel, MatchStatus, AlertLevel

# Config — env-overridable
SAR_MATCH_RADIUS_KM = float(os.getenv("ORCA_SAR_MATCH_RADIUS_KM", "2.0").strip() or 2.0)
SAR_MATCH_WINDOW_MINUTES = int(os.getenv("ORCA_SAR_MATCH_WINDOW_MINUTES", "60").strip() or 60)
SAR_MIN_CONFIDENCE = float(os.getenv("ORCA_SAR_MIN_CONFIDENCE", "0.50").strip() or 0.50)
SAR_HIGH_CONFIDENCE = float(os.getenv("ORCA_SAR_HIGH_CONFIDENCE", "0.80").strip() or 0.80)
SAR_BOUNDARY_RADIUS_KM = float(os.getenv("ORCA_SAR_BOUNDARY_RADIUS_KM", "10").strip() or 10)
# Cache TTL / freshness
SAR_STALE_MINUTES = int(os.getenv("ORCA_SAR_STALE_MINUTES", "120").strip() or 120)

# Alert thresholds
HIGH_ALERT_DISTANCE_KM = float(os.getenv("ORCA_SAR_HIGH_ALERT_DISTANCE_KM", "5").strip() or 5)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_epoch(iso_str: str) -> Optional[float]:
    if not iso_str:
        return None
    try:
        # Python 3.11+: fromisoformat handles Z via replace
        s = iso_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def validate_coordinates(lat: float, lon: float):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Invalid coordinates: lat={lat} lon={lon}")


def validate_confidence(conf: float):
    if not (0.0 <= conf <= 1.0):
        raise ValueError(f"Invalid confidence: {conf}")


def get_known_vessels(include_simulated: bool = False) -> list[KnownVessel]:
    """
    Unified known-vessel inventory from ORCA's own records.

    Sources:
      - fleet_convergence.fleet_store  (recommendation history -> vessel activity)
      - proactive_monitor._users        (registered vessel/user positions)
      - session-backed ad-hoc vessels   (if available)

    Real and simulated are flagged; callers choose include_simulated.
    No private user identities are exposed — only vessel_id + position.
    """
    vessels: list[KnownVessel] = []

    # 1. Fleet activities (highest volume)
    try:
        import fleet_convergence as fc
        recent = fc.fleet_store.get_recent(window_hours=6, include_simulated=include_simulated)
        for a in recent:
            vessels.append(KnownVessel(
                vessel_id=f"ORCA-FLEET-{a.session_id[:8]}",
                latitude=a.zone_lat,
                longitude=a.zone_lon,
                timestamp=a.timestamp,
                source="ORCA_FLEET_SIM" if a.is_simulated else "ORCA_FLEET",
                is_simulated=a.is_simulated,
                label="Fleet activity",
            ))
    except Exception:
        pass

    # 2. Registered users (proactive monitor)
    try:
        from agents.proactive_monitor import _users as _pm_users
        for uid, u in dict(_pm_users).items():
            try:
                lat = float(u.get("lat"))
                lon = float(u.get("lon"))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
            except Exception:
                continue
            vessels.append(KnownVessel(
                vessel_id=f"ORCA-USER-{uid[:8]}",
                latitude=lat,
                longitude=lon,
                timestamp=float(u.get("registered_at", time.time())),
                source="ORCA_USER",
                is_simulated=False,
                label="Registered vessel",
            ))
    except Exception:
        pass

    return vessels


def find_match(
    detection: SARDetection,
    known_vessels: list[KnownVessel],
    match_radius_km: float = SAR_MATCH_RADIUS_KM,
    match_window_minutes: int = SAR_MATCH_WINDOW_MINUTES,
) -> Optional[KnownVessel]:
    """
    Find the closest known vessel within BOTH spatial and temporal tolerances.

    Returns the best match (smallest haversine) that satisfies both windows,
    or None when no vessel satisfies both.
    """
    det_epoch = _parse_epoch(detection.acquisition_timestamp)
    best: Optional[KnownVessel] = None
    best_dist = float("inf")
    window_s = match_window_minutes * 60
    for kv in known_vessels:
        # Temporal check first (cheaper)
        if det_epoch is not None:
            if abs(kv.timestamp - det_epoch) > window_s:
                continue
        # else: if detection has no timestamp, allow match on spatial alone
        dist = _haversine_km(detection.latitude, detection.longitude, kv.latitude, kv.longitude)
        if dist <= match_radius_km and dist < best_dist:
            best = kv
            best_dist = dist
    return best


def classify_detection(
    detection: SARDetection,
    known_vessels: list[KnownVessel],
    boundary_radius_km: float = SAR_BOUNDARY_RADIUS_KM,
    match_radius_km: float = SAR_MATCH_RADIUS_KM,
    match_window_minutes: int = SAR_MATCH_WINDOW_MINUTES,
) -> SARDetection:
    """
    Enrich one detection with:
      distance_to_boundary + is_near_boundary + match_status + alert_level

    Pipeline:
      1. Validate coordinates & confidence
      2. Compute distance_to_boundary
      3. Check confidence threshold (LOW_CONFIDENCE -> filtered)
      4. If not near boundary -> NOT_NEAR_BOUNDARY (not surfaced as alert)
      5. If near boundary -> spatial+temporal match against ORCA inventory
      6. Matched -> KNOWN (LOW alert)
         Unmatched -> UNKNOWN (MEDIUM or HIGH by distance+confidence)

    Never claims "illegal" — only UNKNOWN/ unmatched.
    """
    # Validate
    validate_coordinates(detection.latitude, detection.longitude)
    validate_confidence(detection.confidence)

    # Boundary proximity
    from .boundary import distance_to_boundary as _dist_to_boundary
    try:
        dist, seg, ztype = _dist_to_boundary(detection.latitude, detection.longitude)
    except ValueError:
        raise
    detection.distance_to_boundary_km = dist
    detection.boundary_segment = seg
    detection.boundary_type = ztype
    detection.is_near_boundary = dist <= boundary_radius_km

    # Confidence gate — low-confidence detections are not UNKNOWN, they are LOW_CONFIDENCE
    # They still appear but with NONE alert and LOW_CONFIDENCE status (so authority doesn't chase ghosts)
    if detection.confidence < SAR_MIN_CONFIDENCE:
        detection.match_status = MatchStatus.LOW_CONFIDENCE.value
        detection.alert_level = AlertLevel.NONE.value
        detection.matched_vessel_id = None
        return detection

    if not detection.is_near_boundary:
        detection.match_status = MatchStatus.NOT_NEAR_BOUNDARY.value
        detection.alert_level = AlertLevel.NONE.value
        detection.matched_vessel_id = None
        return detection

    # Near boundary + sufficient confidence -> attempt matching
    match = find_match(detection, known_vessels, match_radius_km, match_window_minutes)
    if match is not None:
        detection.matched_vessel_id = match.vessel_id
        detection.match_status = MatchStatus.KNOWN.value
        detection.alert_level = AlertLevel.LOW.value
        return detection

    # Unknown vessel near boundary — the core innovation
    detection.matched_vessel_id = None
    detection.match_status = MatchStatus.UNKNOWN.value
    # Alert priority: HIGH when high confidence + very close to boundary
    if detection.confidence >= SAR_HIGH_CONFIDENCE and dist <= HIGH_ALERT_DISTANCE_KM:
        detection.alert_level = AlertLevel.HIGH.value
    else:
        detection.alert_level = AlertLevel.MEDIUM.value
    return detection


def compute_age_minutes(acquisition_timestamp: str) -> Optional[float]:
    epoch = _parse_epoch(acquisition_timestamp)
    if epoch is None:
        return None
    return round((time.time() - epoch) / 60.0, 1)


def is_stale(acquisition_timestamp: str, stale_minutes: int = SAR_STALE_MINUTES) -> bool:
    age = compute_age_minutes(acquisition_timestamp)
    if age is None:
        return False
    return age > stale_minutes


def dedupe_detections(detections: list[SARDetection], radius_km: float = 0.5) -> list[SARDetection]:
    """
    Remove duplicate detections that are within radius_km of each other,
    keeping the higher-confidence one.
    """
    if not detections:
        return []
    # Sort by confidence descending so first seen is best
    sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
    kept: list[SARDetection] = []
    for d in sorted_dets:
        dup = False
        for k in kept:
            if _haversine_km(d.latitude, d.longitude, k.latitude, k.longitude) <= radius_km:
                dup = True
                break
        if not dup:
            kept.append(d)
    # Restore original order? Keep confidence order for deterministic tests
    return kept
