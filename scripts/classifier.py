"""Rule-based archetype classifier with LLM fallback.

Input: a task summary dict (the kind summarize_features.py emits).
Output: (archetype, confidence, reasons)

Rules are tuned from the 199-task labeled set. Confidence < 0.6 means
the caller should consult LLM for adjudication.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CANONICAL_ARCHETYPES = [
    "ByteExactGolden",
    "CliSurfaceAndExitCode",
    "FilesystemSideEffect",
    "TuiScreenSnapshot",
    "LinterDiagnostic",
    "NumericTolerance",
    "OrchestrationDrivenWatcher",
    "MassiveFixtureSuite",
]


def _dist(s: dict, key: str) -> float:
    return s.get("assertion_distribution", {}).get(key, 0.0)


def _has_golden_in_docstrings(s: dict) -> bool:
    docs = s.get("docstring_samples", []) or []
    return any("golden" in (d or "").lower() or "Golden files:" in (d or "") for d in docs)


def _has_lint_in_files(s: dict) -> bool:
    files = " ".join(s.get("test_files", []) or [])
    return any(t in files.lower() for t in ("lint", "checker", "diagnost"))


def _has_tui_in_files(s: dict) -> bool:
    files = " ".join(s.get("test_files", []) or [])
    return any(t in files.lower() for t in ("test_tui_", "test_interactive", "test_screen"))


def _has_screen_golden(s: dict) -> bool:
    docs = " ".join(s.get("docstring_samples", []) or [])
    return any(t in docs for t in ("screen", "snapshot", ".golden -- ", "title_", "state_"))


def _is_massive_fixture(s: dict) -> bool:
    # ctags-style: massive test count, repeated template docstring
    if s.get("n_tests", 0) < 1500:
        return False
    docs = s.get("docstring_samples", []) or []
    if len(docs) < 4:
        return False
    # Check if docstrings are template-repeated
    norm = [(d or "")[:80] for d in docs]
    return len(set(norm)) <= 2


def classify(s: dict) -> dict[str, Any]:
    """Return {archetype, confidence, reasons} for one task summary."""
    rc_eq = _dist(s, "returncode.eq")
    so_eq = _dist(s, "stdout.eq")
    so_in = _dist(s, "stdout.contains")
    se_eq = _dist(s, "stderr.eq")
    se_in = _dist(s, "stderr.contains")
    oth_eq = _dist(s, "other.eq")
    oth_in = _dist(s, "other.contains")
    oth_tr = _dist(s, "other.truthy")
    oth_gt = _dist(s, "other.gt")
    oth_ge = _dist(s, "other.ge")
    popen = s.get("popen_calls", 0)
    golden_doc = _has_golden_in_docstrings(s)

    reasons: list[str] = []

    # Rule 1: Massive fixture suite (ctags-like)
    if _is_massive_fixture(s):
        return {
            "archetype": "MassiveFixtureSuite",
            "confidence": 0.95,
            "reasons": [f"n_tests={s['n_tests']} + repeated docstring template"],
        }

    # Rule 2: Orchestration-driven (popen-using watcher)
    if popen >= 5:
        return {
            "archetype": "OrchestrationDrivenWatcher",
            "confidence": 0.90,
            "reasons": [f"popen_calls={popen} (>= 5 threshold)"],
        }

    # Rule 3: Numeric tolerance (inequality bounds dominate)
    bound_total = oth_gt + oth_ge + _dist(s, "other.lt") + _dist(s, "other.le")
    if bound_total >= 0.20:
        reasons.append(f"other.gt+ge+lt+le={bound_total:.2f} >= 0.20")
        return {"archetype": "NumericTolerance", "confidence": 0.85, "reasons": reasons}

    # Rule 4: Linter (test files mention lint + diagnostic-style assertions)
    if _has_lint_in_files(s) and (oth_eq >= 0.15 or oth_in >= 0.15):
        reasons.append("test files mention lint/diagnostic + other.eq/contains high")
        return {"archetype": "LinterDiagnostic", "confidence": 0.75, "reasons": reasons}

    # Rule 5: TUI screen snapshot
    # signature: returncode.eq is unusually low + other.* dominates + TUI files OR screen golden refs
    other_total = oth_eq + oth_in + oth_tr
    if rc_eq < 0.15 and other_total >= 0.45 and (_has_tui_in_files(s) or _has_screen_golden(s)):
        reasons.append(f"rc.eq={rc_eq:.2f} low + other.*={other_total:.2f} high + TUI/screen signal")
        return {"archetype": "TuiScreenSnapshot", "confidence": 0.75, "reasons": reasons}

    # Rule 6: ByteExactGolden — stdout.eq significant OR (other.eq high + golden docstring)
    if so_eq >= 0.15:
        reasons.append(f"stdout.eq={so_eq:.2f} >= 0.15")
        conf = 0.85 if golden_doc else 0.75
        return {"archetype": "ByteExactGolden", "confidence": conf, "reasons": reasons}

    if oth_eq >= 0.20 and golden_doc:
        reasons.append(f"other.eq={oth_eq:.2f} + golden in docstrings")
        return {"archetype": "ByteExactGolden", "confidence": 0.75, "reasons": reasons}

    # Rule 7: FilesystemSideEffect — other.truthy/contains dominate (no TUI signal)
    if oth_tr + oth_in >= 0.30 and so_eq < 0.10 and not _has_tui_in_files(s):
        reasons.append(f"other.truthy+contains={oth_tr+oth_in:.2f} >= 0.30, no TUI signal")
        return {"archetype": "FilesystemSideEffect", "confidence": 0.70, "reasons": reasons}

    # Rule 8: ByteExactGolden weak — stdout.eq moderate (0.08-0.15) but golden docstrings
    if so_eq >= 0.08 and golden_doc:
        reasons.append(f"stdout.eq={so_eq:.2f} + golden in docstrings")
        return {"archetype": "ByteExactGolden", "confidence": 0.65, "reasons": reasons}

    # Rule 9: Default — CliSurfaceAndExitCode (most common archetype)
    if rc_eq >= 0.15:
        reasons.append(f"returncode.eq={rc_eq:.2f} >= 0.15 (default CLI)")
        conf = 0.75 if (so_in + se_in) >= 0.10 else 0.60
        return {"archetype": "CliSurfaceAndExitCode", "confidence": conf, "reasons": reasons}

    # Rule 10: Last resort — CLI but low confidence
    reasons.append("no strong signal, defaulting to CLI")
    return {"archetype": "CliSurfaceAndExitCode", "confidence": 0.40, "reasons": reasons}


def main():
    summaries = [json.loads(l) for l in open("distill_out/summaries.jsonl")]
    ground_truth = {}
    for line in open("distill_out/task_archetypes.jsonl"):
        d = json.loads(line)
        ground_truth[d["task_id"]] = d["archetype"]

    correct = 0
    by_archetype = {a: {"correct": 0, "total": 0, "miss": []} for a in CANONICAL_ARCHETYPES}
    confusion = {}

    for s in summaries:
        tid = s["task_id"]
        truth = ground_truth.get(tid)
        if not truth:
            continue
        result = classify(s)
        pred = result["archetype"]
        by_archetype[truth]["total"] += 1
        if pred == truth:
            correct += 1
            by_archetype[truth]["correct"] += 1
        else:
            by_archetype[truth]["miss"].append((tid, pred, result["confidence"]))
            confusion.setdefault((truth, pred), 0)
            confusion[(truth, pred)] += 1

    total = sum(b["total"] for b in by_archetype.values())
    print(f"Overall: {correct}/{total} = {100*correct/total:.1f}%")
    print()
    print(f"{'Archetype':32s} {'correct/total':>15s}  {'acc':>6s}")
    print("-" * 60)
    for a in CANONICAL_ARCHETYPES:
        b = by_archetype[a]
        if b["total"] == 0:
            continue
        acc = 100 * b["correct"] / b["total"]
        print(f"{a:32s} {b['correct']:5d}/{b['total']:<8d} {acc:5.1f}%")

    print()
    print("Confusion (truth -> predicted):")
    for (t, p), n in sorted(confusion.items(), key=lambda x: -x[1]):
        print(f"  {n:3d}: {t} -> {p}")

    print()
    print("Misclassifications (showing first 5 per archetype):")
    for a in CANONICAL_ARCHETYPES:
        misses = by_archetype[a]["miss"][:5]
        if not misses:
            continue
        print(f"\n  {a} should-have-been:")
        for tid, pred, conf in misses:
            print(f"    {tid:50s} -> {pred} (conf={conf:.2f})")


if __name__ == "__main__":
    main()
