"""
SAR Engine — end-to-end pipeline:

SAR Product
  ↓ Preprocessing (simulated/real)
  ↓ Sea / Land Mask
  ↓ Candidate Detection
  ↓ Vessel Detection
  ↓ Geolocation
  ↓ Boundary Proximity
  ↓ Known-Vessel Matching (spatial + temporal)
  ↓ Unknown Vessel Classification
  ↓ Alert Generation
  ↓ Caching + Freshness

Fisherman queries are NEVER blocked — SAR scans are invoked explicitly via
/sar/scan (authority action), results are cached, and the latest scan is
served from cache for the dashboard.
"""
from __future__ import annotations

import os
import time
import logging
from dataclasses import asdict
from typing import Optional

from .models import (
    SARObservation,
    SARDetection,
    SARProvenance,
    SARScanResult,
    SARSource,
    SARStatus,
    MatchStatus,
    AlertLevel,
)
from .providers import SARDataProvider, get_provider
from .matching import (
    classify_detection,
    get_known_vessels,
    compute_age_minutes,
    is_stale,
    dedupe_detections,
    SAR_BOUNDARY_RADIUS_KM,
    SAR_MATCH_RADIUS_KM,
    SAR_MATCH_WINDOW_MINUTES,
    SAR_STALE_MINUTES,
)
from .store import sar_store
from .boundary import get_boundary_info

logger = logging.getLogger("orca.sar.engine")

# Env-overridable config
SAR_BOUNDARY_RADIUS_KM_CFG = SAR_BOUNDARY_RADIUS_KM
SAR_MATCH_RADIUS_KM_CFG = SAR_MATCH_RADIUS_KM
SAR_MATCH_WINDOW_MINUTES_CFG = SAR_MATCH_WINDOW_MINUTES
SAR_STALE_MINUTES_CFG = SAR_STALE_MINUTES


class SARConfig:
    def __init__(
        self,
        boundary_radius_km: float = SAR_BOUNDARY_RADIUS_KM_CFG,
        match_radius_km: float = SAR_MATCH_RADIUS_KM_CFG,
        match_window_minutes: int = SAR_MATCH_WINDOW_MINUTES_CFG,
        stale_minutes: int = SAR_STALE_MINUTES_CFG,
        provider: str = "auto",
        dedupe_radius_km: float = 0.5,
        min_confidence: float = 0.50,
    ):
        self.boundary_radius_km = boundary_radius_km
        self.match_radius_km = match_radius_km
        self.match_window_minutes = match_window_minutes
        self.stale_minutes = stale_minutes
        self.provider = provider
        self.dedupe_radius_km = dedupe_radius_km
        self.min_confidence = min_confidence

    def to_dict(self) -> dict:
        return {
            "boundary_radius_km": self.boundary_radius_km,
            "match_radius_km": self.match_radius_km,
            "match_window_minutes": self.match_window_minutes,
            "stale_minutes": self.stale_minutes,
            "provider": self.provider,
            "dedupe_radius_km": self.dedupe_radius_km,
        }


def get_default_config() -> SARConfig:
    return SARConfig()


def _generate_alerts(detections: list[SARDetection]) -> list[dict]:
    """
    Generate authority alerts for UNKNOWN vessels near boundary.

    Each alert is explainable and contains:
      detection_id, coordinates, distance, confidence, acquisition_time, source,
      reason, map location, freshness

    Language: "Requires authority verification." — never "Illegal fishing confirmed."
    """
    alerts: list[dict] = []
    for d in detections:
        if d.match_status != MatchStatus.UNKNOWN.value:
            continue
        # Unknown vessel near boundary — authority alert
        alerts.append({
            "alert_id": f"ALERT-{d.detection_id}",
            "detection_id": d.detection_id,
            "type": "UNKNOWN_VESSEL_NEAR_BOUNDARY",
            "severity": d.alert_level,  # MEDIUM / HIGH
            "title": "🚨 Unknown vessel detected near maritime boundary",
            "message": (
                f"SAR confidence: {d.confidence:.0%}  "
                f"Distance to IMBL: {d.distance_to_boundary_km:.1f} km  "
                f"Observed: {d.acquisition_timestamp}  "
                f"Source: {d.source} / {d.dataset}  "
                f"No matching ORCA vessel activity was found within the configured "
                f"spatial ({SAR_MATCH_RADIUS_KM_CFG} km) / temporal ({SAR_MATCH_WINDOW_MINUTES_CFG} min) window.  "
                f"Requires authority verification.  "
                f"[Unknown / unmatched vessel — no legality determination from SAR alone.]"
            ),
            "coordinates": {"lat": d.latitude, "lon": d.longitude},
            "distance_to_boundary_km": d.distance_to_boundary_km,
            "boundary_segment": d.boundary_segment,
            "confidence": d.confidence,
            "acquisition_timestamp": d.acquisition_timestamp,
            "source": d.source,
            "dataset": d.dataset,
            "product_id": d.product_id,
            "status": d.status,
            "match_status": d.match_status,
            "alert_level": d.alert_level,
            "age_minutes": d.age_minutes,
            "is_stale": is_stale(d.acquisition_timestamp, SAR_STALE_MINUTES_CFG),
            "recommendation": "Requires authority verification.",
        })
    return alerts


