"""
SAR Observation Cache — short-TTL cache so identical area/time windows
don't re-download SAR products repeatedly.

Reuses storage.TTLStore when REDIS_URL is set, otherwise in-process dict.
All cached observations carry provenance so the UI can show REAL vs SIMULATED
vs STALE vs UNAVAILABLE honestly.

Policy:
  ORCA_SAR_CACHE_TTL_S  default 600s (10 min) — SAR observations are not
                        per-second like wave forecasts; 10 min is reasonable
  ORCA_SAR_STALE_MINUTES  default 120 (2h) — observations older than this
                          are flagged STALE, not presented as "real-time"
"""
from __future__ import annotations

import os
import time
import json
import hashlib
import threading
from typing import Optional

import storage

SAR_CACHE_TTL_S = int(os.getenv("ORCA_SAR_CACHE_TTL_S", "600").strip() or 600)
SAR_NEGATIVE_TTL_S = int(os.getenv("ORCA_SAR_NEGATIVE_TTL_S", "120").strip() or 120)


class SARStore:
    """
    Thin wrapper over storage.TTLStore for SAR observations + scan results.

    Keys are SHA-256 hex digests of (area + provider + time_window), so the
    same scan over the same waters returns cached results without re-fetching
    SAR products.

    Stored values are JSON dicts (SARScanResult.to_dict) — safe for both
    Redis and in-memory backends.
    """

    def __init__(self):
        self._ttl = SAR_CACHE_TTL_S
        self._neg_ttl = SAR_NEGATIVE_TTL_S
        # Reuse the shared TTLStore namespace pattern (separate key prefix)
        self._store = storage.TTLStore("sar")
        # In-memory fallback for the latest observation (always accessible)
        self._lock = threading.Lock()
        self._latest: Optional[dict] = None
        self._latest_time: float = 0

    def _key(self, area: Optional[dict], provider: str, time_window: str) -> str:
        raw = json.dumps({"area": area or {}, "provider": provider, "window": time_window}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, area: Optional[dict], provider: str, time_window: str = "today") -> Optional[dict]:
        key = self._key(area, provider, time_window)
        return self._store.get(key)

    def set(self, area: Optional[dict], provider: str, scan_dict: dict, time_window: str = "today", ttl_s: Optional[int] = None) -> None:
        key = self._key(area, provider, time_window)
        ttl = ttl_s if ttl_s is not None else self._ttl
        # Negative caching: UNAVAILABLE results get shorter TTL
        if scan_dict.get("status") == "UNAVAILABLE":
            ttl = self._neg_ttl
        self._store.set(key, scan_dict, ttl_s=ttl)
        with self._lock:
            self._latest = scan_dict
            self._latest_time = time.time()

    def get_latest(self) -> Optional[dict]:
        with self._lock:
            return self._latest

    def clear(self) -> None:
        # Clear in-memory by setting expired placeholders? TTLStore has no bulk delete
        # So we clear the latest pointer and let TTL entries expire naturally;
        # for in-memory backend we can iterate (access private _mem under lock)
        with self._lock:
            self._latest = None
            self._latest_time = 0
        # Attempt to clear known in-memory keys (best-effort)
        try:
            if hasattr(self._store, "_mem"):
                with self._store._lock:  # type: ignore
                    prefix = self._store._ns + ":"  # type: ignore
                    to_del = [k for k in list(self._store._mem.keys()) if k.startswith(prefix)]  # type: ignore
                    for k in to_del:
                        self._store._mem.pop(k, None)  # type: ignore
            elif hasattr(self._store, "_redis") and getattr(self._store, "_redis") is not None:
                # Redis: SCAN and delete
                r = self._store._redis  # type: ignore
                pattern = self._store._ns + ":*"  # type: ignore
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor=cursor, match=pattern, count=200)
                    if keys:
                        r.delete(*keys)
                    if cursor == 0:
                        break
        except Exception:
            pass

    def cache_info(self) -> dict:
        with self._lock:
            age = round(time.time() - self._latest_time, 1) if self._latest_time else None
            has_latest = self._latest is not None
        return {
            "ttl_s": self._ttl,
            "negative_ttl_s": self._neg_ttl,
            "has_latest": has_latest,
            "latest_age_s": age,
            "backend": getattr(self._store, "backend", "memory"),
        }


# Global singleton — reused across requests
sar_store = SARStore()
