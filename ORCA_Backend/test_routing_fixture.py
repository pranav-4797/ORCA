"""
Routing fixture evaluation — Task 3.

Loads test_data/routing_queries.json and runs auto_router.fast_route()
against each query. Reports precision/recall per intent plus overall
fast-path vs fallback rate. Does NOT change confidence thresholds.
"""
import json
from pathlib import Path
from collections import defaultdict, Counter

import auto_router

FIXTURE_PATHS = [
    Path(__file__).resolve().parent / "test_data" / "routing_queries.json",
    Path(__file__).resolve().parent.parent / "ORCA_Backend" / "test_data" / "routing_queries.json",
    Path(__file__).resolve().parents[1] / "ORCA UI" / "test_data" / "routing_queries.json",
]
# Also try repo root discovery
for p in Path(__file__).resolve().parents:
    cand = p / "ORCA_Backend" / "test_data" / "routing_queries.json"
    if cand.exists():
        FIXTURE_PATHS.insert(0, cand)
        break
    cand2 = p / "test_data" / "routing_queries.json"
    if cand2.exists():
        FIXTURE_PATHS.insert(0, cand2)
        break

def _load_fixture():
    for p in FIXTURE_PATHS:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")), p
    # fallback: search recursively
    for parent in Path(__file__).resolve().parents:
        cand = parent / "ORCA_Backend" / "test_data" / "routing_queries.json"
        if cand.exists():
            return json.loads(cand.read_text(encoding="utf-8")), cand
    raise FileNotFoundError(f"routing_queries.json not found, tried {FIXTURE_PATHS}")