def run_sar_scan(
    area: Optional[dict] = None,
    provider: Optional[SARDataProvider | str] = None,
    config: Optional[SARConfig] = None,
    known_vessels: Optional[list] = None,
    use_cache: bool = True,
    time_window: str = "today",
) -> SARScanResult:
    """
    Run a full SAR boundary scan (synchronous, but fast — no image download for demo).

    Steps (with reuse):
      1. Cache check (area+provider+window key)
      2. Fetch SAR observation via provider (Bhoonidhi or Demo)
      3. Dedupe detections
      4. For each detection: boundary distance + classification + matching
      5. Freshness / STALE flag
      6. Alert generation (UNKNOWN only)
      7. Cache + return

    This does NOT block fisherman queries: it is invoked only when authority
    surveillance is requested (POST /sar/scan) and serves cached results on GET.
    """
    t0 = time.perf_counter()
    cfg = config or get_default_config()

    # Resolve provider
    if isinstance(provider, str):
        prov = get_provider(provider)
        prov_name = provider
    elif provider is not None and hasattr(provider, "fetch_observation"):
        prov = provider  # type: ignore
        prov_name = getattr(prov, "name", "unknown")
    else:
        # provider is None or "auto"
        pref = provider if isinstance(provider, str) else (cfg.provider if cfg else "auto")
        prov = get_provider(pref)
        prov_name = getattr(prov, "name", pref)  # type: ignore

    # Cache check (only when use_cache True)
    if use_cache:
        cached = sar_store.get(area, prov_name, time_window)
        if cached is not None:
            # Return cached but recompute age / stale (time passes)
            # Wrap cached dict into SARScanResult
            obs_data = cached.get("observation", cached)
            # Recompute staleness for the cached acquisition time
            acq = obs_data.get("acquisition_time") or cached.get("acquisition_time") or ""
            stale = is_stale(acq, cfg.stale_minutes) if acq else False
            # Patch status to STALE if needed
            if stale and cached.get("status") == SARStatus.SIMULATED.value:
                cached["is_stale"] = True
            elif stale and cached.get("status") == SARStatus.REAL.value:
                cached["is_stale"] = True
                # Also update provenance status field? keep original but flag is_stale
            # Recompute age for each detection
            for d in cached.get("detections", []):
                d["age_minutes"] = compute_age_minutes(d.get("acquisition_timestamp", ""))
            result = _dict_to_scan_result(cached, cache_hit=True, processing_ms=0.0)
            return result

    # Fetch observation
    try:
        observation: SARObservation = prov.fetch_observation(area=area, time_window=time_window)  # type: ignore
    except Exception as exc:
        logger.warning("SAR provider fetch failed: %s", exc)
        # Gracefully degrade to UNAVAILABLE, not crash
        from datetime import datetime, timezone
        import time as _t
        now_iso = datetime.now(timezone.utc).isoformat()
        prov_star = getattr(prov, "name", "unknown")
        prov2 = SARProvenance(
            source=SARSource.UNAVAILABLE.value,
            dataset="UNAVAILABLE",
            product_id="",
            acquisition_time="",
            processing_time=now_iso,
            status=SARStatus.UNAVAILABLE.value,
            note=f"Provider {prov_star} fetch failed: {exc}",
        )
        observation = SARObservation(
            observation_id=f"OBS-ERROR-{int(_t.time())}",
            status=SARStatus.UNAVAILABLE.value,
            source=SARSource.UNAVAILABLE.value,
            dataset="UNAVAILABLE",
            provenance=prov2,
            detections=[],
        )

    # If observation is UNAVAILABLE (no products, no credentials, etc.), return early
    if observation.status == SARStatus.UNAVAILABLE.value:
        scan = SARScanResult(
            observation=observation,
            detections=[],
            alerts=[],
            total=0,
            known=0,
            unknown=0,
            near_boundary=0,
            config=cfg.to_dict(),
            processing_time_ms=round((time.perf_counter() - t0) * 1000, 1),
            cache_hit=False,
        )
        # Cache negative result with shorter TTL
        sar_store.set(area, prov_name, scan.to_dict(), time_window=time_window)
        return scan

    # Dedupe
    detections = dedupe_detections(list(observation.detections), radius_km=cfg.dedupe_radius_km)

    # Known vessel inventory (respect demo flag via include_simulated)
    if known_vessels is None:
        # Demo provider implies simulated fleet may be relevant for demo readability,
        # but the matching should NOT count simulated fleet as real known vessels
        # when evaluating UNKNOWN — spec says "ORCA's known vessel/activity records"
        # should be real OR real+sim? For honesty, we match against REAL only unless
        # the caller explicitly says include_simulated.
        # The demo scenario is designed so that the 4 known vessels ARE present as
        # simulated fleet? No, we need to guarantee matching deterministically without
        # relying on fleet_store state that may be empty before SIH demo.
        # Solution: if fleet_store is empty, we synthesize minimal known vessels
        # colocated with the 4 matched demo detections, so the demo always shows
        # 4 known / 1 unknown even on a fresh server. This is demo-data fallback,
        # NOT claimed as real fleet.
        from .providers import _DEMO_KNOWN_VESSELS_OFFSET, _DEMO_DETECTIONS_RAW
        from .models import KnownVessel as KV
        fleet_vessels = get_known_vessels(include_simulated=False)
        # Check if we have enough vessels to match demo detections; if not and using demo provider, inject synthetic
        is_demo = getattr(observation, "source", "") == SARSource.ORCA_SIMULATION.value
        if is_demo and not fleet_vessels:
            # Inject synthetic known vessels for demo determinism
            import time as _t2
            now_epoch = _t2.time()
            fleet_vessels = []
            for det_id, lat, lon, _conf in _DEMO_DETECTIONS_RAW:
                off = _DEMO_KNOWN_VESSELS_OFFSET.get(det_id)
                if off is None:
                    continue
                dlat, dlon = off
                fleet_vessels.append(KV(
                    vessel_id=f"SYNTH-{det_id}",
                    latitude=lat + dlat,
                    longitude=lon + dlon,
                    timestamp=now_epoch - 15*60,  # 15 min ago, within window
                    source="ORCA_SIMULATION",
                    is_simulated=True,
                    label="Demo known vessel",
                ))
        elif is_demo and fleet_vessels and len(fleet_vessels) < 3:
            # Supplement with synthetic to guarantee at least 4 matches
            import time as _t2
            now_epoch2 = _t2.time()
            existing_ids = {v.vessel_id for v in fleet_vessels}
            for det_id, lat, lon, _conf in _DEMO_DETECTIONS_RAW:
                if det_id == "SAR-DEMO-001":
                    continue  # keep unknown
                off = _DEMO_KNOWN_VESSELS_OFFSET.get(det_id)
                if off is None:
                    continue
                dlat, dlon = off
                synth_lat, synth_lon = lat + dlat, lon + dlon
                # Check if any existing vessel is already near this detection within match radius
                from .matching import _haversine_km as _hav
                already_covered = any(_hav(synth_lat, synth_lon, v.latitude, v.longitude) <= cfg.match_radius_km for v in fleet_vessels)
                if not already_covered:
                    fleet_vessels.append(KV(
                        vessel_id=f"SYNTH-{det_id}",
                        latitude=synth_lat,
                        longitude=synth_lon,
                        timestamp=now_epoch2 - 15*60,
                        source="ORCA_SIMULATION",
                        is_simulated=True,
                        label="Demo known vessel",
                    ))
        known_vessels = fleet_vessels

    # Enrich each detection (boundary + matching + alert level)
    enriched: list[SARDetection] = []
    for det in detections:
        try:
            classified = classify_detection(
                det,
                known_vessels=known_vessels,
                boundary_radius_km=cfg.boundary_radius_km,
                match_radius_km=cfg.match_radius_km,
                match_window_minutes=cfg.match_window_minutes,
            )
        except ValueError as exc:
            logger.warning("SAR detection %s invalid: %s", det.detection_id, exc)
            continue
        # Age / staleness
        classified.age_minutes = compute_age_minutes(classified.acquisition_timestamp)
        # Flag observation stale if acquisition is old
        enriched.append(classified)

    # Stale flag on observation (if any detection is stale, the observation is stale)
    is_stale_obs = any(is_stale(d.acquisition_timestamp, cfg.stale_minutes) for d in enriched) if enriched else False
    if is_stale_obs:
        observation.is_stale = True
        # Per spec, status becomes STALE but provenance still says REAL/SIMULATED
        # We keep observation.status as is but set is_stale flag; also for API status field,
        # clients should check is_stale.
    else:
        observation.is_stale = False

    # Update observation counts
    observation.total_detections = len(enriched)
    observation.known_count = sum(1 for d in enriched if d.match_status == MatchStatus.KNOWN.value)
    observation.unknown_count = sum(1 for d in enriched if d.match_status == MatchStatus.UNKNOWN.value)
    observation.detections = enriched

    # Alerts (only UNKNOWN)
    alerts = _generate_alerts(enriched)

    # Also set detection count fields on enriched for GeoJSON viz convenience
    near_boundary = sum(1 for d in enriched if d.is_near_boundary)

    scan = SARScanResult(
        observation=observation,
        detections=enriched,
        alerts=alerts,
        total=len(enriched),
        known=observation.known_count,
        unknown=observation.unknown_count,
        near_boundary=near_boundary,
        config=cfg.to_dict(),
        processing_time_ms=round((time.perf_counter() - t0) * 1000, 1),
        cache_hit=False,
    )

    # Cache result
    sar_store.set(area, prov_name, scan.to_dict(), time_window=time_window)

    return scan


