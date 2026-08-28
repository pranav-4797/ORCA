"""
Pluggable key/value storage with TTL -- PDF Sec 13 names Redis for
production; this keeps the demo dependency-free while making the swap a
single env var:

    REDIS_URL=redis://localhost:6379/0   -> real Redis backend
    (unset)                              -> in-process dict backend

Values are JSON-serialised so both backends behave identically. Used by
sessions.py (conversation memory) and main.py (response cache).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("orca.storage")

REDIS_URL = os.getenv("REDIS_URL", "").strip()


class TTLStore:
    """Uniform get/set/delete over Redis or an in-process dict."""

    def __init__(self, namespace: str = "orca"):
        self._ns = namespace
        self._lock = threading.Lock()
        self._redis = None
        if REDIS_URL:
            try:
                import redis  # optional dependency

                client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                client.ping()
                self._redis = client
                logger.info("storage backend: redis (%s)", REDIS_URL)
            except Exception as exc:  # fall back, never crash the app
                logger.warning(
                    "REDIS_URL set but unreachable (%s); using in-process store", exc,
                )
        self._mem: dict[str, tuple[float, str]] = {}
        self.backend = "redis" if self._redis else "memory"

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def get(self, key: str) -> Optional[Any]:
        full = self._key(key)
        if self._redis is not None:
            raw = self._redis.get(full)
            return json.loads(raw) if raw is not None else None
        with self._lock:
            hit = self._mem.get(full)
            if hit is None:
                return None
            expires_at, raw = hit
            if time.monotonic() > expires_at:
                del self._mem[full]
                return None
            return json.loads(raw)

    def set(self, key: str, value: Any, ttl_s: float = 3600.0) -> None:
        full = self._key(key)
        raw = json.dumps(value, default=str)
        if self._redis is not None:
            self._redis.setex(full, max(int(ttl_s), 1), raw)
            return
        with self._lock:
            self._mem[full] = (time.monotonic() + ttl_s, raw)
            if len(self._mem) > 4096:  # opportunistic sweep
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._mem.items() if exp < now]
                for k in expired:
                    del self._mem[k]

    def delete(self, key: str) -> None:
        full = self._key(key)
        if self._redis is not None:
            self._redis.delete(full)
            return
        with self._lock:
            self._mem.pop(full, None)


# Shared instances (one namespace per concern).
session_store = TTLStore("sessions")
response_cache = TTLStore("responses")


def info() -> dict:
    return {
        "backend": session_store.backend,
        "redis_url": REDIS_URL or None,
    }
