"""
Ocean-State Agent — INCOIS-only marine intelligence.

Replaces every Open-Meteo dependency with official INCOIS THREDDS WMS:
  SST_NIO_{YYYYMMDD}.nc (SST), rsmc_combined_ww3_{YYYYMMDD}.nc (UWND:VWND-mag,
  UWND:VWND-group, PHS01), CURRENTS_NIO_{YYYYMMDD}.nc (CURRENT),
  and erddap.incois.gov.in OceanSat-2 CHL.

Single data source: data_connectors.incois_marine.get_marine_snapshot(...)
Fetched concurrently, cached 10 min. No city hardcoding.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import os as _os

import data_connectors.tide as tide
import data_connectors.incois_marine as incois_marine
from models import (
    AgentTrace,
    DataSource,
    ExceedanceWindow,
    Location,
    OceanStateReading,
    TideExtreme,
)

WAVE_UNSAFE_M = 2.5
GUST_UNSAFE_KMH = 45.0
_SERIES_HOURS_AHEAD = 48

_READING_TTL_S = int(_os.getenv("ORCA_OCEAN_TTL_S", "120").strip() or 120)
_reading_cache: dict[tuple, tuple[float, "OceanStateReading"]] = {}
_ENABLE_LLM_NOTE = _os.getenv("ORCA_ENABLE_LLM_REASONING", "").strip().lower() in ("1", "true", "yes")

logger = logging.getLogger("orca.ocean_state")


class OceanStateAgent:
    name = "OceanStateAgent"

    def run(self, location: Location, time_window: str,
            target_hour: int | None = None,
            thresholds: dict | None = None) -> tuple[OceanStateReading, AgentTrace]:
        start = time.perf_counter()
        self._active_thresholds = thresholds or {
            "wave_height_unsafe_m": WAVE_UNSAFE_M,
            "wind_gust_unsafe_kmh": GUST_UNSAFE_KMH,
        }
        cache_key = (location.name, round(location.lat, 3),
                     round(location.lon, 3), time_window, target_hour)
        hit = _reading_cache.get(cache_key)
        if hit is not None and time.monotonic() - hit[0] < _READING_TTL_S:
            reading = hit[1]
            trace = AgentTrace(
                agent_name=self.name,
                action=f"Retrieved INCOIS marine state for {location.name} ({time_window})",
                result_summary=f"CACHED ({_READING_TTL_S // 60} min TTL): SST {reading.sst_celsius}°C, wave {reading.wave_height_m}m — served instantly",
                data_sources=[reading.source],
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return reading, trace

        degraded_reason: str | None = None
        try:
            reading = self._fetch_live_incois(location, time_window, target_hour)
        except Exception as exc:
            degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("INCOIS marine unavailable (%s); trying cache fallback for %s", degraded_reason, location.name)
            # Cache fallback only — never a silent provider switch or simulation
            if hit is not None:
                reading = hit[1]
                logger.info("Using recently retrieved INCOIS data (cached)")
            else:
                reading = None
                logger.warning("Official INCOIS data is temporarily unavailable for %s (%s)", location.name, degraded_reason)

        if reading is None:
            # Honest degraded result: report unavailability instead of fabricating values
            reading = self._unavailable_reading(location, degraded_reason or "INCOIS unavailable")
            reading.reasoning_note = self._generate_reasoning_note(reading, time_window)
            duration_ms = (time.perf_counter() - start) * 1000
            return reading, AgentTrace(
                agent_name=self.name,
                action=f"Tried INCOIS marine state for {location.name} ({time_window})",
                result_summary=f"Official INCOIS data is temporarily unavailable ({degraded_reason}).",
                data_sources=["unavailable"],
                duration_ms=duration_ms,
            )

        reading.reasoning_note = self._generate_reasoning_note(reading, time_window)
        duration_ms = (time.perf_counter() - start) * 1000
        if degraded_reason and hit is not None:
            result_summary = f"INCOIS temporarily unavailable ({degraded_reason}) — Using recently retrieved INCOIS data."
        else:
            sources = reading.field_sources or {}
            live_fields = sorted(k.replace("_mg_m3","").replace("_m","") for k,v in sources.items() if v in ("live", "tide_gauge_model"))
            result_summary = f"INCOIS live for {location.name} ({time_window}): live fields {', '.join(live_fields) or 'none'}"
            chl_note = getattr(reading, "chlorophyll_latency_note", None)
            if chl_note and sources.get("chlorophyll_mg_m3") == "live":
                result_summary += f" | chlorophyll: {chl_note}"
            _reading_cache[cache_key] = (time.monotonic(), reading)

        trace = AgentTrace(
            agent_name=self.name,
            action=f"Retrieved INCOIS marine state for {location.name} ({time_window})",
            result_summary=result_summary,
            data_sources=[reading.source],
            duration_ms=duration_ms,
        )
        return reading, trace

    def _unavailable_reading(self, location: Location, reason: str) -> OceanStateReading:
        """Honest placeholder — every field is UNAVAILABLE (None) so no
        fabricated number ever reaches the response. Callers render each field
        individually as 'Live INCOIS value unavailable.'"""
        field_sources = {
            "sst_celsius": "unavailable",
            "wave_height_m": "unavailable",
            "wind_speed_kmh": "unavailable",
            "wind_gust_kmh": "unavailable",
            "chlorophyll_mg_m3": "unavailable",
            "tide_level_m": "unavailable",
            "surface_current_mps": "unavailable",
            "primary_swell_height_m": "unavailable",
        }
        reading = OceanStateReading(
            location=location,
            timestamp=datetime.now(timezone.utc),
            sst_celsius=None, chlorophyll_mg_m3=None, wave_height_m=None,
            wind_speed_kmh=None, wind_gust_kmh=None, tide_level_m=None,
            source=DataSource.SIMULATED, confidence=0.0,
            field_sources=field_sources,
        )
        reading.primary_swell_height_m = None
        reading.surface_current_mps = None
        reading.wind_direction = None
        reading.unavailable_reason = reason
        reading.debug_incois = {}
        return reading

    def _fetch_live_incois(self, location: Location, time_window: str, target_hour: int | None = None) -> OceanStateReading:
        # Resolve forecast_time from time_window
        now_utc = datetime.now(timezone.utc)
        forecast_time = now_utc
        if time_window.startswith("tomorrow"):
            forecast_time = now_utc + timedelta(days=1)
            if target_hour is not None:
                forecast_time = forecast_time.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        elif target_hour is not None:
            forecast_time = forecast_time.replace(hour=target_hour, minute=0, second=0, microsecond=0)

        logger.info("SST fetch for %.4f,%.4f", location.lat, location.lon)
        logger.info("Wind fetch for %.4f,%.4f", location.lat, location.lon)

        # Coordinates are used exactly as given (map-tap / GPS / geocoded point).
        # Official INCOIS only — no provider switching, no simulated chlorophyll.
        snapshot = incois_marine.get_marine_snapshot(location.lat, location.lon, forecast_time)
        logger.info("Current fetch for %.4f,%.4f = %s", location.lat, location.lon, snapshot.get("surface_current"))
        logger.info("Swell fetch for %.4f,%.4f = %s", location.lat, location.lon, snapshot.get("primary_swell_height"))
        logger.info("Chlorophyll fetch for %.4f,%.4f = %s", location.lat, location.lon, snapshot.get("chlorophyll"))
        # Cache hit/miss already logged in incois_marine

        # Extract fields — each is None when its INCOIS layer could not serve it.
        # Field-by-field: never fail the whole reading for a single layer outage.
        sst = snapshot.get("sst")
        wind_speed = snapshot.get("wind_speed")
        wind_dir = snapshot.get("wind_direction")
        wind_dir_deg = snapshot.get("wind_direction_deg")
        current = snapshot.get("surface_current")
        swell = snapshot.get("primary_swell_height")
        # Chlorophyll: MOSDAC (ISRO OCM) primary → INCOIS ERDDAP secondary → unavailable
        # Never simulated; per-field provenance is "live" only on genuine success.
        chl = None
        chl_source_detail = "unavailable"
        chl_latency_note = None
        # Try MOSDAC first if key is configured
        try:
            import os

            if os.getenv("MOSDAC_API_KEY", "").strip():
                from data_connectors.isro_sources import MosdacConnector

                mosdac = MosdacConnector()
                try:
                    mos_res = mosdac.fetch(location)
                    v = mos_res.get("chlorophyll")
                    if v is not None and 0.0 <= float(v) <= 50.0:
                        chl = round(float(v), 3)
                        chl_source_detail = "live"
                        chl_latency_note = mos_res.get("latency_note")
                        logger.info("MOSDAC chlorophyll live for %.4f,%.4f = %.3f mg/m³", location.lat, location.lon, chl)
                    else:
                        logger.warning("MOSDAC chlorophyll out of range %s for %.4f,%.4f", v, location.lat, location.lon)
                except Exception as e:
                    # MOSDAC failed — fall back to INCOIS ERDDAP (free, currently empty but harmless)
                    logger.warning("MOSDAC chlorophyll failed for %s (%.4f,%.4f): %s — falling back to INCOIS ERDDAP", location.name, location.lat, location.lon, e)
        except Exception:
            pass
        # Fallback to INCOIS ERDDAP if MOSDAC did not yield a value
        if chl is None:
            v2 = snapshot.get("chlorophyll")
            if v2 is not None and 0.0 <= float(v2) <= 50.0:
                chl = round(float(v2), 3)
                chl_source_detail = "live"
                logger.info("INCOIS ERDDAP chlorophyll live for %.4f,%.4f = %.3f mg/m³", location.lat, location.lon, chl)
            else:
                chl_source_detail = "unavailable"
                if v2 is not None:
                    logger.warning("INCOIS chlorophyll out of range %s for %.4f,%.4f", v2, location.lat, location.lon)

        # Primary Swell Height (PHS01) is the meaningful marine wave field.
        wave = swell if swell is not None else None
        # INCOIS WW3 does not provide gust — do NOT fabricate a derived gust.

        # Tide via the independent harmonic model. Keep it when available;
        # never fabricate a tide value on failure.
        utc_offset = 19800  # IST +5:30
        tide_extremes = []
        try:
            tide_val, tide_src, tide_extremes = self._get_tide(location, utc_offset, time_window, target_hour)
        except Exception as e:
            logger.warning("tide fetch failed: %s", e)
            tide_val, tide_src = None, "unavailable"

        # Field sources: INCOIS live where available, otherwise unavailable.
        # No simulated fallback, no derived gust. Chlorophyll provenance is
        # "live" only on genuine MOSDAC or INCOIS success, per honest-data rule.
        field_sources = {
            "sst_celsius": "live" if sst is not None else "unavailable",
            "wave_height_m": "live" if swell is not None else "unavailable",
            "wind_speed_kmh": "live" if wind_speed is not None else "unavailable",
            "wind_gust_kmh": "unavailable",
            "chlorophyll_mg_m3": chl_source_detail,
            "tide_level_m": tide_src,
            "surface_current_mps": "live" if current is not None else "unavailable",
            "primary_swell_height_m": "live" if swell is not None else "unavailable",
        }

        # Chlorophyll: MOSDAC primary → INCOIS fallback — never simulated.
        chl_val = round(float(chl), 3) if chl is not None else None
        has_live = any(v == "live" for v in field_sources.values())

        reading = OceanStateReading(
            location=location,
            timestamp=datetime.now(timezone.utc),
            sst_celsius=round(float(sst), 2) if sst is not None else None,
            chlorophyll_mg_m3=chl_val,
            wave_height_m=round(float(wave), 2) if wave is not None else None,
            wind_speed_kmh=round(float(wind_speed), 2) if wind_speed is not None else None,
            wind_gust_kmh=None,
            tide_level_m=round(float(tide_val), 2) if tide_val is not None else None,
            source=DataSource.LIVE if has_live else DataSource.SIMULATED,
            confidence=0.9 if has_live else 0.0,
            field_sources=field_sources,
            exceedance_windows=[],
            tide_extremes=tide_extremes,
            hourly_series={
                "times": [forecast_time.strftime("%Y-%m-%dT%H:%M:%SZ")],
                "wave_height_m": [round(float(wave), 2)] if wave is not None else [],
                "wind_gust_kmh": [],
            } if has_live else {},
        )
        reading.surface_current_mps = round(float(current), 3) if current is not None else None
        reading.primary_swell_height_m = round(float(swell), 2) if swell is not None else None
        reading.wind_direction = wind_dir
        reading.wind_direction_deg = wind_dir_deg
        reading.marine_location_note = (
            "Marine conditions are reported for your requested location."
        )
        reading.debug_incois = snapshot.get("debug") or {}
        reading.unavailable_reason = None if has_live else "Live INCOIS value unavailable"
        if chl_latency_note:
            reading.chlorophyll_latency_note = chl_latency_note
        return reading

    def _get_tide(self, location: Location, utc_offset_seconds: int, time_window: str, target_hour: int | None = None):
        target_local = self._target_local_time(utc_offset_seconds, time_window, target_hour)
        target_utc = (target_local - timedelta(seconds=utc_offset_seconds)).replace(tzinfo=timezone.utc)
        import data_connectors.tide as tide
        result = tide.predict_level_m(location.lat, location.lon, target_utc)
        try:
            hl = tide.predict_highs_lows(location.lat, location.lon, when_utc=target_utc, utc_offset_seconds=utc_offset_seconds)
            extremes = [TideExtreme(kind=e["kind"], time_local=e["time_local"], height_m=e["height_m"]) for e in hl.get("extremes", [])]
        except Exception:
            extremes = []
        return round(result["level_m"],2), DataSource.TIDE_GAUGE_MODEL.value, extremes

    def _target_local_time(self, utc_offset_seconds: int, time_window: str, target_hour: int | None = None) -> datetime:
        local_now = datetime.now(timezone.utc) + timedelta(seconds=utc_offset_seconds)
        day = local_now.date()
        if time_window.startswith("tomorrow"):
            day += timedelta(days=1)
        if target_hour is not None:
            hour = max(0, min(23, int(target_hour)))
        else:
            hour = 9 if time_window == "tomorrow_morning" else (12 if time_window == "tomorrow" else local_now.hour)
        return datetime(day.year, day.month, day.day, hour)

    def _generate_reasoning_note(self, reading: OceanStateReading, time_window: str) -> str:
        sources = reading.field_sources or {}
        _fmt = lambda x: "unavailable" if x is None else f"{x}"
        sst_txt = _fmt(reading.sst_celsius) + " °C"
        wave = reading.wave_height_m
        thr_wave = getattr(self, "_active_thresholds", {}).get("wave_height_unsafe_m", WAVE_UNSAFE_M)
        if wave is None:
            wave_note = "Wave height unavailable."
        elif wave > thr_wave:
            wave_note = f"Wave height {wave} m exceeds {thr_wave} m limit."
        else:
            wave_note = f"Wave height {wave} m within safe (<{thr_wave} m)."
        gust = reading.wind_gust_kmh
        if gust is None:
            gust_note = "Wind gust unavailable (INCOIS does not publish gust)."
        else:
            gust_note = f"Wind gusts {gust} km/h."
        tide_txt = _fmt(reading.tide_level_m) + " m"
        deterministic = f"Reading for {reading.location.name}, {time_window}: SST {sst_txt}, {wave_note} {gust_note} Tide {tide_txt}."
        if not _ENABLE_LLM_NOTE:
            return deterministic
        import llm_client
        try:
            return llm_client.complete("You are Ocean-State Agent...", deterministic, temperature=0.4, max_tokens=250, timeout=7, attempts=1)
        except Exception:
            return deterministic