def _dict_to_scan_result(d: dict, cache_hit: bool = False, processing_ms: float = 0.0) -> SARScanResult:
    """Rehydrate a cached dict into a SARScanResult (best-effort)."""
    # Rebuild observation stub from dict
    prov = d.get("provenance") or {}
    # Support both nested and flat shapes
    obs_id = d.get("observation_id") or d.get("observation", {}).get("observation_id", "cached")
    status = d.get("status") or "SIMULATED"
    source = d.get("source") or "ORCA_SIMULATION"
    dataset = d.get("dataset") or "DEMO_SAR"
    product_id = d.get("product_id") or ""
    acq = d.get("acquisition_time") or ""
    proc = d.get("processing_time") or ""
    # Build observation
    from datetime import datetime, timezone
    observation = SARObservation(
        observation_id=obs_id,
        status=status,
        source=source,
        dataset=dataset,
        product_id=product_id,
        acquisition_time=acq,
        processing_time=proc,
        provenance=SARProvenance(
            source=prov.get("source", source),
            dataset=prov.get("dataset", dataset),
            product_id=prov.get("product_id", product_id),
            acquisition_time=prov.get("acquisition_time", acq),
            processing_time=prov.get("processing_time", proc),
            status=prov.get("status", status),
            note=prov.get("note", ""),
        ),
        is_stale=d.get("is_stale", False),
        total_detections=d.get("total", 0),
        known_count=d.get("known", 0),
        unknown_count=d.get("unknown", 0),
    )
    # Rebuild detections as SARDetection
    dets = []
    for dd in d.get("detections", []):
        try:
            det = SARDetection(
                detection_id=dd.get("detection_id") or dd.get("id", "unk"),
                latitude=float(dd.get("latitude") or dd.get("lat", 0)),
                longitude=float(dd.get("longitude") or dd.get("lon", 0)),
                acquisition_timestamp=dd.get("acquisition_timestamp") or dd.get("acquisition_time") or acq,
                confidence=float(dd.get("confidence", 0.5)),
                source=dd.get("source", source),
                dataset=dd.get("dataset", dataset),
                product_id=dd.get("product_id", product_id),
                distance_to_boundary_km=float(dd.get("distance_to_boundary_km") or dd.get("distance_to_boundary", 999)),
                boundary_segment=dd.get("boundary_segment", ""),
                boundary_type=dd.get("boundary_type", ""),
                is_near_boundary=bool(dd.get("is_near_boundary", False)),
                matched_vessel_id=dd.get("matched_vessel_id"),
                match_status=dd.get("match_status", "UNKNOWN"),
                alert_level=dd.get("alert_level", "NONE"),
                status=dd.get("status", status),
                age_minutes=dd.get("age_minutes"),
            )
            dets.append(det)
        except Exception:
            continue
    return SARScanResult(
        observation=observation,
        detections=dets,
        alerts=d.get("alerts", []),
        total=d.get("total", len(dets)),
        known=d.get("known", 0),
        unknown=d.get("unknown", 0),
        near_boundary=d.get("near_boundary", 0),
        config=d.get("config", {}),
        processing_time_ms=processing_ms,
        cache_hit=cache_hit,
    )
