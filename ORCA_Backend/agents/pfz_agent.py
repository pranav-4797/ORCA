"""
PFZ Agent ("Finds where the fish likely are")

Responsibility: locate the nearest Potential Fishing Zone for the user's
reference point, with distance, bearing and the SST/chlorophyll evidence
that justifies it.

Data source (per project documentation Section 9):
    Tier 1 -- Bhuvan Ocean Tool WMS GetFeatureInfo (ISRO/NRSC PFZ layer).
    The live call is implemented against Bhuvan's documented OGC request
    pattern but DISABLED BY DEFAULT: endpoint paths require account/endpoint
    verification (first probe returned 404). Flip USE_LIVE_BHUVAN_PFZ once
    verified.

    Until then the zone is DERIVED FROM LIVE DATA: a ring of sample points
    around the user is queried against Open-Meteo's live marine grid in ONE
    batched request, and the strongest sea-surface-temperature front (the
    classic PFZ proxy -- fish aggregate along thermal gradients) wins.
    The result is tagged DataSource.DERIVED_LIVE ("derived_from_live_data")
    -- real satellite-model SST driving a real computation, but still NOT an
    official INCOIS/Bhuvan advisory. Only if even that live sampling fails
    does the deterministic seeded fallback run, tagged DataSource.SIMULATED.
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
from models import (
    AgentTrace,
    DataSource,
    Location,
    OceanStateReading,
    PFZRecommendation,
)
_ENABLE_LLM_NOTE = os.getenv("ORCA_ENABLE_LLM_REASONING", "").strip().lower() in ("1", "true", "yes")

USE_LIVE_BHUVAN_PFZ = False  # enable after verifying Bhuvan WMS endpoint/auth

_BHUVAN_WMS_URL = (
    "https://bhuvan-app1.nrsc.gov.in/cgi-bin/ocean/handler_ocn_WMS.cgi"
)
_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
_HTTP_TIMEOUT_S = 10.0

# Front-sampling geometry: rings around the reference point (km).
_SAMPLE_RINGS_KM = [12.0, 25.0, 40.0]

# PFZ calculation cache (expensive ring sampling) — short TTL, env-overridable
_PFZ_TTL_S = int(os.getenv("ORCA_PFZ_TTL_S", "120").strip() or 120)
_pfz_cache: dict[tuple, tuple[float, "PFZRecommendation"]] = {}

# Compass bearings -> plain words, so notes read naturally.
_BEARS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _bearing_word(deg: float) -> str:
    return _BEARS[int((deg % 360) / 45) % 8]


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
        if USE_LIVE_BHUVAN_PFZ:
            try:
                pfz = self._fetch_bhuvan_live(location)
            except Exception as exc:
                degraded_reason = f"{type(exc).__name__}: {exc}"
                pfz, derived_live = self._derive_zone(location, ocean_state)
        else:
            degraded_reason = "Bhuvan official PFZ layer not yet verified"
            pfz, derived_live = self._derive_zone(location, ocean_state)

        pfz.reasoning_note = self._generate_reasoning_note(pfz)

        duration_ms = (time.perf_counter() - start) * 1000
        if degraded_reason:
            kind = "derived from live SST field" if derived_live else "simulated"
            summary = (
                f"{kind.capitalize()} zone [{kind}, reason: {degraded_reason}]: "
                f"{pfz.distance_from_reference_km:.1f} km {_bearing_word(pfz.bearing_deg)} "
                f"of {location.name}"
            )
        else:
            summary = (
                f"LIVE Bhuvan PFZ: {pfz.distance_from_reference_km:.1f} km "
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
    # LIVE path (disabled until endpoint verification)
    # ------------------------------------------------------------------
    def _fetch_bhuvan_live(self, location: Location) -> PFZRecommendation:
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetFeatureInfo",
            "LAYERS": "pfz",  # TODO: confirm exact layer id on verified endpoint
            "QUERY_LAYERS": "pfz",
            "SRS": "EPSG:4326",
            "BBOX": f"{location.lon - 0.5},{location.lat - 0.5},"
                    f"{location.lon + 0.5},{location.lat + 0.5}",
            "WIDTH": "256",
            "HEIGHT": "256",
            "X": "128",
            "Y": "128",
            "INFO_FORMAT": "application/json",
        }
        url = f"{_BHUVAN_WMS_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "orca-backend/0.1"})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        props = (payload.get("features") or [{}])[0].get("properties", {})
        lat = float(props["lat"])
        lon = float(props["lon"])
        dist, bear = self._haversine_bearing(location.lat, location.lon, lat, lon)
        return PFZRecommendation(
            reference_location=location,
            center_lat=lat,
            center_lon=lon,
            distance_from_reference_km=round(dist, 1),
            bearing_deg=round(bear, 1),
            sst_at_zone_celsius=float(props.get("sst", 0.0)),
            chlorophyll_at_zone_mg_m3=float(props.get("chlorophyll", 0.0)),
            source=DataSource.BHUVAN_LIVE,
            confidence=0.9,
            field_sources={
                "center_lat": DataSource.BHUVAN_LIVE.value,
                "center_lon": DataSource.BHUVAN_LIVE.value,
                "sst_at_zone_celsius": DataSource.BHUVAN_LIVE.value,
                "chlorophyll_at_zone_mg_m3": DataSource.BHUVAN_LIVE.value,
            },
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

        center_sst = samples[0]["sst"]
        # Strongest gradient point = max |SST difference| vs the centre.
        ranked = sorted(samples[1:], key=lambda s: abs(s["sst"] - center_sst),
                        reverse=True)
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
            alternates.append({
                "center_lat": round(cand["lat"], 4),
                "center_lon": round(cand["lon"], 4),
                "distance_km": round(d, 1),
                "bearing_deg": round(b, 1),
                "sst_celsius": round(cand["sst"], 2),
                "gradient_vs_reference_c": round(abs(cand["sst"] - center_sst), 2),
            })

        dist, bear = self._haversine_bearing(
            location.lat, location.lon, best["lat"], best["lon"]
        )
        chl = (
            ocean_state.chlorophyll_mg_m3
            if ocean_state is not None else None
        )
        chl_source = (
            (ocean_state.field_sources.get("chlorophyll_mg_m3")
             if ocean_state else None) or DataSource.SIMULATED.value
        )

        return PFZRecommendation(
            reference_location=location,
            center_lat=round(best["lat"], 4),
            center_lon=round(best["lon"], 4),
            distance_from_reference_km=round(dist, 1),
            bearing_deg=round(bear, 1),
            sst_at_zone_celsius=round(best["sst"], 2),
            chlorophyll_at_zone_mg_m3=chl if chl is not None else 0.0,
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
        """Live SST at the centre + ring points, one batched API call."""
        lats, lons = [location.lat], [location.lon]
        for r in _SAMPLE_RINGS_KM:
            for bearing in range(0, 360, 45):
                rad = math.radians(bearing)
                dlat = (r / 111.0) * math.cos(rad)
                dlon = (r / (111.0 * max(math.cos(math.radians(location.lat)), 0.2))) * math.sin(rad)
                lats.append(location.lat + dlat)
                lons.append(location.lon + dlon)

        params = urllib.parse.urlencode({
            "latitude": ",".join(f"{v:.4f}" for v in lats),
            "longitude": ",".join(f"{v:.4f}" for v in lons),
            "hourly": "sea_surface_temperature",
            "forecast_days": 1,
            "timezone": "auto",
        })
        url = f"{_MARINE_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "orca-backend/0.1"})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        results = payload if isinstance(payload, list) else [payload]
        if len(results) != len(lats):
            raise ValueError(f"expected {len(lats)} sample points, got {len(results)}")

        out: list[dict] = []
        for i, res in enumerate(results):
            series = res["hourly"]["sea_surface_temperature"]
            idx = min(range(len(series)),
                      key=lambda k: (series[k] is None, k))
            if series[idx] is None:
                continue  # land/coastal cell -- skip, don't kill the sampling
            out.append({"lat": lats[i], "lon": lons[i], "sst": float(series[idx])})
        # Centre (index 0) must be valid as the gradient baseline, and we
        # need a usable ring around it.
        if not out or out[0]["lat"] != lats[0]:
            raise ValueError("no live SST at reference point")
        if len(out) < len(lats) * 0.6:
            raise ValueError(
                f"only {len(out) - 1}/{len(lats) - 1} ring samples had live SST"
            )
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

        sst = ocean_state.sst_celsius if ocean_state is not None else frac(4, 26.5, 29.5)
        chl = ocean_state.chlorophyll_mg_m3 if ocean_state is not None else frac(12, 0.6, 2.2)

        dist = float(frac(20, 6.0, 38.0))
        bear = float(frac(28, 0.0, 359.9))
        rad = math.radians(bear)
        dlat = (dist / 111.0) * math.cos(rad)
        dlon = (dist / (111.0 * max(math.cos(math.radians(location.lat)), 0.2))) * math.sin(rad)

        return PFZRecommendation(
            reference_location=location,
            center_lat=round(location.lat + dlat, 4),
            center_lon=round(location.lon + dlon, 4),
            distance_from_reference_km=dist,
            bearing_deg=bear,
            sst_at_zone_celsius=sst,
            chlorophyll_at_zone_mg_m3=chl,
            source=DataSource.SIMULATED,
            confidence=0.5,
            field_sources={
                "zone_position": DataSource.SIMULATED.value,
                "sst_at_zone_celsius":
                    (ocean_state.field_sources.get("sst_celsius")
                     if ocean_state else DataSource.SIMULATED.value),
                "chlorophyll_at_zone_mg_m3":
                    (ocean_state.field_sources.get("chlorophyll_mg_m3")
                     if ocean_state else DataSource.SIMULATED.value),
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

    # ------------------------------------------------------------------
    # Deterministic note by default — no LLM needed for distance/bearing facts.
    # ------------------------------------------------------------------
    def _generate_reasoning_note(self, pfz: PFZRecommendation) -> str:
        kind = "derived from live SST field" \
            if pfz.source == DataSource.DERIVED_LIVE else "simulated"
        deterministic = (
            f"{kind.capitalize()} zone {pfz.distance_from_reference_km} km away at "
            f"{pfz.bearing_deg:.1f}° bearing; "
            f"SST {pfz.sst_at_zone_celsius} °C, chlorophyll "
            f"{pfz.chlorophyll_at_zone_mg_m3} mg/m³."
            + (" Derived from live satellite-model SST thermal front, not an official INCOIS/Bhuvan advisory." if pfz.source == DataSource.DERIVED_LIVE else "")
        )
        if not _ENABLE_LLM_NOTE:
            return deterministic
        sources = ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in sorted(pfz.field_sources.items()))
        system_prompt = (
            "You are the PFZ Agent in a marine multi-agent system. You just located "
            "the nearest potential fishing zone and are writing a short note to the "
            "Synthesis Agent as if talking to a colleague. Rules: use ONLY the "
            "values provided; do NOT invent numbers; do NOT give the final verdict; "
            "2-3 sentences; explicitly mention that the zone position is derived "
            "from live satellite-model SST data (a thermal-front heuristic) rather "
            "than an official INCOIS/Bhuvan advisory."
        )
        user_prompt = (
            f"Reference point: {pfz.reference_location.name}\n"
            f"- Zone centre: ({pfz.center_lat}, {pfz.center_lon})\n"
            f"- Distance: {pfz.distance_from_reference_km} km, "
            f"bearing {pfz.bearing_deg} deg\n"
            f"- SST at zone: {pfz.sst_at_zone_celsius} C, chlorophyll: "
            f"{pfz.chlorophyll_at_zone_mg_m3} mg/m3\n"
            f"Provenance: {sources}\n\n"
            "Write your note."
        )
        try:
            return llm_client.complete(system_prompt, user_prompt, temperature=0.4, max_tokens=250,
                                       timeout=7, attempts=1)
        except llm_client.LLMUnavailableError:
            return deterministic
