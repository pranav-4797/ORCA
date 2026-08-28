"""
Demo-scenario cache — Task 9.

Feature-flagged (env ORCA_DEMO_CACHE, default off) that serves pre-generated
full discussion transcript + final response from JSON fixtures when query matches
a known demo scenario. Response is clearly marked mode=cached_demo.

No behavior change when flag off.
"""
from __future__ import annotations
import os
import json
import hashlib
from pathlib import Path
from typing import Optional

_CACHE_DIR = Path(__file__).resolve().parent / "demo_cache"
# Also check test_data/demo_cache fallback
if not _CACHE_DIR.exists():
    alt = Path(__file__).resolve().parent / "test_data" / "demo_cache"
    if alt.exists():
        _CACHE_DIR = alt

# Fixed demo queries — these are the canonical demo scenarios.
# They are normalized (strip, lower) for matching.
DEMO_QUERIES = [
    "Is it safe to fish near Ratnagiri tomorrow?",
    "Where is the nearest fishing zone near Kochi today?",
    "Is it safe to fish near Kochi and what's the safest route avoiding restricted zones?",
    "Why has SST changed over the last 6 months near Kochi?",
    "Am I near a restricted area off Kochi?",
]

def _normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())

# Build lookup from normalized query to cache file key
def _cache_key_for_query(query: str) -> str:
    norm = _normalize(query)
    # Use hash of normalized for stable file name
    h = hashlib.sha256(norm.encode()).hexdigest()[:12]
    # Also try to find a descriptive name
    return h

def is_enabled() -> bool:
    return os.getenv("ORCA_DEMO_CACHE", "").strip().lower() in ("1", "true", "yes", "on")

def _fixture_path_for_query(query: str) -> Path:
    key = _cache_key_for_query(query)
    return _CACHE_DIR / f"{key}.json"

def _fixture_path_for_normalized(norm: str) -> Optional[Path]:
    # Try to find matching fixture by checking all DEMO_QUERIES
    for demo_q in DEMO_QUERIES:
        if _normalize(demo_q) == norm:
            return _CACHE_DIR / f"{_cache_key_for_query(demo_q)}.json"
    # Also check if any fixture file matches this hash directly
    direct = _CACHE_DIR / f"{_cache_key_for_query(norm)}.json"
    if direct.exists():
        return direct
    return None

def get_cached_response(query: str):
    """
    If demo cache enabled and query matches a known demo scenario with a fixture file,
    return the deserialized response dict (with mode=cached_demo). Else return None.
    """
    if not is_enabled():
        return None
    if not _CACHE_DIR.exists():
        return None
    norm = _normalize(query)
    path = _fixture_path_for_normalized(norm)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Ensure mode is cached_demo
        data["mode"] = "cached_demo"
        data["cached_demo"] = True
        return data
    except Exception:
        return None

def get_cached_orchestrator_response(query: str, session_id: str | None = None):
    """
    Return an OrchestratorResponse object for a cached demo query, or None if not found/disabled.
    The response is marked mode=cached_demo so it's never confused with live.
    """
    data = get_cached_response(query)
    if data is None:
        return None
    try:
        from models import SafetyStatus, AgentTrace, OrchestratorResponse
        # Reconstruct minimal OrchestratorResponse from cached dict
        status_str = data.get("status", "CAUTION")
        try:
            status = SafetyStatus(status_str)
        except:
            # Handle string like "SafetyStatus.SAFE" or plain
            status = SafetyStatus.CAUTION
            if isinstance(status_str, str):
                upper = status_str.upper().replace("SAFETYSTATUS.", "").strip()
                for s in SafetyStatus:
                    if s.value.upper() == upper:
                        status = s
                        break
        # Reconstruct traces
        traces = []
        for t in data.get("trace", []) or []:
            try:
                # t may be dict with agent_name, action, etc.
                if isinstance(t, dict):
                    traces.append(AgentTrace(
                        agent_name=t.get("agent_name", "Unknown"),
                        action=t.get("action", ""),
                        result_summary=t.get("result_summary", "")[:200],
                        data_sources=[],
                        duration_ms=float(t.get("duration_ms", 0)),
                    ))
                else:
                    traces.append(t)
            except:
                continue
        # Add demo cache trace
        traces.append(AgentTrace(
            agent_name="DemoCache",
            action="Served cached demo response (ORCA_DEMO_CACHE=on)",
            result_summary=f"Cache hit for '{query[:60]}' — no LLM call, mode=cached_demo",
            data_sources=[],
            duration_ms=0.0,
        ))
        resp = OrchestratorResponse(
            answer=data.get("answer", ""),
            status=status,
            reasoning=data.get("reasoning", []),
            evidence_sources=[],
            trace=traces,
            language=data.get("language", "en"),
            mode="cached_demo",
            answered_by="DemoCache (cached_demo — no live LLM)",
            confidence_score=float(data.get("confidence_score", 0) or 0),
            timings=data.get("timings", {}),
            routing=data.get("routing", {"routing_mode": "cached_demo"}),
        )
        # Attach extra fields if present
        # Preserve discussion if present
        resp.discussion = data.get("discussion", [])
        # For viz, try to preserve ocean_state etc as dict? Keep as is for now
        # Mark as cached
        resp.timings = data.get("timings", {})
        return resp
    except Exception as e:
        # Fallback: return None so live path runs
        return None

def load_fixture_dict(query: str) -> Optional[dict]:
    path = _fixture_path_for_normalized(_normalize(query))
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None

def list_demo_scenarios() -> list[str]:
    return list(DEMO_QUERIES)

def cache_dir() -> Path:
    return _CACHE_DIR
