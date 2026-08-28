"""
Ocean-State Agent

Responsibility: given a location + time window, retrieve the physical
ocean/weather state -- SST, chlorophyll, wave height, wind, tide.

PRIMARY DATA SOURCE (production, keyless, no registration):
    - Open-Meteo Marine API   -> wave height, sea surface temperature, swell
      https://marine-api.open-meteo.com/v1/marine
    - Open-Meteo Weather API  -> wind speed, wind gusts (requested in km/h)
      https://api.open-meteo.com/v1/forecast
    - UHSLC tide gauges       -> REAL harmonic-fit tide prediction
      (data_connectors/tide.py: least-squares fit of 8 tidal constituents
      on observed hourly sea level from the nearest Indian gauge)
    - NOAA CoastWatch ERDDAP  -> satellite chlorophyll-a
      (data_connectors/chlorophyll.py; host network-blocked from this dev
      machine -- see its FIELD REALITY CHECK -- so it degrades gracefully)

Both Open-Meteo feeds and the tide model return real data. Chlorophyll is
LIVE when its source is reachable; otherwise it falls back to a seeded
value (_simulate_chlorophyll). Every field's actual provenance is recorded
per-run in `field_sources`; nothing simulated is ever presented as live.

ERROR FALLBACK ONLY: if either Open-Meteo call fails or times out, the
whole reading falls back to the deterministic simulator, the failure is
logged with its reason, and the AgentTrace result_summary explicitly says
the response is degraded. This is an error path, not a mode.

Registered Indian-agency feeds (MOSDAC/INCOIS/IMD) are stubbed in
data_connectors/isro_sources.py -- NOT ACTIVATED, they require credentials
and are never called by this agent by default.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import data_connectors.chlorophyll as chlorophyll
import data_connectors.tide as tide
from models import (
    AgentTrace,
    DataSource,
    ExceedanceWindow,
    Location,
    OceanStateReading,
    TideExtreme,
)

USE_LIVE_DATA = True  # Open-Meteo is the production path (keyless)

# Safety thresholds mirrored from the Hazard Agent so exceedance intervals
# are computed against exactly what the verdict uses.
WAVE_UNSAFE_M = 2.5
GUST_UNSAFE_KMH = 45.0

_SERIES_HOURS_AHEAD = 48  # window for exceedance scan + chart series

_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
_HTTP_TIMEOUT_S = 10.0

# Whole-reading TTL cache: identical repeat queries within the TTL are
# served instantly (live forecasts barely move in minutes). The trace
# honestly marks cached responses.
_READING_TTL_S = 15 * 60
_reading_cache: dict[tuple, tuple[float, "OceanStateReading"]] = {}

# Marine dry-cell retries must respect a wall-clock budget so a coastal
# point outside the marine grid can never stall a query for minutes.
_MARINE_BUDGET_S = 30.0

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
                action=f"Retrieved ocean/weather state for {location.name} ({time_window})",
                result_summary=(
                    f"CACHED ({_READING_TTL_S // 60} min TTL): SST "
                    f"{reading.sst_celsius}\u00b0C, wave {reading.wave_height_m}m, "
                    f"gusts {reading.wind_gust_kmh}km/h -- served instantly"
                ),
                data_sources=[reading.source],
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            return reading, trace

        degraded_reason: str | None = None
        if USE_LIVE_DATA:
            try:
                reading = self._fetch_live(location, time_window, target_hour)
            except Exception as exc:
                degraded_reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Open-Meteo unavailable (%s); falling back to simulated data "
                    "for %s [%s]",
                    degraded_reason, location.name, time_window,
                )
                reading = self._fetch_simulated_fallback(location, time_window)
        else:
            degraded_reason = "USE_LIVE_DATA disabled manually"
            reading = self._fetch_simulated_fallback(location, time_window)

        # LLM layer: reason ON TOP of the structured data (never replaces it).
        reading.reasoning_note = self._generate_reasoning_note(reading, time_window)

        duration_ms = (time.perf_counter() - start) * 1000

        if degraded_reason:
            result_summary = (
                f"Open-Meteo unavailable ({degraded_reason}) -- used cached/simulated "
                f"fallback [DEGRADED]. SST {reading.sst_celsius}°C, wave "
                f"{reading.wave_height_m}m, gusts {reading.wind_gust_kmh}km/h"
            )
        else:
            sources = reading.field_sources or {}
            sim_fields = sorted(k.replace("_mg_m3", "").replace("_m", "")
                                for k, v in sources.items() if v == "simulated")
            provenance = (
                f"(simulated fields: {', '.join(sim_fields)})"
                if sim_fields else "(all fields real)"
            )
            result_summary = (
                f"LIVE data for {location.name} @ {reading.timestamp:%Y-%m-%d %H:%M} "
                f"local ({time_window}): SST {reading.sst_celsius}\u00b0C, wave "
                f"{reading.wave_height_m}m, wind {reading.wind_speed_kmh}km/h, "
                f"gusts {reading.wind_gust_kmh}km/h {provenance}"
            )
            _reading_cache[cache_key] = (time.monotonic(), reading)

        trace = AgentTrace(
            agent_name=self.name,
            action=f"Retrieved ocean/weather state for {location.name} ({time_window})",
            result_summary=result_summary,
            data_sources=[reading.source],
            duration_ms=duration_ms,
        )
        return reading, trace

    # ------------------------------------------------------------------
    # LIVE PATH -- Open-Meteo Marine + Weather APIs
    # ------------------------------------------------------------------
    def _fetch_live(self, location: Location, time_window: str,
                    target_hour: int | None = None) -> OceanStateReading:
        # Marine and weather are independent feeds -- fetch concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_marine = pool.submit(self._get_marine, location)
            f_weather = pool.submit(self._get_json, _WEATHER_URL, {
                "latitude": location.lat,
                "longitude": location.lon,
                "hourly": "wind_speed_10m,wind_gusts_10m",
                "wind_speed_unit": "kmh",  # request km/h directly, no conversion needed
                "timezone": "auto",
                "forecast_days": 3,
            })
            marine = f_marine.result()
            weather = f_weather.result()

        utc_offset = marine.get("utc_offset_seconds", 0)
        target_local = self._target_local_time(utc_offset, time_window, target_hour)
        idx_marine = self._hour_index(marine["hourly"]["time"], target_local)
        idx_weather = self._hour_index(weather["hourly"]["time"], target_local)

        sst = self._value_at(marine["hourly"].get("sea_surface_temperature"), idx_marine)
        wave = self._value_at(marine["hourly"].get("wave_height"), idx_marine)
        wind = self._unit_converted(weather["hourly"], "wind_speed_10m", idx_weather)
        gusts = self._unit_converted(weather["hourly"], "wind_gusts_10m", idx_weather)

        # Temporal exceedance reasoning + chart series from the full hourly
        # forecast (P1 #10/#13): WHEN does it get dangerous, not just how much.
        exceedance, hourly_series = self._analyse_temporal(
            marine["hourly"], weather["hourly"], utc_offset
        )

        # Chlorophyll and tide are independent of each other -- fetch them
        # concurrently too (each may hit its own slow external source).
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_chl = pool.submit(self._get_chlorophyll, location)
            f_tide = pool.submit(
                self._get_tide, location, utc_offset, time_window, target_hour
            )
            chl_value, chl_source = f_chl.result()
            tide_value, tide_source, tide_extremes = f_tide.result()

        timestamp = datetime.now(timezone.utc)

        return OceanStateReading(
            location=location,
            timestamp=timestamp,
            sst_celsius=sst,
            chlorophyll_mg_m3=chl_value,
            wave_height_m=wave,
            wind_speed_kmh=round(wind, 2),
            wind_gust_kmh=round(gusts, 2),
            tide_level_m=tide_value,
            source=DataSource.LIVE,
            confidence=0.85,  # live forecast model data; below 1.0 because it's a model, not a buoy
            field_sources={
                "sst_celsius": DataSource.LIVE.value,
                "wave_height_m": DataSource.LIVE.value,
                "wind_speed_kmh": DataSource.LIVE.value,
                "wind_gust_kmh": DataSource.LIVE.value,
                "chlorophyll_mg_m3": chl_source,
                "tide_level_m": tide_source,
            },
            exceedance_windows=exceedance,
            tide_extremes=tide_extremes,
            hourly_series=hourly_series,
        )

    # ------------------------------------------------------------------
    # Temporal analysis: threshold-crossing windows + trimmed series.
    # ------------------------------------------------------------------
    def _analyse_temporal(self, marine_hourly: dict, weather_hourly: dict,
                          utc_offset: int):
        thr = getattr(self, "_active_thresholds", None) or {
            "wave_height_unsafe_m": WAVE_UNSAFE_M,
            "wind_gust_unsafe_kmh": GUST_UNSAFE_KMH,
        }
        # Open-Meteo returns NAIVE local wall-clock strings -- compare against
        # an equally naive local now.
        now_local = (datetime.now(timezone.utc) + timedelta(seconds=utc_offset)
                     ).replace(tzinfo=None)
        horizon = now_local + timedelta(hours=_SERIES_HOURS_AHEAD)

        def _collect(hourly: dict, field: str):
            times, values = [], []
            for t, v in zip(hourly.get("time", []), hourly.get(field, []) or []):
                try:
                    tv = datetime.fromisoformat(t)
                except ValueError:
                    continue
                if now_local <= tv <= horizon and v is not None:
                    times.append(t)
                    values.append(float(v))
            return times, values

        exceedance: list[ExceedanceWindow] = []
        wave_t, wave_v = _collect(marine_hourly, "wave_height")
        gust_t, gust_v = _collect(weather_hourly, "wind_gusts_10m")

        for metric, times, values, thr_v in (
            ("wave_height_m", wave_t, wave_v, thr["wave_height_unsafe_m"]),
            ("wind_gust_kmh", gust_t, gust_v, thr["wind_gust_unsafe_kmh"]),
        ):
            run_start = None
            peak = None
            peak_time = ""
            for tstr, v in zip(times, values):
                over = v > thr_v
                if over and run_start is None:
                    run_start, peak, peak_time = tstr, v, tstr
                elif over and v > (peak or 0):
                    peak, peak_time = v, tstr
                elif not over and run_start is not None:
                    exceedance.append(ExceedanceWindow(
                        metric=metric,
                        threshold=thr_v,
                        start_local=run_start,
                        end_local=tstr,
                        peak_value=round(peak, 2),
                        unit="m" if metric == "wave_height_m" else "km/h",
                    ))
                    run_start = None
            if run_start is not None:  # still over at end of window
                exceedance.append(ExceedanceWindow(
                    metric=metric,
                    threshold=thr_v,
                    start_local=run_start,
                    end_local=times[-1] if times else "",
                    peak_value=round(peak or 0, 2),
                    unit="m" if metric == "wave_height_m" else "km/h",
                ))

        series = {
            "times": wave_t or gust_t,
            "wave_height_m": wave_v,
            "wind_gust_kmh": gust_v,
        }
        return exceedance, series

    # ------------------------------------------------------------------
    # Per-field live fetchers with honest per-field fallbacks.
    # ------------------------------------------------------------------
    def _get_chlorophyll(self, location: Location) -> tuple[float, str]:
        try:
            result = chlorophyll.fetch_chlorophyll(location.lat, location.lon)
            return result["chlorophyll_mg_m3"], DataSource.LIVE.value
        except chlorophyll.ChlUnavailableError as exc:
            logger.info("satellite chlorophyll unavailable (%s); simulated value used", exc)
            sim = self._simulate_chlorophyll(location)
            return sim, DataSource.SIMULATED.value

    def _get_tide(
        self, location: Location, utc_offset_seconds: int, time_window: str,
        target_hour: int | None = None,
    ) -> tuple[float, str, list[TideExtreme]]:
        target_local = self._target_local_time(utc_offset_seconds, time_window, target_hour)
        target_utc = (target_local - timedelta(seconds=utc_offset_seconds)).replace(tzinfo=timezone.utc)
        try:
            result = tide.predict_level_m(location.lat, location.lon, target_utc)
            logger.info(
                "tide %.2f m from %s gauge (%.0f km, fit rms %.2f m)",
                result["level_m"], result["station_name"],
                result["station_distance_km"], result["fit_rms_m"],
            )
            # High/low events + range from the same harmonic fit (P1 #14).
            try:
                hl = tide.predict_highs_lows(
                    location.lat, location.lon,
                    when_utc=target_utc,
                    utc_offset_seconds=utc_offset_seconds,
                )
                extremes = [
                    TideExtreme(kind=e["kind"], time_local=e["time_local"],
                                height_m=e["height_m"])
                    for e in hl.get("extremes", [])
                ]
            except Exception as exc:  # extremes are enrichment, never fatal
                logger.info("tide extremes unavailable (%s)", exc)
                extremes = []
            return round(result["level_m"], 2), DataSource.TIDE_GAUGE_MODEL.value, extremes
        except tide.TideUnavailableError as exc:
            logger.info("tide prediction unavailable (%s); simulated value used", exc)
            sim = self._simulate_tide(location)
            return sim, DataSource.SIMULATED.value, []

    def _get_marine(self, location: Location) -> dict:
        """Marine forecast for the sea point nearest the user.

        Coastal points can fall outside Open-Meteo's marine grid (all-null
        response) when the coordinate is on the beach itself. Retry with a
        small offshore cross of offsets -- still the user's sea, just a
        wet cell of it. Raises ValueError when every offset is dry/null.
        """
        last_error: Exception | None = None
        deadline = time.monotonic() + _MARINE_BUDGET_S
        # Near-shore points often sit outside the marine grid -- walk an
        # increasingly wide cross until a wet cell answers. East-coast
        # places need +lon, west-coast -lon, so both directions are probed.
        for dlat, dlon in [(0.0, 0.0), (0.1, 0.05), (-0.1, -0.05),
                           (0.05, -0.1), (-0.05, 0.1),
                           (0.15, 0.25), (0.15, -0.25),
                           (-0.15, 0.3), (-0.15, -0.3)]:
            if time.monotonic() > deadline:
                break  # budget spent -- fail fast into the degraded path
            # Two attempts per offset: Open-Meteo occasionally returns an
            # all-null body under burst load -- a short pause clears it.
            for attempt in range(2):
                try:
                    payload = self._get_json(_MARINE_URL, {
                        "latitude": location.lat + dlat,
                        "longitude": location.lon + dlon,
                        "hourly": "wave_height,sea_surface_temperature,swell_wave_height",
                        "timezone": "auto",
                        "forecast_days": 3,
                    })
                except ValueError as exc:
                    last_error = exc
                    break
                hourly = payload.get("hourly", {})
                # A coordinate on land still returns HTTP 200 -- but with an
                # all-null hourly series. Treat that as "dry cell".
                if any(hourly.get(k) and any(v is not None for v in hourly[k])
                       for k in ("wave_height", "sea_surface_temperature")):
                    return payload
                last_error = ValueError(f"all-null marine series at offset ({dlat}, {dlon})")
                if attempt == 0 and time.monotonic() < deadline:
                    time.sleep(1.0)
        raise last_error or ValueError("no marine grid data near this point")

    def _get_json(self, base_url: str, params: dict) -> dict:
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "orca-backend/0.1"})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if "error" in payload and payload.get("error"):
            raise ValueError(f"Open-Meteo returned error: {payload.get('reason', payload['error'])}")
        return payload

    def _target_local_time(self, utc_offset_seconds: int, time_window: str,
                           target_hour: int | None = None) -> datetime:
        """Local wall-clock target for the requested window, using the API's tz offset.

        `target_hour` (0-23) overrides the window's default hour so queries
        like 'tomorrow at 10 am' hit the exact hour (P1 #10).
        """
        local_now = datetime.now(timezone.utc) + timedelta(seconds=utc_offset_seconds)
        day = local_now.date()
        if time_window.startswith("tomorrow"):
            day += timedelta(days=1)
        if target_hour is not None:
            hour = max(0, min(23, int(target_hour)))
        else:
            hour = 9 if time_window == "tomorrow_morning" else (
                12 if time_window == "tomorrow" else local_now.hour
            )
        return datetime(day.year, day.month, day.day, hour)

    def _hour_index(self, times: list[str], target: datetime) -> int:
        """Exact-hour match first, else the nearest available hour."""
        want = target.strftime("%Y-%m-%dT%H:00")
        if want in times:
            return times.index(want)
        parsed = [datetime.fromisoformat(t) for t in times]
        return min(range(len(parsed)), key=lambda i: abs(parsed[i] - target))

    def _value_at(self, series: list | None, idx: int) -> float:
        """Nearest non-null value around idx (Open-Meteo uses null for missing hours)."""
        if not series:
            raise ValueError("missing hourly series in Open-Meteo response")
        n = len(series)
        for radius in range(n):
            for i in (idx - radius, idx + radius):
                if 0 <= i < n and series[i] is not None:
                    return float(series[i])
        raise ValueError("all values null in hourly series")

    def _unit_converted(self, hourly: dict, field: str, idx: int) -> float:
        value = self._value_at(hourly.get(field), idx)
        units = hourly.get("units", {}).get(field, "")
        if units in ("m/s", "ms⁻¹"):
            value *= 3.6  # defensive: we requested km/h, but honour the declared unit
        return value

    # ------------------------------------------------------------------
    # Simulated fields -- only for values with NO free keyless source.
    # Deterministic per (field, location), same scheme as before.
    # ------------------------------------------------------------------
    def _simulate_chlorophyll(self, location: Location) -> float:
        seed = int(hashlib.sha256(f"chlorophyll|{location.name}".encode()).hexdigest(), 16)
        fraction = (seed >> 12) % 10_000 / 10_000
        return round(0.1 + fraction * (2.5 - 0.1), 2)

    def _simulate_tide(self, location: Location) -> float:
        seed = int(hashlib.sha256(f"tide|{location.name}".encode()).hexdigest(), 16)
        fraction = (seed >> 44) % 10_000 / 10_000
        return round(0.3 + fraction * (2.1 - 0.3), 2)

    # ------------------------------------------------------------------
    # ERROR FALLBACK ONLY -- deterministic full-reading simulator.
    # Used exclusively when Open-Meteo fails; always marked DEGRADED.
    # ------------------------------------------------------------------
    def _fetch_simulated_fallback(self, location: Location, time_window: str) -> OceanStateReading:
        seed_str = f"{location.name}|{time_window}"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16)

        def pseudo_random(offset: int, lo: float, hi: float) -> float:
            n = (seed >> offset) % 10_000
            fraction = n / 10_000
            return round(lo + fraction * (hi - lo), 2)

        return OceanStateReading(
            location=location,
            timestamp=datetime.now(timezone.utc),
            sst_celsius=pseudo_random(4, 24.0, 31.0),
            chlorophyll_mg_m3=pseudo_random(12, 0.1, 2.5),
            wave_height_m=pseudo_random(20, 0.4, 3.6),
            wind_speed_kmh=pseudo_random(28, 8.0, 42.0),
            wind_gust_kmh=pseudo_random(36, 12.0, 55.0),
            tide_level_m=pseudo_random(44, 0.3, 2.1),
            source=DataSource.SIMULATED,
            confidence=0.55,
            field_sources={
                "sst_celsius": DataSource.SIMULATED.value,
                "wave_height_m": DataSource.SIMULATED.value,
                "wind_speed_kmh": DataSource.SIMULATED.value,
                "wind_gust_kmh": DataSource.SIMULATED.value,
                "chlorophyll_mg_m3": DataSource.SIMULATED.value,
                "tide_level_m": DataSource.SIMULATED.value,
            },
        )

    # ------------------------------------------------------------------
    # LLM layer: a short note "reporting back to a colleague". Grounded
    # strictly in the structured numbers -- the model is told not to invent
    # any values, and told which fields are live vs simulated so it can be
    # equally honest. Falls back to a deterministic template on LLM failure.
    # ------------------------------------------------------------------
    def _generate_reasoning_note(self, reading: OceanStateReading, time_window: str) -> str:
        sources = reading.field_sources or {}
        source_note = (
            "Field provenance: "
            + ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in sorted(sources.items()))
            if sources else
            f"Whole reading tagged: {reading.source.value}"
        )
        system_prompt = (
            "You are the Ocean-State Agent in a marine-safety multi-agent system. "
            "You just retrieved an ocean/weather reading and are writing a short note "
            "to report your findings to a colleague agent (the Hazard Agent), as if "
            "talking to them. Rules: use ONLY the numbers provided; do NOT invent or "
            "estimate any new values; do NOT give the final safety verdict yourself "
            "(that is the Hazard Agent's job); keep it to 2-4 sentences of natural "
            "speech; if some fields are simulated, mention which."
        )
        user_prompt = (
            f"Query time window: {time_window}\n"
            f"Location: {reading.location.name} "
            f"(lat {reading.location.lat}, lon {reading.location.lon})\n"
            f"- Sea surface temperature: {reading.sst_celsius} °C\n"
            f"- Chlorophyll: {reading.chlorophyll_mg_m3} mg/m³\n"
            f"- Wave height: {reading.wave_height_m} m\n"
            f"- Wind speed: {reading.wind_speed_kmh} km/h\n"
            f"- Wind gusts: {reading.wind_gust_kmh} km/h\n"
            f"- Tide level: {reading.tide_level_m} m\n"
            f"{source_note}\n\n"
            "Write your 2-4 sentence note about what stands out in this data."
        )
        try:
            import llm_client
            return llm_client.complete(
                system_prompt, user_prompt, temperature=0.4, max_tokens=600
            )
        except Exception:
            sim_fields = ", ".join(k for k, v in sources.items() if v == "simulated") or "none"
            return (
                f"[llm_unavailable] Reading for {reading.location.name}, {time_window}. "
                f"Live fields fetched from Open-Meteo; simulated fields: {sim_fields}. "
                f"Wave height {reading.wave_height_m} m and gusts "
                f"{reading.wind_gust_kmh} km/h are the values most likely to matter downstream."
            )
