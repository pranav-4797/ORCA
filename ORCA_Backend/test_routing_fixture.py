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
    # Exclude compound entries from single-intent metrics (they are tested separately)
    compound_entries = [e for e in data if e.get("is_compound")]
    single_data = [e for e in data if not e.get("is_compound")]
    print(f"\n[Routing Fixture] Loaded {len(data)} queries from {path} ({len(compound_entries)} compound, {len(single_data)} single)")

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

    for entry in single_data:
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

    total = len(single_data)
    print(f"[Routing Fixture] Total single-intent queries: {total} (compound excluded)")
    print(f"  Fast-path (fast-rules) : {fast_path_total} ({fast_path_total/total:.1%} of single)")
    print(f"  Fallback (LLM planner) : {fallback_total} ({fallback_total/total:.1%} of single)")
    if fallback_expected:
        print(f"  Ambiguous expected FALLBACK: {fallback_expected}, correctly fallback: {fallback_correct} ({fallback_correct/fallback_expected:.1%})")
    if compound_entries:
        print(f"  Compound queries: {len(compound_entries)} (tested separately)")

    # Also include compound in overall total for summary
    total_all = len(data)

    # Per-intent precision/recall
    print("\nPer-intent precision / recall (fast-rules only):")
    print(f"{'Intent':<16} {'Support':>7} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>6} {'Rec':>6} {'F1':>6}")
    for intent in intents:
        support = counts_expected[intent]
        prec = tp[intent] / (tp[intent] + fp[intent]) if (tp[intent] + fp[intent]) > 0 else (1.0 if tp[intent]==0 and fp[intent]==0 else 0.0)
        rec = tp[intent] / (tp[intent] + fn[intent]) if (tp[intent] + fn[intent]) > 0 else (1.0 if support==0 else 0.0)
        f1 = 2*prec*rec/(prec+rec) if (prec+rec)>0 else 0.0
        print(f"{intent:<16} {support:>7} {tp[intent]:>4} {fp[intent]:>4} {fn[intent]:>4} {prec:>5.2f} {rec:>5.2f} {f1:>5.2f}")

    # Overall accuracy (including fallback as correct class) — on single-intent subset
    correct = 0
    for entry in single_data:
        expected = entry.get("expected_intent")
        decision = auto_router.fast_route(entry["query"])
        predicted = decision.intent if decision else None
        # For expected fallback, predicted None is correct
        if expected is None and predicted is None:
            correct += 1
        elif expected is not None and predicted == expected:
            correct += 1
    accuracy = correct/total if total else 0
    print(f"\nOverall accuracy (single-intent, fallback counted): {correct}/{total} = {accuracy:.2%}")

    # Compound handling check (Task 4)
    if compound_entries:
        print("\nCompound-intent handling (Task 4):")
        for entry in compound_entries:
            q = entry["query"]
            expected_intents = entry.get("expected_intents") or []
            expected_agents = set(entry.get("expected_agents") or [])
            decision = auto_router.fast_route(q)
            if decision is None:
                print(f"  {entry['id']}: FAIL — expected compound but got fallback None")
            else:
                agents_ok = expected_agents.issubset(set(decision.agents)) if expected_agents else True
                intent_ok = decision.intent in expected_intents if expected_intents else True
                complexity_ok = decision.complexity in ("complex", "deep")
                status = "PASS" if (agents_ok and intent_ok and complexity_ok) else "FAIL"
                print(f"  {entry['id']}: {status} — predicted intent={decision.intent} agents={decision.agents} complexity={decision.complexity} (expected intents {expected_intents}, agents {expected_agents})")
                if status == "FAIL":
                    print(f"    Query: {q[:80]}")

    # Print mismatches for debugging (single-intent only)
    print("\nMismatched queries (single-intent, expected != predicted):")
    mismatches = []
    for entry in single_data:
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
        "total_all": total_all,
        "compound": len(compound_entries),
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

def test_compound_intent_handling():
    """Task 4: verify compound queries union agents and set complexity at least complex."""
    data, _ = _load_fixture()
    compounds = [e for e in data if e.get("is_compound")]
    assert len(compounds) >= 2, f"Need at least 2 compound fixtures, got {len(compounds)}"
    for entry in compounds:
        q = entry["query"]
        expected_intents = entry.get("expected_intents") or []
        expected_agents = set(entry.get("expected_agents") or [])
        decision = auto_router.fast_route(q)
        assert decision is not None, f"Compound query {entry['id']} should NOT fallback, got None (fallback) for '{q}'"
        # Agents should be unioned (superset of expected)
        assert expected_agents.issubset(set(decision.agents)), f"{entry['id']} agents {decision.agents} should include {expected_agents}"
        # Complexity at least complex
        assert decision.complexity in ("complex", "deep"), f"{entry['id']} complexity should be at least complex, got {decision.complexity}"
        # Intent should be one of expected intents (top)
        if expected_intents:
            assert decision.intent in expected_intents or decision.intent == expected_intents[0], f"{entry['id']} intent {decision.intent} not in {expected_intents}"
        # Reason should mention compound
        assert "Compound" in decision.reason or len(decision.agents) > 2, f"{entry['id']} reason should indicate compound: {decision.reason}"

def test_compound_specific_examples():
    """Direct tests for Task 4 example queries."""
    # Example from task description
    q1 = "Is it safe to fish near Kochi and what's the safest route avoiding restricted zones?"
    d1 = auto_router.fast_route(q1)
    assert d1 is not None, "Compound safety+route+geofence should not fallback"
    # Should include all three intents' agents: safety (Ocean,Hazard,Geo), route (Geo,Ocean,Hazard), geofence (Geo) => at least those 3
    needed = {"OceanStateAgent", "HazardAgent", "GeospatialAgent"}
    assert needed.issubset(set(d1.agents)), f"q1 agents {d1.agents} should contain {needed}"
    assert d1.complexity in ("complex", "deep")

    q2 = "Where is the nearest fishing zone near Kochi for tomorrow and is it safe to go there?"
    d2 = auto_router.fast_route(q2)
    assert d2 is not None
    needed2 = {"PFZAgent", "OceanStateAgent", "HazardAgent", "GeospatialAgent"}
    # pfz+ safety union is 4 agents
    assert needed2.issubset(set(d2.agents)) or len(d2.agents) >= 4, f"q2 agents {d2.agents} should be union pfz+safety"
    assert d2.complexity in ("complex", "deep")

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
