"""
Marine Memory -- long-term, *inferred* preferences for one fisher.

Unlike sessions.py (one hour of conversation context) this remembers across
days: which cards they actually open, the port they keep asking about, the
language they keep typing in, the hour they usually leave, the map layers they
turn on.

Two rules from the spec drive the whole design:

  1. "Never overwrite after a single query."  Nothing is written to a
     preference field until its evidence crosses PROMOTE_THRESHOLD, so one
     stray question can never rewrite a fisher's home port.

  2. Recency matters more than raw frequency.  Every observation decays the
     existing evidence by DECAY first, so a fisher who switches to asking
     about cyclones sees Hazard climb within a few queries instead of being
     out-voted forever by last month's PFZ habit.

Storage is storage.memory_store -- Redis when REDIS_URL is set, else the
in-process TTL dict. Same pluggability as sessions, no new dependency.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import storage

logger = logging.getLogger("orca.memory")

_TTL_S = 30 * 24 * 3600     # 30 days of silence forgets a fisher
PROMOTE_THRESHOLD = 3.0     # evidence needed before a preference is written
DECAY = 0.85                # applied to every score on each new observation
_FLOOR = 0.05               # drop scores below this so the dict stays small

# One observation of an intent credits its cards. The primary card gets the
# full point; related cards get partial credit, so "wind at my location" mostly
# teaches Wind without pretending it said nothing about SST.
_INTENT_CARDS: dict[str, list[tuple[str, float]]] = {
    "pfz_lookup":     [("pfz", 1.0)],
    "ocean_state":    [("wind", 1.0), ("sst", 0.5), ("tide", 0.3)],
    "safety_check":   [("hazard", 0.7), ("wind", 0.7)],
    "hazard_alerts":  [("hazard", 1.0)],
    "trend_analysis": [("sst", 0.7), ("wind", 0.5)],
    "zone_scan":      [("pfz", 0.7), ("sst", 0.5)],
    "route_plan":     [("current", 0.7), ("wind", 0.5)],
    "geofence_check": [("hazard", 0.5)],
    # Opening the app on the dashboard is the weakest signal of all (no
    # explicit card was picked), so we credit every visible card with 0.1
    # rather than zeroing it out. The decay (0.85) ensures an inert fisher
    # whose interests shift naturally ends up with whatever they ACTUALLY
    # tap outscoring the dashboard auto-credit.
    "dashboard_open": [("pfz", 0.1), ("sst", 0.1), ("wind", 0.1),
                       ("current", 0.1), ("tide", 0.1), ("hazard", 0.1)],
    "unknown":        [],
}

# An explicit card tap is worth more than an inferred intent -- the fisher
# told us directly.
_CARD_TAP_WEIGHT = 1.5


def _departure_bucket(hour: int) -> str:
    if 4 <= hour < 7:
        return "pre_dawn"
    if 7 <= hour < 11:
        return "morning"
    if 11 <= hour < 16:
        return "afternoon"
    if 16 <= hour < 20:
        return "evening"
    return "night"


@dataclass
class MarineMemory:
    """Inferred preferences. Empty strings/lists mean "not learned yet"."""
    user_key: str
    home_port: str = ""
    preferred_language: str = ""
    favorite_cards: list = field(default_factory=list)
    usual_departure: str = ""
    vessel_type: str = ""
    favorite_map_layers: list = field(default_factory=list)
    # Raw evidence: {"card:pfz": 3.2, "port:Ratnagiri": 2.0, ...}
    scores: dict = field(default_factory=dict)
    observations: int = 0
    updated_at: float = field(default_factory=time.time)

    def card_score(self, card_type: str) -> float:
        return float(self.scores.get(f"card:{card_type}", 0.0))

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def get(user_key: Optional[str]) -> MarineMemory:
    """Never returns None -- an unknown fisher is an empty memory."""
    if not user_key:
        return MarineMemory(user_key="")
    raw = storage.memory_store.get(str(user_key))
    if not raw:
        return MarineMemory(user_key=str(user_key))
    try:
        return MarineMemory(**raw)
    except TypeError:          # schema drift -- start clean rather than crash
        logger.info("memory schema drift for %s; resetting", user_key)
        return MarineMemory(user_key=str(user_key))


def reset(user_key: str) -> None:
    storage.memory_store.delete(str(user_key))


def _bump(scores: dict, key: str, amount: float) -> None:
    scores[key] = round(float(scores.get(key, 0.0)) + amount, 4)


def _top(scores: dict, prefix: str) -> tuple[str, float]:
    """Highest-scoring value under a prefix, e.g. ("Ratnagiri", 3.4)."""
    best, best_score = "", 0.0
    for key, val in scores.items():
        if key.startswith(prefix) and float(val) > best_score:
            best, best_score = key[len(prefix):], float(val)
    return best, best_score


def _promoted(scores: dict, prefix: str) -> list:
    """Every value under a prefix that crossed the threshold, strongest first."""
    hits = [
        (key[len(prefix):], float(val))
        for key, val in scores.items()
        if key.startswith(prefix) and float(val) >= PROMOTE_THRESHOLD
    ]
    hits.sort(key=lambda kv: kv[1], reverse=True)
    return [name for name, _ in hits]


def observe(
    user_key: Optional[str],
    *,
    intent: Optional[str] = None,
    card: Optional[str] = None,
    location_name: Optional[str] = None,
    language: Optional[str] = None,
    hour: Optional[int] = None,
    layer: Optional[str] = None,
    vessel_class: Optional[str] = None,
) -> MarineMemory:
    """Record one interaction and re-derive the preference fields.

    Every argument is optional; only what actually happened is credited. Safe
    to call on every query -- callers wrap it in try/except so memory can
    never break an answer.
    """
    if not user_key:
        return MarineMemory(user_key="")

    mem = get(user_key)
    scores = {k: float(v) * DECAY for k, v in (mem.scores or {}).items()}

    if intent:
        for card_type, weight in _INTENT_CARDS.get(str(intent), []):
            _bump(scores, f"card:{card_type}", weight)
    if card:
        _bump(scores, f"card:{card}", _CARD_TAP_WEIGHT)
    if location_name and str(location_name).strip():
        _bump(scores, f"port:{str(location_name).strip()}", 1.0)
    if language:
        _bump(scores, f"lang:{str(language).strip().lower()}", 1.0)
    if hour is not None:
        try:
            _bump(scores, f"depart:{_departure_bucket(int(hour))}", 1.0)
        except (TypeError, ValueError):
            pass
    if layer:
        _bump(scores, f"layer:{str(layer).strip().lower()}", _CARD_TAP_WEIGHT)
    if vessel_class:
        _bump(scores, f"vessel:{str(vessel_class).strip()}", 1.0)

    scores = {k: v for k, v in scores.items() if v >= _FLOOR}

    port, port_score = _top(scores, "port:")
    lang, lang_score = _top(scores, "lang:")
    depart, depart_score = _top(scores, "depart:")
    vessel, vessel_score = _top(scores, "vessel:")

    mem.scores = scores
    mem.observations = int(mem.observations or 0) + 1
    # Promotion only -- an existing learned value survives until something else
    # out-scores it past the threshold.
    if port_score >= PROMOTE_THRESHOLD:
        mem.home_port = port
    if lang_score >= PROMOTE_THRESHOLD:
        mem.preferred_language = lang
    if depart_score >= PROMOTE_THRESHOLD:
        mem.usual_departure = depart
    if vessel_score >= PROMOTE_THRESHOLD:
        mem.vessel_type = vessel
    mem.favorite_cards = _promoted(scores, "card:")
    mem.favorite_map_layers = _promoted(scores, "layer:")
    mem.updated_at = time.time()

    storage.memory_store.set(str(user_key), mem.as_dict(), ttl_s=_TTL_S)
    return mem


def observe_safe(user_key: Optional[str], **kwargs) -> None:
    """Fire-and-forget wrapper for hot paths (the orchestrator)."""
    try:
        observe(user_key, **kwargs)
    except Exception as exc:                      # never break a query
        logger.debug("memory observe failed: %s", exc)
