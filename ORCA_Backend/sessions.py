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
    """Everything remembered about one conversation."""
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
    for k, v in kwargs.items():
        if v is not None:
            setattr(s, k, v)
    s.updated_at = time.time()
    storage.session_store.set(session_id, dataclasses.asdict(s), ttl_s=_TTL_S)
    return s


def clear(session_id: str) -> None:
    storage.session_store.delete(session_id)
