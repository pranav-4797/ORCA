"""
Session memory (PS requirement: multi-turn conversation context).

A tiny store keyed by session_id carrying what a follow-up question needs:
last location, time window, language, GPS/destination and the previous
plan. The Orchestrator consults it BEFORE planning so queries like "what
about the day after?" or "and near Visakhapatnam?" resolve against
remembered context instead of failing.

Design: backed by storage.TTLStore -- Redis when REDIS_URL is set (shared
across workers, PDF Sec. 13), else an in-process TTL dict. Callers are
unaffected either way.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Optional

import storage


_TTL_S = 3600  # 1 hour of silence expires a session


@dataclass
class SessionContext:
    """Everything remembered about one conversation.

    Smarter memory (Intent+Memory upgrade):
    - Keeps a rolling history of the last 6 turns (user queries + intents)
      so pronoun-heavy follow-ups like "why there?" or "what about the wind?"
      can be resolved without an LLM.
    - Stores last vessel class, last ocean/hazard summary and last tourism
      count so the next turn's planning can be context-aware even when the
      LLM is down.
    """
    session_id: str
    location_name: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    time_window: str = "today"
    target_hour: Optional[int] = None
    language: str = "en"
    device_gps: Optional[tuple] = None
    map_point: Optional[tuple] = None
    destination: Optional[dict] = None          # {"lat","lon","name"}
    last_intent: str = ""
    last_query: str = ""
    # Conversation findings — so "why is that?" / "what about the wind?" can be answered
    last_verdict: str = ""                      # e.g. "CAUTION — borderline"
    last_answer: str = ""                       # truncated final answer (first ~500 chars)
    last_evidence: str = ""                     # key evidence line for the verdict
    # Richer memory for smarter follow-ups
    last_vessel_class: str = ""                 # e.g. "small_fishing_boat"
    last_ocean_summary: str = ""                # e.g. "SST 28.5C wind 12km/h"
    last_hazard_summary: str = ""               # e.g. "SAFE — calm seas"
    last_tourism_count: int = 0
    # Rolling history: list of {"role": "user"|"assistant", "content": str, "intent": str, "location": str, "ts": float}
    history: list = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


def get(session_id: Optional[str]) -> Optional[SessionContext]:
    if not session_id:
        return None
    raw = storage.session_store.get(session_id)
    if raw is None:
        return None
    try:
        ctx = SessionContext(**raw)
    except TypeError:
        return None  # schema drift -- treat as expired
    if time.time() - ctx.updated_at > _TTL_S:
        clear(session_id)
        return None
    return ctx


def upsert(session_id: str, **kwargs) -> SessionContext:
    s = get(session_id) or SessionContext(session_id=session_id)
    # Handle history append separately so callers can pass history_entry
    history_entry = kwargs.pop("history_entry", None)
    for k, v in kwargs.items():
        if v is not None:
            setattr(s, k, v)
    if history_entry is not None:
        try:
            # Keep at most 6 turns to bound storage
            s.history.append(history_entry)
            if len(s.history) > 6:
                s.history = s.history[-6:]
        except Exception:
            pass
    s.updated_at = time.time()
    storage.session_store.set(session_id, dataclasses.asdict(s), ttl_s=_TTL_S)
    return s

def append_history(session_id: str, role: str, content: str, intent: str = "", location: str = "") -> None:
    """Convenience: add one turn to the rolling history."""
    try:
        upsert(session_id, history_entry={"role": role, "content": content[:400], "intent": intent, "location": location, "ts": time.time()})
    except Exception:
        pass


def clear(session_id: str) -> None:
    storage.session_store.delete(session_id)
