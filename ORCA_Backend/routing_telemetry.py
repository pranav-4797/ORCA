"""
Lightweight routing telemetry — Task 6.

In-process counters for routing_mode per query and whether discussion/synthesis LLM ran.
Exposes record() and get_stats() for debug endpoint and test_run summary.
No DB, no persistence — just memory, minimal overhead.
"""
from __future__ import annotations
import time
import threading
from collections import Counter, defaultdict

_lock = threading.Lock()
_counters = Counter()
_timings: list[float] = []
# Detailed per-query log (last 200)
_recent: list[dict] = []

def record(
    routing_mode: str,
    complexity: str,
    discussion_ran: bool,
    synthesis_ran: bool,
    latency_ms: float,
    mode: str = "auto",
):
    """Record one query's telemetry."""
    with _lock:
        _counters["total"] += 1
        _counters[f"routing:{routing_mode}"] += 1
        _counters[f"complexity:{complexity}"] += 1
        _counters[f"mode:{mode}"] += 1
        if discussion_ran:
            _counters["discussion_llm"] += 1
        else:
            _counters["discussion_skipped"] += 1
        if synthesis_ran:
            _counters["synthesis_llm"] += 1
        else:
            _counters["synthesis_skipped"] += 1
        # For X% without LLM call: both discussion and synthesis skipped
        if not discussion_ran and not synthesis_ran:
            _counters["no_llm"] += 1
        else:
            _counters["with_llm"] += 1
        _timings.append(float(latency_ms))
        # Keep only last 500 timings for avg
        if len(_timings) > 500:
            _timings.pop(0)
        # Recent log
        _recent.append({
            "ts": time.time(),
            "routing_mode": routing_mode,
            "complexity": complexity,
            "discussion_llm": discussion_ran,
            "synthesis_llm": synthesis_ran,
            "latency_ms": round(float(latency_ms), 1),
            "mode": mode,
        })
        if len(_recent) > 200:
            _recent.pop(0)

def get_stats() -> dict:
    with _lock:
        total = _counters["total"]
        fast_rules = _counters.get("routing:fast-rules", 0)
        llm_planner = _counters.get("routing:llm-planner", 0)
        rules = _counters.get("routing:rules", 0)
        degraded = _counters.get("routing:degraded", 0)
        no_llm = _counters.get("no_llm", 0)
        with_llm = _counters.get("with_llm", 0)
        avg_latency = sum(_timings)/len(_timings) if _timings else 0
        # Also compute avg for no_llm vs with_llm recent?
        return {
            "total_queries": total,
            "routing_counts": {
                "fast-rules": fast_rules,
                "llm-planner": llm_planner,
                "rules": rules,
                "degraded": degraded,
            },
            "complexity_counts": {
                k.split(":",1)[1]: v for k,v in _counters.items() if k.startswith("complexity:")
            },
            "mode_counts": {
                k.split(":",1)[1]: v for k,v in _counters.items() if k.startswith("mode:")
            },
            "discussion_llm": _counters.get("discussion_llm",0),
            "discussion_skipped": _counters.get("discussion_skipped",0),
            "synthesis_llm": _counters.get("synthesis_llm",0),
            "synthesis_skipped": _counters.get("synthesis_skipped",0),
            "no_llm_queries": no_llm,
            "with_llm_queries": with_llm,
            "no_llm_percent": round(100*no_llm/total, 1) if total else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "recent": list(_recent[-20:]),  # last 20 for debug
        }

def reset():
    with _lock:
        _counters.clear()
        _timings.clear()
        _recent.clear()

def summary_text() -> str:
    s = get_stats()
    total = s["total_queries"]
    if total == 0:
        return "No queries yet."
    lines = [
        f"Telemetry: {total} queries, avg {s['avg_latency_ms']}ms",
        f"  Routing: fast-rules {s['routing_counts']['fast-rules']} ({s['routing_counts']['fast-rules']/total:.0%}), llm-planner {s['routing_counts']['llm-planner']}, rules {s['routing_counts']['rules']}, degraded {s['routing_counts']['degraded']}",
        f"  No LLM (discussion+synthesis skipped): {s['no_llm_queries']} ({s['no_llm_percent']}%) — handled without any LLM call",
        f"  Discussion LLM: {s['discussion_llm']} vs skipped {s['discussion_skipped']}",
        f"  Synthesis LLM: {s['synthesis_llm']} vs skipped {s['synthesis_skipped']}",
    ]
    return "\n".join(lines)
