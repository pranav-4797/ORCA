"""
PFZ Agent ("Finds where the fish likely are")

Responsibility: locate the nearest Potential Fishing Zone for the user's
reference point, with distance, bearing and the evidence that justifies it.

Data source (per SIH-2026 decision -- replaces the unverified Bhuvan WMS):
    Tier 1 -- OFFICIAL INCOIS / SAMUDRA feeds, reached through
    data_connectors.incois_pfz (the ONLY module that talks to INCOIS):
        * pfzMobile : 1,223 landing centres, each carrying today's official
          PFZ advisory where one is issued (Direction, Distance, Depth and
          the zone's lat/lon relative to the centre).
        * pfzLines  : digitized PFZ zone LineStrings (official geometry).
        * TextData  : per-sector advisory narrative text.
    The nearest centre to the query point is found with a KD-tree spatial
    index (agents.geospatial_agent.LandingCentreIndex) in well under 10 ms;
    its PLatitude/PLongitude/Direction/Distance/Depth are parsed into the
    PFZRecommendation WITHOUT any LLM step, so coordinates are always the
    ones INCOIS actually issued. Tagged DataSource.INCOIS_LIVE (Tier 1/2).

    Fallback (unchanged behaviour): if the advisory cannot be reached OR no
    zone is issued near the query point, the zone is DERIVED FROM LIVE DATA
    (strongest SST front inside agents/pfz_agent._derive_zone) and tagged
    DataSource.DERIVED_LIVE. Only if even that live sampling fails does the
    deterministic seeded fallback run, tagged DataSource.SIMULATED.

The public interface (run / name) is unchanged so the LangGraph Orchestrator
(and its planner/dispatch) need no modifications.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request

import llm_client
from agents.geospatial_agent import LandingCentreIndex
from data_connectors.geocode import GeocodeUnavailableError, reverse_geocode
from data_connectors.incois_pfz import (
    IncoisUnavailableError,
    get_live_pfz_sync,
)
from models import (
    AgentTrace,
    DataSource,
    Location,
    OceanStateReading,
    PFZRecommendation,
)
_ENABLE_LLM_NOTE = os.getenv("ORCA_ENABLE_LLM_REASONING", "").strip().lower() in ("1", "true", "yes")

_MARINE_URL = "https://incois.gov.in/thredds/wms/osf/winds/SST_NIO"  # INCOIS SST (Open-Meteo removed)
_HTTP_TIMEOUT_S = 10.0

# Maximum distance (km) between the query point and the nearest INCOIS landing
# centre before we fall back to the derived zone. A 150 km cap stops the agent
# recommending an advisory zone on the far side of India for a mid-sea query.
_MAX_CENTRE_DIST_KM = 150.0
_MAX_CENTRE_CANDIDATES = 40          # KD-tree lookup depth for issued-searching
_MAX_ALTERNATES = 2                  # extra issued zones to offer
_MAX_ZONE_LINES = 5                  # nearby official zone lines for context

# Front-sampling geometry: rings around the reference point (km).
_SAMPLE_RINGS_KM = [12.0, 25.0, 40.0]

# PFZ calculation cache (expensive ring sampling) — short TTL, env-overridable
_PFZ_TTL_S = int(os.getenv("ORCA_PFZ_TTL_S", "120").strip() or 120)
_pfz_cache: dict[tuple, tuple[float, "PFZRecommendation"]] = {}

# Compass bearings -> plain words, so notes read naturally.
_BEARS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _bearing_word(deg: float) -> str:
    return _BEARS[int((deg % 360) / 45) % 8]


def _nearest_landmark(lat: float, lon: float) -> str | None:
    """Best-effort reverse-geocode to a town-level landmark (cached, keyless).

    Returns None on failure/miss — never raises, never fabricates.
    """
    try:
        return reverse_geocode(lat, lon)
    except GeocodeUnavailableError:
        return None
    except Exception:
        return None


def _line_bbox(feature: dict) -> tuple[float, float, float, float]:
    """[(lon,lat), ...] -> (min_lon, min_lat, max_lon, max_lat)."""
    coords = feature.get("geometry", {}).get("coordinates") or []
    lons = [c[0] for c in coords if c and c[0] is not None]
    lats = [c[1] for c in coords if c and c[1] is not None]
    if not lons or not lats:
        return (0, 0, 0, 0)
    return (min(lons), min(lats), max(lons), max(lats))


def _bbox_distance_km(lat: float, lon: float, bbox) -> float:
    """Distance from point to a (min_lon, min_lat, max_lon, max_lat) box."""
    min_lon, min_lat, max_lon, max_lat = bbox
    clat = max(min_lat, min(lat, max_lat))
    clon = max(min_lon, min(lon, max_lon))
    return PFZAgent._haversine_bearing(lat, lon, clat, clon)[0]


class PFZAgent:
    name = "PFZAgent"

    def run(
        self,
        location: Location,
        ocean_state: OceanStateReading | None = None,
        time_window: str = "today",
    ) -> tuple[PFZRecommendation, AgentTrace]:
        start = time.perf_counter()

        # Check PFZ cache (same location + time_window within TTL)
        cache_key = (location.name, round(location.lat, 3), round(location.lon, 3), time_window)
        hit = _pfz_cache.get(cache_key)
        if hit is not None and time.monotonic() - hit[0] < _PFZ_TTL_S:
            pfz = hit[1]
            trace = AgentTrace(
                agent_name=self.name,
                action=f"Located nearest potential fishing zone for {location.name}",
                result_summary=f"CACHED ({_PFZ_TTL_S//60} min TTL): {pfz.distance_from_reference_km:.1f} km {_bearing_word(pfz.bearing_deg)} of {location.name}",
                data_sources=[pfz.source],
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            pfz.reasoning_note = self._generate_reasoning_note(pfz)
            return pfz, trace

        degraded_reason: str | None = None
        pfz: PFZRecommendation | None = None
        derived_live = False
        if not os.getenv("ORCA_DISABLE_INCOIS_PFZ"):
            try:
                pfz = self._fetch_incois_live(location, ocean_state)
            except (IncoisUnavailableError, ValueError) as exc:
                degraded_reason = f"{type(exc).__name__}: {exc}"
        if pfz is None:
            degraded_reason = degraded_reason or (
                "INCOIS advisory disabled (ORCA_DISABLE_INCOIS_PFZ)"
            )
            pfz, derived_live = self._derive_zone(location, ocean_state)

        pfz.reasoning_note = self._generate_reasoning_note(pfz)

        duration_ms = (time.perf_counter() - start) * 1000
        if pfz.source == DataSource.INCOIS_LIVE:
            lc = pfz.landing_center or {}
            summary = (
                f"OFFICIAL INCOIS PFZ via {lc.get('name', 'landing centre')}: "
                f"{pfz.distance_from_reference_km:.1f} km "
                f"{_bearing_word(pfz.bearing_deg)} of {location.name}"
            )
        else:
            kind = "derived from live SST field" if derived_live else "simulated"
            summary = (
                f"{kind.capitalize()} zone [{kind}, reason: {degraded_reason or 'fallback'}]: "
                f"{pfz.distance_from_reference_km:.1f} km "
                f"{_bearing_word(pfz.bearing_deg)} of {location.name}"
            )
        trace = AgentTrace(
            agent_name=self.name,
            action=f"Located nearest potential fishing zone for {location.name}",
            result_summary=summary,
            data_sources=[pfz.source],
            duration_ms=duration_ms,
        )
        # Cache only live-derived zones (simulated fallback already tagged)
        if pfz.source != DataSource.SIMULATED:
            _pfz_cache[cache_key] = (time.monotonic(), pfz)
        return pfz, trace

    # ------------------------------------------------------------------
    # LIVE INCOIS path (primary; Tier 1/2 -- official advisory)
    # ------------------------------------------------------------------
    def _fetch_incois_live(
        self,
        location: Location,
        ocean_state: OceanStateReading | None,
    ) -> PFZRecommendation:
        """Official advisory for the nearest landing centre with a zone today.

        Geometry is parsed from the INCOIS PLatitude/PLongitude fields -- NO
        LLM, no fabrication. Raises IncoisUnavailableError (feeds unreachable)
        or ValueError (no usable advisory near this point) -> caller falls
        back to the derived path.
        """
        live = get_live_pfz_sync()
        mobile = live.get("landing_centres") or {}
        features = mobile.get("features") or []
        if not features:
            raise IncoisUnavailableError("empty pfzMobile feature set")

        centres = [f["properties"] for f in features]
        index = LandingCentreIndex(centres)
        candidates = index.nearest_k(
            location.lat, location.lon, k=_MAX_CENTRE_CANDIDATES
        )

        issued = [c for c in candidates if c.get("pfz_issued")]
        if not issued:
            near = candidates[0] if candidates else None
            raise ValueError(
                "no officially issued PFZ advisory within {} km of {}"
                .format((near or {}).get("distance_km", "?"), location.name)
            )
        primary = issued[0]
        if float(primary.get("distance_km", 0)) > _MAX_CENTRE_DIST_KM:
            # Nearest issued advisory is on the far side of the country --
            # do not mislead the user; derive locally instead.
            raise ValueError(
                f"nearest issued centre {primary.get('LANDINGNAM')} is "
                f"{primary['distance_km']} km away (>{_MAX_CENTRE_DIST_KM} km cap)"
            )

        zone_lat, zone_lon = primary["pfz_lat"], primary["pfz_lon"]
        distance_km, bearing_deg = self._haversine_bearing(
            location.lat, location.lon, zone_lat, zone_lon
        )

        # Prefer the nearest spot on the OFFICIAL digitized PFZ geometry
        # (pfzLines) as the target: distance/bearing/target-coordinates all
        # come from a haversine against the real zone lines. Fall back to the
        # advisory's zone position when no line is nearby.
        #
        # BUG FIX (region-jump guard): _nearest_point_on_lines() scans the
        # ENTIRE nationwide pfz_lines feature set with no distance cap and no
        # state/region filter -- unlike the landing-centre selection above,
        # which is already bounded by _MAX_CENTRE_DIST_KM. Without this check,
        # a stray/corrupt line entry anywhere in India could silently replace
        # a correct, nearby Mumbai/Maharashtra advisory position with a point
        # hundreds of km away (e.g. Andhra Pradesh) while still reporting a
        # small, misleading distance -- because that distance never went
        # through the cap. Apply the same cap here before accepting it.
        nearest = self._nearest_point_on_lines(
            location.lat, location.lon,
            (live.get("pfz_lines") or {}).get("features") or [],
        )
        import logging as _logging
        _pfzlog = _logging.getLogger("orca.pfz")
        if nearest is not None and nearest["distance_km"] <= _MAX_CENTRE_DIST_KM:
            zone_lat, zone_lon = nearest["lat"], nearest["lon"]
            distance_km, bearing_deg = nearest["distance_km"], nearest["bearing_deg"]
            _pfzlog.info(
                "Resolved location: %s | Advisory region: %s | Selected PFZ: line geometry "
                "%.1f km %s of reference",
                location.name, primary.get("STATENAME", "?"), distance_km, _bearing_word(bearing_deg),
            )
        else:
            if nearest is not None:
                _pfzlog.warning(
                    "Discarding line-geometry PFZ point %.1f km from %s (exceeds %.0f km cap; "
                    "nearest issued centre %s is only %.1f km away) -- keeping advisory zone "
                    "position from that centre instead.",
                    nearest["distance_km"], location.name, _MAX_CENTRE_DIST_KM,
                    primary.get("LANDINGNAM"), primary.get("distance_km", 0),
                )
            # nearest advisory zone position (still official, from pfzMobile) --
            # already implicitly bounded because `primary` passed the
            # _MAX_CENTRE_DIST_KM check above.
            distance_km, bearing_deg = self._haversine_bearing(
                location.lat, location.lon, zone_lat, zone_lon
            )
            _pfzlog.info(
                "Resolved location: %s | Advisory region: %s | Selected PFZ: advisory position "
                "via %s, %.1f km %s of reference",
                location.name, primary.get("STATENAME", "?"), primary.get("LANDINGNAM"),
                distance_km, _bearing_word(bearing_deg),
            )

        # sst/chl are not carried in the PFZ feed; reuse the ocean-state
        # reading when available (still honestly tagged from whence it came).
        # Never fabricate 0.0 — None means unavailable.
        sst = None
        chl = None
        if ocean_state is not None:
            sst = ocean_state.sst_celsius if ocean_state.sst_celsius is not None else None
            chl = ocean_state.chlorophyll_mg_m3 if ocean_state.chlorophyll_mg_m3 is not None else None
        sst_source = (
            ocean_state.field_sources.get("sst_celsius")
            if ocean_state and ocean_state.field_sources.get("sst_celsius") not in (None, "")
            and ocean_state.sst_celsius is not None else "unavailable"
        )
        chl_source = (
            ocean_state.field_sources.get("chlorophyll_mg_m3")
            if ocean_state and ocean_state.field_sources.get("chlorophyll_mg_m3") not in (None, "")
            and ocean_state.chlorophyll_mg_m3 is not None else "unavailable"
        )
        # If ocean_state is None or fields are None, source must be unavailable, not simulated
        if sst is None:
            sst_source = "unavailable"
        if chl is None:
            chl_source = "unavailable"

        # Reverse-geocode primary zone to nearest landmark (town-level, zoom=14)
        primary_landmark = _nearest_landmark(float(zone_lat), float(zone_lon))

        # Alternate issued zones (next nearest centres) so users can compare.
        alternates: list[dict] = []
        for c in issued[1:1 + _MAX_ALTERNATES]:
            d, b = self._haversine_bearing(
                location.lat, location.lon, c["pfz_lat"], c["pfz_lon"]
            )
            # Best-effort landmark for each alternate
            try:
                alt_landmark = _nearest_landmark(float(c["pfz_lat"]), float(c["pfz_lon"]))
            except Exception:
                alt_landmark = None
            alternates.append({
                "center_lat": c["pfz_lat"],
                "center_lon": c["pfz_lon"],
                "distance_km": round(d, 1),
                "bearing_deg": round(b, 1),
                "landing_center": c.get("LANDINGNAM"),
                "state": c.get("STATENAME"),
                "direction": c.get("Direction"),
                "advisory_distance_km": c.get("Distance"),
                "advisory_depth_m": c.get("Depth"),
                "nearest_landmark": alt_landmark,
            })

        # Candidate official zone lines within sight of the point (context
        # for the synthesis/response agents -- full geometry stays in
        # /api/pfz/live for the map).
        zone_lines: list[dict] = []
        pfz_lines = (live.get("pfz_lines") or {}).get("features") or []
        ranked_lines = []
        for f in pfz_lines:
            d = _bbox_distance_km(zone_lat, zone_lon, _line_bbox(f))
            props = f.get("properties") or {}
            ranked_lines.append((d, {
                "uid": props.get("UID"),
                "length": props.get("Length"),
                "distance_km": round(d, 1),
            }))
        ranked_lines.sort(key=lambda t: t[0])
        zone_lines = [entry for _d, entry in ranked_lines[:_MAX_ZONE_LINES]]

        advisory = live.get("advisory") or {}
        # Best-effort sector narrative (small extra fetch; cached 10 min).
        sector_text = None
        secid = str(primary.get("SECTOR_ID", ""))
        try:
            adv2 = get_live_pfz_sync(sector_ids=[secid]) if secid else advisory
            sector_text = (
                (adv2.get("advisory") or advisory)
                .get("sectors", {}).get(secid, {}).get("text")
            )
        except IncoisUnavailableError:
            sector_text = None

        return PFZRecommendation(
            reference_location=location,
            center_lat=round(float(zone_lat), 4),
            center_lon=round(float(zone_lon), 4),
            distance_from_reference_km=round(distance_km, 1),
            bearing_deg=round(bearing_deg, 1),
            sst_at_zone_celsius=round(float(sst), 2) if sst is not None else None,
            chlorophyll_at_zone_mg_m3=round(float(chl), 3) if chl is not None else None,
            nearest_landmark=primary_landmark,
            source=DataSource.INCOIS_LIVE,
            confidence=0.9,
            field_sources={
                "zone_position": DataSource.INCOIS_LIVE.value,
                "sst_at_zone_celsius": sst_source,
                "chlorophyll_at_zone_mg_m3": chl_source,
                "direction": DataSource.INCOIS_LIVE.value,
                "distance": DataSource.INCOIS_LIVE.value,
                "depth": DataSource.INCOIS_LIVE.value,
            },
            alternates=alternates,
            landing_center={
                "name": primary.get("LANDINGNAM"),
                "state": primary.get("STATENAME"),
                "sector_id": secid,
                "sector_name": (
                    advisory.get("sectors", {}).get(secid, {}).get("name")
                ),
                "centre_lat": primary["lat"],
                "centre_lon": primary["lon"],
                "distance_km_to_centre": primary["distance_km"],
                "direction": primary.get("Direction"),
                "angle_deg": primary.get("Angle"),
                "advisory_distance_km": primary.get("Distance"),
                "advisory_depth_m": primary.get("Depth"),
                "pfz_lat": round(float(zone_lat), 4),
                "pfz_lon": round(float(zone_lon), 4),
                "forecast_date": advisory.get("forecast_date"),
                "valid_upto": advisory.get("valid_upto"),
            },
            zone_lines=zone_lines,
            advisory_text=sector_text,
        )

    # ------------------------------------------------------------------
    # DERIVED zone -- strongest live SST front around the reference point
    # (the standard PFZ proxy: fish aggregate along thermal gradients).
    # Samples a ring grid via ONE batched Open-Meteo marine request; only
    # if that live sampling fails does the deterministic seeded fallback
    # run (still honestly tagged SIMULATED).
    # ------------------------------------------------------------------
    def _derive_zone(
        self,
        location: Location,
        ocean_state: OceanStateReading | None,
    ) -> tuple[PFZRecommendation, bool]:
        try:
            samples = self._sample_sst_ring(location)
            derived_live = True
        except Exception as exc:
            import logging

            logging.getLogger("orca.pfz").warning(
                "live SST front sampling failed (%s); seeded fallback used", exc
            )
            return self._seeded_fallback_zone(location, ocean_state), False

        # Find centre sample by coordinate match, not position 0 (as_completed order is random).
        centre = next((s for s in samples if abs(s["lat"] - location.lat) < 1e-6 and abs(s["lon"] - location.lon) < 1e-6), None)
        if centre is None:
            centre = samples[0]
        center_sst = centre["sst"]
        ring = [s for s in samples if s is not centre]
        ranked = sorted(ring, key=lambda s: abs(s["sst"] - center_sst), reverse=True)
        if not ranked:
            return self._seeded_fallback_zone(location, ocean_state), False
        best = ranked[0]

        # Region scan (P1 #12): rank secondary zones by thermal gradient,
        # keeping candidates >= 20 km apart so they're genuinely different
        # areas a fisherman could choose between.
        alternates: list[dict] = []
        MIN_SEP_KM = 20.0
        for cand in ranked:
            if len(alternates) >= 3:
                break
            far_enough = all(
                self._haversine_bearing(cand["lat"], cand["lon"],
                                        a["center_lat"], a["center_lon"])[0] >= MIN_SEP_KM
                and self._haversine_bearing(location.lat, location.lon,
                                            cand["lat"], cand["lon"])[0]
                > self._haversine_bearing(location.lat, location.lon,
                                          a["center_lat"], a["center_lon"])[0] * 0.5
                for a in alternates
            )
            if not far_enough:
                continue
            d, b = self._haversine_bearing(location.lat, location.lon,
                                           cand["lat"], cand["lon"])
            # Best-effort landmark for each derived alternate
            try:
                alt_landmark = _nearest_landmark(round(float(cand["lat"]), 4), round(float(cand["lon"]), 4))
            except Exception:
                alt_landmark = None
            alternates.append({
                "center_lat": round(cand["lat"], 4),
                "center_lon": round(cand["lon"], 4),
                "distance_km": round(d, 1),
                "bearing_deg": round(b, 1),
                "sst_celsius": round(cand["sst"], 2),
                "gradient_vs_reference_c": round(abs(cand["sst"] - center_sst), 2),
                "nearest_landmark": alt_landmark,
            })

        dist, bear = self._haversine_bearing(
            location.lat, location.lon, best["lat"], best["lon"]
        )
        chl = (
            ocean_state.chlorophyll_mg_m3
            if ocean_state is not None else None
        )
        # Honest source: unavailable when field is None
        if ocean_state is not None and ocean_state.chlorophyll_mg_m3 is not None:
            chl_source = ocean_state.field_sources.get("chlorophyll_mg_m3", "unavailable")
        elif ocean_state is not None:
            chl = None
            chl_source = "unavailable"
        else:
            chl_source = DataSource.SIMULATED.value

        # Reverse-geocode primary derived zone
        derived_landmark = _nearest_landmark(round(float(best["lat"]), 4), round(float(best["lon"]), 4))

        return PFZRecommendation(
            reference_location=location,
            center_lat=round(best["lat"], 4),
            center_lon=round(best["lon"], 4),
            distance_from_reference_km=round(dist, 1),
            bearing_deg=round(bear, 1),
            sst_at_zone_celsius=round(best["sst"], 2),
            chlorophyll_at_zone_mg_m3=chl if chl is not None else None,
            nearest_landmark=derived_landmark,
            source=DataSource.DERIVED_LIVE,
            confidence=0.65,
            field_sources={
                "zone_position": DataSource.DERIVED_LIVE.value,
                "sst_at_zone_celsius": DataSource.LIVE.value,
                "chlorophyll_at_zone_mg_m3": chl_source,
            },
            alternates=alternates,
        ), derived_live

    def _sample_sst_ring(self, location: Location) -> list[dict]:
        """Live INCOIS SST at centre + ring points via WMS GetFeatureInfo."""
        from datetime import datetime, timezone
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import data_connectors.incois_marine as im
        lats, lons = [location.lat], [location.lon]
        for r in _SAMPLE_RINGS_KM:
            for bearing in range(0, 360, 45):
                rad = math.radians(bearing)
                dlat = (r / 111.0) * math.cos(rad)
                dlon = (r / (111.0 * max(math.cos(math.radians(location.lat)), 0.2))) * math.sin(rad)
                lats.append(location.lat + dlat)
                lons.append(location.lon + dlon)
        ft = datetime.now(timezone.utc)
        out: list[dict] = []
        def fetch_one(i):
            try:
                snap = im.get_marine_snapshot(lats[i], lons[i], ft)
                sst = snap.get("sst")
                if sst is not None:
                    return {"lat": lats[i], "lon": lons[i], "sst": float(sst)}
            except Exception:
                pass
            return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(fetch_one, i): i for i in range(len(lats))}
            for f in as_completed(futs):
                r = f.result()
                if r:
                    out.append(r)
        # Ensure centre present
        if not any(abs(o["lat"]-lats[0])<1e-6 and abs(o["lon"]-lons[0])<1e-6 for o in out):
            raise ValueError("no live INCOIS SST at reference point")
        if len(out) < len(lats) * 0.5:
            raise ValueError(f"only {len(out)-1}/{len(lats)-1} INCOIS SST samples had data")
        return out

    def _seeded_fallback_zone(
        self,
        location: Location,
        ocean_state: OceanStateReading | None,
    ) -> PFZRecommendation:
        seed = int(hashlib.sha256(
            f"pfz|{location.name}".encode()
        ).hexdigest(), 16)
        frac = lambda off, lo, hi: round(lo + ((seed >> off) % 10_000 / 10_000) * (hi - lo), 3)

        # Never fabricate a number — respect None fields
        if ocean_state is not None and ocean_state.sst_celsius is not None:
            sst = ocean_state.sst_celsius
            sst_fs = ocean_state.field_sources.get("sst_celsius") if ocean_state.field_sources else None
            sst_source_fs = sst_fs if sst_fs not in (None, "") else "unavailable"
        elif ocean_state is not None:
            sst = None
            sst_source_fs = "unavailable"
        else:
            sst = frac(4, 26.5, 29.5)
            sst_source_fs = DataSource.SIMULATED.value
        if ocean_state is not None and ocean_state.chlorophyll_mg_m3 is not None:
            chl = ocean_state.chlorophyll_mg_m3
            chl_fs = ocean_state.field_sources.get("chlorophyll_mg_m3") if ocean_state.field_sources else None
            chl_source_fs = chl_fs if chl_fs not in (None, "") else "unavailable"
        elif ocean_state is not None:
            chl = None
            chl_source_fs = "unavailable"
        else:
            chl = frac(12, 0.6, 2.2)
            chl_source_fs = DataSource.SIMULATED.value

        dist = float(frac(20, 6.0, 38.0))
        # Bias fallback bearing offshore: west coast (lon < 78) -> west (240-300°), east coast -> east (60-120°)
        # Surat/Mumbai/Kochi are west coast, so keep zone seaward, not inland.
        raw_bear = float(frac(28, 0.0, 359.9))
        if location.lon < 78.0:
            # West coast: force to western quadrant (W/SW/NW) — map 0-360 -> 240-300
            bear = 240.0 + (raw_bear % 60.0)
        elif location.lon > 82.0:
            # East coast: east quadrant (60-120)
            bear = 60.0 + (raw_bear % 60.0)
        else:
            bear = raw_bear
        rad = math.radians(bear)
        dlat = (dist / 111.0) * math.cos(rad)
        dlon = (dist / (111.0 * max(math.cos(math.radians(location.lat)), 0.2))) * math.sin(rad)
        # Reverse-geocode seeded zone (best-effort)
        try:
            seeded_landmark = _nearest_landmark(round(location.lat + dlat, 4), round(location.lon + dlon, 4))
        except Exception:
            seeded_landmark = None

        return PFZRecommendation(
            reference_location=location,
            center_lat=round(location.lat + dlat, 4),
            center_lon=round(location.lon + dlon, 4),
            distance_from_reference_km=dist,
            bearing_deg=bear,
            sst_at_zone_celsius=round(float(sst), 2) if sst is not None else None,
            chlorophyll_at_zone_mg_m3=round(float(chl), 3) if chl is not None else None,
            nearest_landmark=seeded_landmark,
            source=DataSource.SIMULATED,
            confidence=0.5,
            field_sources={
                "zone_position": DataSource.SIMULATED.value,
                "sst_at_zone_celsius": sst_source_fs,
                "chlorophyll_at_zone_mg_m3": chl_source_fs,
            },
        )

    @staticmethod
    def _haversine_bearing(lat1, lon1, lat2, lon2) -> tuple[float, float]:
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = p2 - p1
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        dist = 2 * r * math.asin(math.sqrt(a))
        y = math.sin(dl) * math.cos(p2)
        x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
        return dist, (math.degrees(math.atan2(y, x)) + 360) % 360

    @staticmethod
    def _point_on_segment(lat1: float, lon1: float, lat2: float, lon2: float,
                          plat: float, plon: float) -> tuple[float, float, float, float]:
        """Closest point on segment (a->b) to p, in equirectangular projection.

        Returns (nlat, nlon, distance_km, bearing_deg) where the distance is
        the haversine great-circle distance from p to the projected point.
        """
        cos_lat = max(math.cos(math.radians((lat1 + lat2) / 2.0)), 0.2)
        dx = (lon2 - lon1) * cos_lat
        dy = lat2 - lat1
        px = (plon - lon1) * cos_lat
        py = plat - lat1
        seg2 = dx * dx + dy * dy
        if seg2 == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, (px * dx + py * dy) / seg2))
        nlat = lat1 + (lat2 - lat1) * t
        nlon = lon1 + (lon2 - lon1) * t
        d, b = PFZAgent._haversine_bearing(plat, plon, nlat, nlon)
        return nlat, nlon, d, b

    @staticmethod
    def _nearest_point_on_lines(lat: float, lon: float, features: list) -> dict | None:
        """Nearest point on the official digitized PFZ LineStrings to (lat, lon).

        Scans every segment of every INCOIS zone line and returns the closest
        spot with a haversine distance + compass bearing -- i.e. the nearest
        actual PFZ point in the official geometry. None when no usable line
        exists near the point (caller keeps the advisory zone position).
        """
        best: tuple[float, float, float, float] | None = None
        for f in features or []:
            geom = (f.get("geometry") or {})
            lines: list[list] = []
            if geom.get("type") == "LineString":
                lines = [geom.get("coordinates") or []]
            elif geom.get("type") == "MultiLineString":
                lines = geom.get("coordinates") or []
            for line in lines:
                for a, b in zip(line, line[1:]):
                    if not a or not b or len(a) < 2 or len(b) < 2:
                        continue
                    try:
                        nlat, nlon, d, br = PFZAgent._point_on_segment(
                            float(a[1]), float(a[0]), float(b[1]), float(b[0]),
                            float(lat), float(lon),
                        )
                    except (TypeError, ValueError):
                        continue
                    if best is None or d < best[0]:
                        best = (d, nlat, nlon, br)
        if best is None:
            return None
        d, nlat, nlon, br = best
        return {
            "distance_km": round(d, 1),
            "bearing_deg": round(br, 1),
            "lat": round(nlat, 4),
            "lon": round(nlon, 4),
        }

    # ------------------------------------------------------------------
    # Deterministic note by default — no LLM needed for distance/bearing facts.
    # ------------------------------------------------------------------
    def _generate_reasoning_note(self, pfz: PFZRecommendation) -> str:
        sst_txt = f"{pfz.sst_at_zone_celsius} °C" if pfz.sst_at_zone_celsius is not None else "N/A"
        chl_txt = f"{pfz.chlorophyll_at_zone_mg_m3} mg/m³" if pfz.chlorophyll_at_zone_mg_m3 is not None else "N/A"
        deterministic = (
            f"Zone {pfz.distance_from_reference_km} km away at "
            f"{pfz.bearing_deg:.1f}° bearing; "
            f"SST {sst_txt}, chlorophyll "
            f"{chl_txt}."
        )
        if pfz.source == DataSource.INCOIS_LIVE:
            lc = pfz.landing_center or {}
            deterministic += (
                f" Official INCOIS advisory via {lc.get('name') or 'landing centre'}, "
                f"valid to {lc.get('valid_upto')}."
            )
        elif pfz.source == DataSource.DERIVED_LIVE:
            deterministic += " Estimated zone — official INCOIS advisory unavailable for this spot today."
        else:
            deterministic += " Seeded estimate — live feeds were unreachable."
        if not _ENABLE_LLM_NOTE:
            return deterministic
        sources = ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in sorted(pfz.field_sources.items()))
        lc = pfz.landing_center or {}
        system_prompt = (
            "You are the PFZ Agent in a marine multi-agent system. You just "
            "located the nearest potential fishing zone and are writing a short "
            "note to the Synthesis Agent as if talking to a colleague. Rules: "
            "use ONLY the values provided; do NOT invent numbers; do NOT give "
            "the final verdict; 2-3 sentences."
        )
        if pfz.source == DataSource.INCOIS_LIVE:
            system_prompt += (
                " The zone comes from the OFFICIAL daily INCOIS advisory for the "
                "nearest landing centre -- state that clearly (it is Tier 1/2 "
                "data, not a private estimate)."
            )
        else:
            system_prompt += (
                " The zone is an alternative estimate because the daily official "
                "advisory was not available for this exact spot -- say so honestly, "
                "but keep the tone factual; the values themselves are from real "
                "forecast data."
            )
        lc_line = (
            f"\nOfficial landing centre: {lc.get('name')} ({lc.get('state')}, "
            f"sector {lc.get('sector_id')}); advisory says zone is "
            f"{lc.get('advisory_distance_km')} km to the {lc.get('direction')} "
            f"at {lc.get('advisory_depth_m')} m depth, valid to "
            f"{lc.get('valid_upto')}." if lc else ""
        )
        user_prompt = (
            f"Reference point: {pfz.reference_location.name}\n"
            f"- Zone centre: ({pfz.center_lat}, {pfz.center_lon})\n"
            f"- Distance: {pfz.distance_from_reference_km} km, "
            f"bearing {pfz.bearing_deg} deg\n"
            f"- SST at zone: {pfz.sst_at_zone_celsius} C, chlorophyll: "
            f"{pfz.chlorophyll_at_zone_mg_m3} mg/m3\n"
            f"Provenance: {sources}{lc_line}\n\n"
            "Write your note."
        )
        try:
            return llm_client.complete(system_prompt, user_prompt, temperature=0.4, max_tokens=250,
                                       timeout=7, attempts=1)
        except llm_client.LLMUnavailableError:
            kind = pfz.source.value
            zone_txt = (
                f"Official INCOIS PFZ ({kind}) via landing centre "
                f"{lc.get('name')}: {pfz.distance_from_reference_km} km away; "
                if lc else
                f"{kind.capitalize()} zone {pfz.distance_from_reference_km} km away; "
            )
            return (
                f"[llm_unavailable] {zone_txt}"
                f"SST {pfz.sst_at_zone_celsius} C, chlorophyll "
                f"{pfz.chlorophyll_at_zone_mg_m3} mg/m3."
            )