def test_routing_fixture_metrics():
    data, path = _load_fixture()
    assert isinstance(data, list) and len(data) >= 40, f"Fixture should have >=40 queries, got {len(data)} at {path}"
    print(f"\n[Routing Fixture] Loaded {len(data)} queries from {path}")

    intents = ["safety_check", "pfz_lookup", "hazard_alerts", "route_plan", "geofence_check", "trend_analysis", "zone_scan"]
    # Also track fallback expected
    counts_expected = Counter()
    counts_predicted = Counter()
    tp = Counter()
    fp = Counter()
    fn = Counter()

    details = []
    fallback_expected = 0
    fallback_correct = 0
    fast_path_total = 0
    fallback_total = 0

    for entry in data:
        q = entry["query"]
        expected = entry.get("expected_intent")  # None means should fallback
        decision = auto_router.fast_route(q)
        predicted = decision.intent if decision is not None else None
        confidence = decision.confidence if decision else 0.0
        should_fallback = auto_router.should_use_llm_fallback(decision, q)

        # Track fast-path vs fallback
        if decision is None or should_fallback:
            fallback_total += 1
        else:
            fast_path_total += 1

        # For metrics
        exp_label = expected if expected is not None else "FALLBACK"
        pred_label = predicted if predicted is not None else "FALLBACK"
        counts_expected[exp_label] += 1
        counts_predicted[pred_label] += 1

        # Per-intent TP/FP/FN
        for intent in intents:
            is_expected = (expected == intent)
            is_predicted = (predicted == intent)
            if is_expected and is_predicted:
                tp[intent] += 1
            elif not is_expected and is_predicted:
                fp[intent] += 1
            elif is_expected and not is_predicted:
                fn[intent] += 1
        # Fallback correct?
        if expected is None:
            fallback_expected += 1
            if predicted is None or should_fallback:
                fallback_correct += 1

        details.append((entry.get("id", ""), q[:60], expected, predicted, confidence, should_fallback))
        # Debug per query if mismatch
        # print(f"{entry.get('id')}: expected={expected}, predicted={predicted} conf={confidence} fallback={should_fallback}")

    total = len(data)
    print(f"[Routing Fixture] Total queries: {total}")
    print(f"  Fast-path (fast-rules) : {fast_path_total} ({fast_path_total/total:.1%})")
    print(f"  Fallback (LLM planner) : {fallback_total} ({fallback_total/total:.1%})")
    if fallback_expected:
        print(f"  Ambiguous expected FALLBACK: {fallback_expected}, correctly fallback: {fallback_correct} ({fallback_correct/fallback_expected:.1%})")

    # Per-intent precision/recall
    print("\nPer-intent precision / recall (fast-rules only):")
    print(f"{'Intent':<16} {'Support':>7} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>6} {'Rec':>6} {'F1':>6}")
    for intent in intents:
        support = counts_expected[intent]
        prec = tp[intent] / (tp[intent] + fp[intent]) if (tp[intent] + fp[intent]) > 0 else (1.0 if tp[intent]==0 and fp[intent]==0 else 0.0)
        rec = tp[intent] / (tp[intent] + fn[intent]) if (tp[intent] + fn[intent]) > 0 else (1.0 if support==0 else 0.0)
        f1 = 2*prec*rec/(prec+rec) if (prec+rec)>0 else 0.0
        print(f"{intent:<16} {support:>7} {tp[intent]:>4} {fp[intent]:>4} {fn[intent]:>4} {prec:>5.2f} {rec:>5.2f} {f1:>5.2f}")

    # Overall accuracy (including fallback as correct class)
    correct = 0
    for entry in data:
        expected = entry.get("expected_intent")
        decision = auto_router.fast_route(entry["query"])
        predicted = decision.intent if decision else None
        # For expected fallback, predicted None is correct
        if expected is None and predicted is None:
            correct += 1
        elif expected is not None and predicted == expected:
            correct += 1
    accuracy = correct/total
    print(f"\nOverall accuracy (fast-rules vs expected, fallback counted): {correct}/{total} = {accuracy:.2%}")

    # Print mismatches for debugging
    print("\nMismatched queries (expected != predicted):")
    mismatches = []
    for entry in data:
        expected = entry.get("expected_intent")
        decision = auto_router.fast_route(entry["query"])
        predicted = decision.intent if decision else None
        if predicted != expected:
            # For fallback expected, None is correct, so only print if wrong
            if not (expected is None and predicted is None):
                mismatches.append((entry.get("id"), entry["query"], expected, predicted, decision.confidence if decision else 0))
                print(f"  {entry.get('id'):<14} expected={str(expected):<14} predicted={str(predicted):<14} conf={decision.confidence if decision else 0:.2f}  query='{entry['query'][:70]}'")

    # Assertions — keep permissive, just ensure fixture sanity and fallback behavior
    # 1. At least 7 ambiguous queries exist and mostly fallback
    assert fallback_expected >= 8, f"Fixture should have >=8 ambiguous queries, got {fallback_expected}"
    assert fallback_correct >= 0.7 * fallback_expected, f"Ambiguous fallback rate too low: {fallback_correct}/{fallback_expected} — thresholds may need tuning or fixture mis-specified"
    # 2. Overall fast-path rate should be reasonable (not 0% nor 100%)
    assert 0.3 <= fast_path_total/total <= 0.9, f"Fast-path rate out of expected range: {fast_path_total/total:.1%}"
    # 3. At least some intents have non-zero recall
    non_zero_recall = sum(1 for i in intents if tp[i] > 0)
    assert non_zero_recall >= 4, f"Only {non_zero_recall} intents have any correct predictions — router likely broken"

    # Save a summary JSON for manual inspection (optional)
    summary = {
        "total": total,
        "fast_path": fast_path_total,
        "fallback": fallback_total,
        "fallback_expected": fallback_expected,
        "fallback_correct": fallback_correct,
        "accuracy": accuracy,
        "per_intent": { intent: {
            "support": counts_expected[intent],
            "tp": tp[intent],
            "fp": fp[intent],
            "fn": fn[intent],
            "precision": tp[intent]/(tp[intent]+fp[intent]) if (tp[intent]+fp[intent])>0 else 0,
            "recall": tp[intent]/(tp[intent]+fn[intent]) if (tp[intent]+fn[intent])>0 else 0,
        } for intent in intents}
    }
    # Write summary next to fixture for inspection
    try:
        out_path = path.parent / "routing_metrics.json"
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\n[Routing Fixture] Summary written to {out_path}")
    except Exception:
        pass

def test_routing_fixture_file_exists():
    data, path = _load_fixture()
    assert path.exists()
    assert len(data) >= 48  # 40-60 + ambiguous
    # Check each has query and expected_intent
    for entry in data:
        assert "query" in entry and isinstance(entry["query"], str) and entry["query"].strip()
        assert "expected_intent" in entry
        if entry["expected_intent"] is not None:
            assert entry["expected_intent"] in ["safety_check","pfz_lookup","hazard_alerts","route_plan","geofence_check","trend_analysis","zone_scan"]
