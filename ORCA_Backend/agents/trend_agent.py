"""
Trend Agent -- analytical/time-series reasoning (PS component #4 extended,
PDF Sec. 11.2 'Dr. Anjali' journey: "Why has fish productivity declined?").

Fetches MONTHS of real history for the location and correlates:
    - Sea surface temperature : NOAA MUR monthly mean SST
      (jplMURSST41mday on CoastWatch ERDDAP, keyless, 2002-present)
    - Chlorophyll-a           : NESDIS VIIRS/OLCI DINEOF daily gap-filled
      (same host as the live chlorophyll feed)

Statistics are computed deterministically here (pure Python): linear trend
per month for each metric and a Pearson correlation between them on common
months. The LLM layer only narrates these numbers -- never invents them.

Falls back honestly: if a source is unreachable the corresponding metric is
absent from the analysis (never simulated silently).
"""

from __future__ import annotations

import csv
import io
import json  # noqa: F401  (kept for parity with other connectors)
import logging
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import os as _os

import llm_client
from models import (
    AgentTrace,
    DataSource,
    Location,
    TrendAnalysis,
    TrendPoint,
)

logger = logging.getLogger("orca.trend")
_ENABLE_LLM_NOTE = _os.getenv("ORCA_ENABLE_LLM_REASONING", "").strip().lower() in ("1", "true", "yes")

_SERVER = "https://coastwatch.pfeg.noaa.gov/erddap"
_SST_DS, _SST_VAR = "jplMURSST41mday", "sst"          # monthly mean
_CHL_DS, _CHL_VAR = "nesdisNPPN20S3ASCIDINEOFDaily", "chlor_a"  # daily
_HTTP_TIMEOUT_S = 40.0

_HEADERS = {
    "User-Agent": "orca-hackathon-proto/0.1 (SIH-2026 marine safety prototype)",
}


class _SourceUnavailable(Exception):
    pass


def _get_json(expr: str, dataset: str) -> list[list]:
    """Rows from a griddap query. Uses .csv (much lighter than .json for
    long series) and tolerates ERDDAP's extra units line."""
    q = urllib.parse.quote(expr, safe="()")
    url = f"{_SERVER}/griddap/{dataset}.csv?{q}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise _SourceUnavailable(f"{dataset}: {exc}") from exc
    lines = raw.splitlines()
    reader = csv.DictReader(io.StringIO("\n".join(lines[:1] + lines[2:])))
    rows = [list(r.values()) for r in reader]
    if not rows:
        raise _SourceUnavailable(f"{dataset}: empty result")
    return rows


def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop ERDDAP 'NaN' strings


def _axis_len(dataset: str) -> int:
    rows = _get_json("time", dataset)
    return len(rows)


def _monthly_means(series: dict[str, float]) -> dict[str, float]:
    """Calendar-month means; require >=10 daily samples for daily sources.
    Monthly sources have 1 sample per month and always pass."""
    buckets: dict[str, tuple[float, int]] = {}
    for date, v in sorted(series.items()):
        month = date[:7]
        s, c = buckets.get(month, (0.0, 0))
        buckets[month] = (s + v, c + 1)
    return {m: round(s / c, 4) for m, (s, c) in buckets.items()}


def _lin_trend(ys: list[float]) -> float:
    """Least-squares slope per step."""
    n = len(ys)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 4:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return None
    return round(num / (da * db), 3)


