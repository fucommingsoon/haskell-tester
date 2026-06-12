"""Spot-check archetype assignments by sampling real test records.

For each picked task, print:
- assigned archetype + expected pattern
- 10 sampled (test_name, invocations, assertions, docstring)
- so user can eyeball whether the assignment is name-and-substance consistent.
"""
import json
import random
from pathlib import Path


# 5 representative tasks (one per major archetype, plus the tiny ones).
PICKS = [
    ("ariga__atlas.6d81150",      "CliSurfaceAndExitCode"),
    ("anordal__shellharden.6a6ffd4", "ByteExactGolden"),
    ("unhappychoice__gittype.34b72d0", "TuiScreenSnapshot"),
    ("eradman__entr.8e2e8b4",     "OrchestrationDrivenWatcher"),
    ("svenstaro__genact.16f96e3", "NumericTolerance"),
]

EXPECTED = {
    "CliSurfaceAndExitCode": "returncode.eq leads + stdout/stderr.contains on flag/help/error tokens, args/no-stdin dominant",
    "ByteExactGolden":       "stdout.eq / other.eq dominates, expected literals = code snippets/full bytes, golden file mentions in docstrings",
    "TuiScreenSnapshot":     "other.contains/truthy on screen state, expected literals mostly empty, golden screen file refs in docstrings",
    "OrchestrationDrivenWatcher": "popen calls > 0, multi-step orchestration (start watcher, mutate file, wait)",
    "NumericTolerance":      "other.gt/ge/le bounds dominate, expected literals are numeric values, no byte-exact",
}

def main():
    rng = random.Random(42)
    recs_by_task: dict[str, list[dict]] = {}
    for line in open("distill_out/features.all.jsonl"):
        r = json.loads(line)
        if r.get("unparseable"):
            continue
        recs_by_task.setdefault(r["task_id"], []).append(r)

    for tid, expected_arch in PICKS:
        print("=" * 80)
        print(f"TASK:     {tid}")
        print(f"ARCHETYPE: {expected_arch}")
        print(f"EXPECTED:  {EXPECTED[expected_arch]}")
        print("-" * 80)
        recs = recs_by_task.get(tid, [])
        if not recs:
            print("  NO RECORDS")
            continue
        # Sample 10 randomly to avoid bias
        sample = rng.sample(recs, min(10, len(recs)))
        for i, r in enumerate(sample, 1):
            print(f"\n  [{i}] {r['test_file']}::{r['test_name']}")
            if r.get("docstring"):
                doc = r["docstring"].replace("\n", " ")[:120]
                print(f"      doc:   {doc}")
            if r["invocations"]:
                for inv in r["invocations"][:2]:
                    print(f"      call:  {inv['call']}(args={inv['args']}, kwargs={list(inv['kwargs'])})")
            asserts = r["assertions"][:5]
            for a in asserts:
                exp = str(a["expected"])[:60]
                print(f"      assert {a['target']:10s} {a['op']:13s} {exp}")
            if len(r["assertions"]) > 5:
                print(f"      ... ({len(r['assertions']) - 5} more asserts)")
        print()


if __name__ == "__main__":
    main()
