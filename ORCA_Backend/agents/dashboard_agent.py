"""
Smart Dashboard Agent -- decides WHAT to show a fisher before they ask.

Pure ranking and assembly: it fetches nothing and calls no LLM, so it is
deterministic and testable. `/dashboard` (api/dashboard.py) supplies the
already-fetched agent outputs; this module decides which cards are worth
showing, in what order, and computes the fishing-readiness score.

Two hard rules from the spec:

  * A card is OMITTED when its underlying field is unavailable. It is never
    emitted with a placeholder, an estimate, or a zero.
  * Ranking is score-based, not fixed:

        score = 0.35*history + 0.35*location + 0.20*time + 0.10*hazard

    with an explicit override that pins Hazard first when the sea is unsafe --
    a cyclone outranks habit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from agents.hazard_agent import get_thresholds

logger = logging.getLogger("orca.dashboard")

CARD_TYPES = ("pfz", "sst", "wind", "current", "tide", "hazard")

W_HISTORY, W_LOCATION, W_TIME, W_HAZARD = 0.35, 0.35, 0.20, 0.10

_DANGER = ("UNSAFE", "EXTREME", "CRITICAL")

# Which card each hour of the day tends to want. 4-6 AM is the departure
# decision (zone + wind + tide); afternoon is water-reading (SST/current);
# evening is the go/no-go for tomorrow (hazard).
_TIME_PRIORITY: dict[str, tuple[int, ...]] = {
    "pfz":     (4, 5, 6, 7),
    "wind":    (4, 5, 6, 7),
    "tide":    (4, 5, 6, 7),
    "sst":     (12, 13, 14, 15, 16),
    "current": (12, 13, 14, 15, 16),
    "hazard":  (18, 19, 20, 21, 22),
}

# Max points each factor can add to the readiness score. Sums to 100 when
# every input is live; factors with no live data are dropped and the rest are
# re-normalised, so the score never leans on a value INCOIS did not send.
_READINESS_WEIGHTS = {
    "pfz": 30.0,
    "wind": 25.0,
    "swell": 25.0,
    "hazard": 15.0,
    "tide": 5.0,
}


# --------------------------------------------------------------------------
# live-data guards
# --------------------------------------------------------------------------

def _live(obj: Any, field: str) -> bool:
    """True only when the field has a value AND was not tagged unavailable.

    Mirrors the frontend's buildHudMetrics contract exactly so the dashboard
    and the metric ribbon can never disagree about what is real.
    """
    if obj is None:
        return False
    value = getattr(obj, field, None)
    if value is None:
        return False
    sources = getattr(obj, "field_sources", None) or {}
    return str(sources.get(field, "")) != "unavailable"


def _first_live(obj: Any, *fields: str) -> tuple[Optional[str], Any]:
    for field in fields:
        if _live(obj, field):
            return field, getattr(obj, field)
    return None, None


def _compass(deg: Optional[float]) -> str:
    if deg is None:
        return ""
    points = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    return points[int((float(deg) % 360) / 22.5 + 0.5) % 16]


def _status_of(risk: Any) -> str:
    status = getattr(risk, "status", None)
    return str(getattr(status, "value", status) or "").upper()


def _has_cap(risk: Any) -> bool:
    return bool(getattr(risk, "cap_polygons", None))


def _is_dangerous(risk: Any) -> bool:
    return _status_of(risk) in _DANGER or _has_cap(risk)


# --------------------------------------------------------------------------
# per-card scoring components
# --------------------------------------------------------------------------

def _history_component(card: str, memory: Any) -> float:
    """Normalised evidence that this fisher cares about this card."""
    if memory is None:
        return 0.0
    try:
        scores = {c: float(memory.card_score(c)) for c in CARD_TYPES}
    except AttributeError:
        raw = dict(getattr(memory, "scores", None) or {})
        scores = {c: float(raw.get(f"card:{c}", 0.0)) for c in CARD_TYPES}
    peak = max(scores.values() or [0.0])
    if peak <= 0.0:
        return 0.0
    return max(0.0, min(1.0, scores.get(card, 0.0) / peak))


def _time_component(card: str, hour: int) -> float:
    hours = _TIME_PRIORITY.get(card, ())
    if not hours:
        return 0.3
    if hour in hours:
        return 1.0
    # Adjacent hour still counts for something -- 3 AM is nearly 4 AM.
    if any(abs(hour - h) == 1 for h in hours):
        return 0.6
    return 0.2


def _location_component(card: str, ocean: Any, pfz: Any) -> float:
    """How relevant this card is to the resolved point, given live data."""
    if card == "pfz":
        if pfz is None:
            return 0.0
        distance = getattr(pfz, "distance_from_reference_km", None)
        if distance is None:
            return 0.0
        confidence = float(getattr(pfz, "confidence", 1.0) or 1.0)
        # Any zone within a normal day's run is fully relevant; relevance only
        # tapers beyond that, reaching zero at 120 km where a small boat
        # realistically cannot go and return. Confidence scales it so a
        # derived zone ranks below an official advisory at the same distance.
        distance = float(distance)
        proximity = 1.0 if distance <= 30.0 else max(0.0, 1.0 - (distance - 30.0) / 90.0)
        return max(0.0, min(1.0, proximity * confidence))
    if card == "hazard":
        return 1.0            # a verdict always applies to the point
    field_map = {
        "sst": ("sst_celsius",),
        "wind": ("wind_gust_kmh", "wind_speed_kmh"),
        "current": ("surface_current_mps",),
        "tide": ("tide_level_m",),
    }
    for field in field_map.get(card, ()):
        if _live(ocean, field):
            return 1.0
    if card == "tide" and getattr(ocean, "tide_extremes", None):
        return 1.0
    return 0.0


def _hazard_component(card: str, risk: Any) -> float:
    if not _is_dangerous(risk):
        return 0.2 if card == "hazard" else 0.0
    if card == "hazard":
        return 1.0
    # In dangerous weather, wind and swell context matter more than SST.
    return 0.6 if card in ("wind", "tide") else 0.1


# --------------------------------------------------------------------------
# card builders -- each returns None when its data is not live
# --------------------------------------------------------------------------

def _card_pfz(ocean: Any, pfz: Any) -> Optional[dict]:
    if pfz is None:
        return None
    distance = getattr(pfz, "distance_from_reference_km", None)
    bearing = getattr(pfz, "bearing_deg", None)
    if distance is None or bearing is None:
        return None
    landing = getattr(pfz, "landing_center", None) or {}
    why = [{"key": "nearest_official_pfz",
            "value": f"{float(distance):.1f} km @ {float(bearing):.0f}° "
                     f"({_compass(bearing)})"}]
    zone_sst = getattr(pfz, "sst_at_zone_celsius", None)
    if zone_sst is not None:
        why.append({"key": "zone_sst", "value": f"{zone_sst} °C"})
    if getattr(pfz, "nearest_landmark", None):
        why.append({"key": "nearest_landmark", "value": pfz.nearest_landmark})
    if landing.get("name"):
        why.append({"key": "landing_centre", "value": str(landing["name"])})
    alternates = getattr(pfz, "alternates", None) or []
    if alternates:
        why.append({"key": "alternates_scanned", "value": str(len(alternates))})
    return {
        "type": "pfz",
        "value": round(float(distance), 1),
        "unit": "km",
        "bearing_deg": round(float(bearing), 1),
        "bearing_compass": _compass(bearing),
        "center": [getattr(pfz, "center_lat", None), getattr(pfz, "center_lon", None)],
        "landmark": getattr(pfz, "nearest_landmark", None),
        "source": str(getattr(getattr(pfz, "source", None), "value",
                              getattr(pfz, "source", "")) or ""),
        "action": "focus_pfz",
        "why": why,
    }


def _card_sst(ocean: Any) -> Optional[dict]:
    if not _live(ocean, "sst_celsius"):
        return None
    return {
        "type": "sst",
        "value": round(float(ocean.sst_celsius), 2),
        "unit": "°C",
        "action": "overlay:sst",
        "why": [{"key": "sst_point", "value": f"{ocean.sst_celsius} °C"}],
    }


def _card_wind(ocean: Any) -> Optional[dict]:
    field, value = _first_live(ocean, "wind_gust_kmh", "wind_speed_kmh")
    if field is None:
        return None
    why = [{"key": "gust" if field == "wind_gust_kmh" else "wind_speed",
            "value": f"{value} km/h"}]
    direction = getattr(ocean, "wind_direction", None)
    deg = getattr(ocean, "wind_direction_deg", None)
    if direction or deg is not None:
        label = direction or _compass(deg)
        why.append({"key": "wind_direction",
                    "value": f"{label}{f' ({deg:.0f}°)' if deg is not None else ''}"})
    return {
        "type": "wind",
        "value": round(float(value), 2),
        "unit": "km/h",
        "direction": direction or _compass(deg),
        "direction_deg": deg,
        "action": "overlay:wind",
        "why": why,
    }


def _card_current(ocean: Any) -> Optional[dict]:
    if not _live(ocean, "surface_current_mps"):
        return None
    return {
        "type": "current",
        "value": round(float(ocean.surface_current_mps), 3),
        "unit": "m/s",
        "action": "overlay:current",
        "why": [{"key": "surface_current",
                 "value": f"{ocean.surface_current_mps} m/s"}],
    }


def _card_tide(ocean: Any) -> Optional[dict]:
    extremes = list(getattr(ocean, "tide_extremes", None) or [])
    has_level = _live(ocean, "tide_level_m")
    if not extremes and not has_level:
        return None
    timeline = []
    for extreme in extremes[:6]:
        kind = getattr(extreme, "kind", None) or (
            extreme.get("kind") if isinstance(extreme, dict) else None)
        when = getattr(extreme, "time_local", None) or (
            extreme.get("time_local") if isinstance(extreme, dict) else None)
        height = getattr(extreme, "height_m", None) if not isinstance(extreme, dict) \
            else extreme.get("height_m")
        if kind and when:
            timeline.append({"kind": str(kind), "time_local": str(when),
                             "height_m": height})
    why = []
    if timeline:
        nxt = timeline[0]
        why.append({"key": f"next_{nxt['kind']}_tide", "value": str(nxt["time_local"])})
    if has_level:
        why.append({"key": "tide_now", "value": f"{ocean.tide_level_m} m"})
    return {
        "type": "tide",
        "value": round(float(ocean.tide_level_m), 2) if has_level else None,
        "unit": "m" if has_level else "",
        "timeline": timeline,
        "action": "tide_timeline",
        "why": why,
    }


def _card_hazard(risk: Any) -> Optional[dict]:
    if risk is None:
        return None
    status = _status_of(risk)
    if not status:
        return None
    flags = []
    for flag in (getattr(risk, "flags", None) or []):
        label = getattr(flag, "label", None) or (
            flag.get("label") if isinstance(flag, dict) else None)
        detail = getattr(flag, "detail", None) or (
            flag.get("detail") if isinstance(flag, dict) else None)
        if label:
            flags.append({"label": str(label), "detail": str(detail or "")})
    why = [{"key": "verdict", "value": status}]
    for flag in flags[:3]:
        why.append({"key": "threshold_crossed",
                    "value": f"{flag['label']} — {flag['detail']}".strip(" — ")})
    if _has_cap(risk):
        why.append({"key": "imd_cap_alerts",
                    "value": str(len(risk.cap_polygons))})
    return {
        "type": "hazard",
        "value": status,
        "unit": "",
        "headline": str(getattr(risk, "headline", "") or ""),
        "flags": flags,
        "cap_count": len(getattr(risk, "cap_polygons", None) or []),
        "action": "show_hazard",
        "why": why,
    }


# --------------------------------------------------------------------------
# readiness score
# --------------------------------------------------------------------------

def compute_readiness(*, ocean: Any, pfz: Any, risk: Any,
                      vessel_class: str = "small_fishing_boat",
                      now: Optional[datetime] = None) -> dict:
    """Today's Fishing Readiness Score with exact per-factor contributions.

    Only factors with live data participate; the rest are listed in
    `excluded` with a reason. Available weights are re-normalised to 100 so
    the reported contributions always sum to the reported score.
    """
    thresholds = get_thresholds(vessel_class)
    wave_unsafe = float(thresholds.get("wave_height_unsafe_m", 2.0))
    gust_unsafe = float(thresholds.get("wind_gust_unsafe_kmh", 40.0))

    raw: dict[str, tuple[float, str]] = {}      # factor -> (0..1 quality, detail)
    excluded: list[dict] = []

    distance = getattr(pfz, "distance_from_reference_km", None) if pfz else None
    if distance is not None:
        distance = float(distance)
        quality = 1.0 if distance <= 30.0 else max(0.0, 1.0 - (distance - 30.0) / 90.0)
        confidence = float(getattr(pfz, "confidence", 1.0) or 1.0)
        raw["pfz"] = (max(0.0, min(1.0, quality * confidence)),
                      f"{distance:.1f} km to nearest zone")
    else:
        excluded.append({"factor": "pfz", "reason": "no PFZ available"})

    gust_field, gust = _first_live(ocean, "wind_gust_kmh", "wind_speed_kmh")
    if gust_field:
        quality = max(0.0, min(1.0, 1.0 - (float(gust) / gust_unsafe)))
        raw["wind"] = (quality, f"{gust} km/h vs {gust_unsafe:g} km/h limit")
    else:
        excluded.append({"factor": "wind", "reason": "wind unavailable"})

    swell_field, swell = _first_live(ocean, "primary_swell_height_m", "wave_height_m")
    if swell_field:
        quality = max(0.0, min(1.0, 1.0 - (float(swell) / wave_unsafe)))
        raw["swell"] = (quality, f"{swell} m vs {wave_unsafe:g} m limit")
    else:
        excluded.append({"factor": "swell", "reason": "wave height unavailable"})

    status = _status_of(risk)
    if status:
        quality = {"SAFE": 1.0, "CAUTION": 0.5}.get(status, 0.0)
        if _has_cap(risk):
            quality = min(quality, 0.25)
        raw["hazard"] = (quality, status if not _has_cap(risk)
                         else f"{status} + IMD alert")
    else:
        excluded.append({"factor": "hazard", "reason": "no verdict"})

    extremes = list(getattr(ocean, "tide_extremes", None) or [])
    if extremes:
        first = extremes[0]
        kind = str(getattr(first, "kind", None) or
                   (first.get("kind") if isinstance(first, dict) else "") or "")
        when = str(getattr(first, "time_local", None) or
                   (first.get("time_local") if isinstance(first, dict) else "") or "")
        hours_away = None
        if when and now is not None:
            try:
                target = datetime.fromisoformat(when)
                if target.tzinfo and now.tzinfo:
                    hours_away = abs((target - now).total_seconds()) / 3600.0
                elif not target.tzinfo and not now.tzinfo:
                    hours_away = abs((target - now).total_seconds()) / 3600.0
            except ValueError:
                hours_away = None
        if hours_away is None:
            quality = 0.5
            detail = f"next {kind} tide {when}".strip()
        else:
            # A high tide within ~3 h is the good departure window.
            quality = 1.0 if hours_away <= 3.0 else max(0.0, 1.0 - (hours_away - 3.0) / 6.0)
            if kind.lower() == "low":
                quality *= 0.6
            detail = f"next {kind} tide in {hours_away:.1f} h"
        raw["tide"] = (max(0.0, min(1.0, quality)), detail)
    else:
        excluded.append({"factor": "tide", "reason": "tide prediction unavailable"})

    if not raw:
        return {"score": None, "score_exact": None, "factors": [],
                "excluded": excluded, "available": False}

    total_weight = sum(_READINESS_WEIGHTS[f] for f in raw)
    factors = []
    for name, (quality, detail) in raw.items():
        share = _READINESS_WEIGHTS[name] / total_weight * 100.0
        factors.append({
            "factor": name,
            "contribution": round(quality * share, 1),
            "max": round(share, 1),
            "quality": round(quality, 3),
            "detail": detail,
        })
    factors.sort(key=lambda f: f["max"], reverse=True)
    score_exact = round(sum(f["contribution"] for f in factors), 1)
    return {
        "score": int(round(score_exact)),
        "score_exact": score_exact,
        "factors": factors,
        "excluded": excluded,
        "available": True,
    }


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def build_dashboard(*, location: Any, language: str = "en", memory: Any = None,
                    ocean: Any = None, pfz: Any = None, risk: Any = None,
                    now: Optional[datetime] = None,
                    vessel_class: str = "small_fishing_boat") -> dict:
    """Rank the cards and compute readiness. No fetching, no LLM."""
    now = now or datetime.now()
    hour = now.hour

    builders = {
        "pfz": lambda: _card_pfz(ocean, pfz),
        "sst": lambda: _card_sst(ocean),
        "wind": lambda: _card_wind(ocean),
        "current": lambda: _card_current(ocean),
        "tide": lambda: _card_tide(ocean),
        "hazard": lambda: _card_hazard(risk),
    }

    dangerous = _is_dangerous(risk)
    cards: list[dict] = []
    omitted: list[str] = []
    for card_type in CARD_TYPES:
        card = builders[card_type]()
        if card is None:
            omitted.append(card_type)     # no data => no card, never a placeholder
            continue
        history = _history_component(card_type, memory)
        location_c = _location_component(card_type, ocean, pfz)
        time_c = _time_component(card_type, hour)
        hazard_c = _hazard_component(card_type, risk)
        score = (W_HISTORY * history + W_LOCATION * location_c
                 + W_TIME * time_c + W_HAZARD * hazard_c)
        card["score"] = round(score, 4)
        card["score_parts"] = {
            "history": round(history, 3), "location": round(location_c, 3),
            "time": round(time_c, 3), "hazard": round(hazard_c, 3),
        }
        card["pinned"] = bool(card_type == "hazard" and dangerous)
        cards.append(card)

    # Hazard override: unsafe seas or an IMD CAP polygon beat learned habit.
    cards.sort(key=lambda c: (c["pinned"], c["score"]), reverse=True)

    readiness = compute_readiness(ocean=ocean, pfz=pfz, risk=risk,
                                  vessel_class=vessel_class, now=now)
    return {
        "cards": cards,
        "omitted_cards": omitted,
        "readiness": readiness,
        "language": language,
        "hour_local": hour,
        "hazard_override": dangerous,
        "location": {
            "name": getattr(location, "name", "") if location else "",
            "lat": getattr(location, "lat", None) if location else None,
            "lon": getattr(location, "lon", None) if location else None,
        },
        "memory_applied": {
            "favorite_cards": list(getattr(memory, "favorite_cards", None) or []),
            "home_port": getattr(memory, "home_port", "") or "",
            "usual_departure": getattr(memory, "usual_departure", "") or "",
            "observations": int(getattr(memory, "observations", 0) or 0),
        } if memory is not None else None,
    }