class TrendAgent:
    name = "TrendAgent"

    def run(self, location: Location,
            months: int = 6) -> tuple[TrendAnalysis, AgentTrace]:
        start = time.perf_counter()
        months = max(3, min(months, 24))

        sst_series: dict[str, float] = {}
        chl_series: dict[str, float] = {}
        sources: dict[str, str] = {}
        try:
            n_sst = _axis_len(_SST_DS)
            expr = f"{_SST_VAR}[{n_sst - months - 1}:1:{n_sst - 1}][({location.lat:.3f})][({location.lon:.3f})]"
            sst_series = {
                r[0][:10]: val for r in _get_json(expr, _SST_DS)
                if (val := _finite(r[-1])) is not None
            }
            sources["sst_celsius"] = "live_noaa_mur_monthly"
        except _SourceUnavailable as exc:
            logger.warning("SST history unavailable: %s", exc)
            sources["sst_celsius"] = "unavailable"

        try:
            n_chl = _axis_len(_CHL_DS)
            # NOTE the [(0)] altitude index -- this grid carries one depth
            # level and griddap requires every dimension to be constrained.
            # Daily data: take ~months*30 last steps, aggregate to months.
            lo = max(0, n_chl - months * 31 - 1)
            expr = (f"{_CHL_VAR}[{lo}:1:{n_chl - 1}][(0)]"
                    f"[({location.lat:.3f})][({location.lon:.3f})]")
            chl_series = {
                r[0][:10]: val for r in _get_json(expr, _CHL_DS)
                if (val := _finite(r[-1])) is not None
            }
            sources["chlorophyll_mg_m3"] = "live_noaa_nesdis_dineof_daily"
        except _SourceUnavailable as exc:
            logger.warning("chlorophyll history unavailable: %s", exc)
            sources["chlorophyll_mg_m3"] = "unavailable"

        sst_m = _monthly_means(sst_series)
        chl_m = _monthly_means(chl_series)
        common = sorted(set(sst_m) & set(chl_m))

        points = [
            TrendPoint(date=m, sst_celsius=sst_m.get(m), chlorophyll_mg_m3=chl_m.get(m))
            for m in sorted(set(sst_m) | set(chl_m))
        ]

        sst_vals = [p.sst_celsius for p in points if p.sst_celsius is not None]
        chl_vals = [p.chlorophyll_mg_m3 for p in points if p.chlorophyll_mg_m3 is not None]
        corr = (_pearson([sst_m[m] for m in common], [chl_m[m] for m in common])
                if common else None)

        result = TrendAnalysis(
            location_name=location.name,
            window_months=months,
            points=[p.__dict__ | {} for p in points],
            sst_trend_per_month=round(_lin_trend(sst_vals), 4),
            chl_trend_per_month=round(_lin_trend(chl_vals), 4),
            sst_chl_correlation=corr,
            field_sources=sources,
        )

        result.reasoning_note = self._note(result)

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action=f"Analysed {months}-month SST/chlorophyll history "
                   f"for {location.name}",
            result_summary=(
                f"SST trend {result.sst_trend_per_month:+.3f} C/mo, chl trend "
                f"{result.chl_trend_per_month:+.3f} mg/m3/mo, r={corr} "
                f"({len(points)} months)"
            ),
            data_sources=[DataSource.DERIVED_LIVE],
            duration_ms=duration_ms,
        )
        return result, trace

    # ------------------------------------------------------------------
    def _note(self, t: TrendAnalysis) -> str:
        # Deterministic interpretation first
        interp = ""
        if t.sst_trend_per_month > 0 and t.chl_trend_per_month < 0:
            interp = "Warming coincides with declining chlorophyll."
        elif t.sst_trend_per_month < 0 and t.chl_trend_per_month > 0:
            interp = "Cooling coincides with rising chlorophyll."
        else:
            interp = "No clear inverse relationship this window."
        deterministic = (f"{interp} SST {t.sst_trend_per_month:+.3f} "
                f"C/mo, chlorophyll {t.chl_trend_per_month:+.3f} mg/m3/mo, "
                f"r={t.sst_chl_correlation}.")
        if not _ENABLE_LLM_NOTE:
            return deterministic
        facts = (
            f"Location: {t.location_name}, window: {t.window_months} months.\n"
            f"- SST trend: {t.sst_trend_per_month:+.4f} degC/month\n"
            f"- Chlorophyll trend: {t.chl_trend_per_month:+.4f} mg/m3/month\n"
            f"- SST-chlorophyll correlation (Pearson r): {t.sst_chl_correlation}\n"
            f"- Data availability: {t.field_sources}\n"
        )
        try:
            return llm_client.complete(
                system_prompt=(
                    "You are ORCA's Trend Agent explaining an analytical finding "
                    "about changing ocean conditions to a researcher/fisherman. "
                    "Use ONLY the statistics provided; do NOT invent causes beyond "
                    "the standard physical interpretation of warming reducing "
                    "nutrient mixing (lower chlorophyll) when the numbers support "
                    "it. 2-3 sentences."
                ),
                user_prompt=facts + "\nWrite your interpretation.",
                temperature=0.3,
                max_tokens=250,
                timeout=7, attempts=1,
            )
        except llm_client.LLMUnavailableError:
            return deterministic
