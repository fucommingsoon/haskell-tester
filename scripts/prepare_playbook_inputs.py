"""For each archetype, build a focused input file:
- list of member tasks + their summaries
- 5 sample test records per task (assertions + invocations + docstring)

Output: distill_out/playbook_inputs/<archetype>.jsonl
Each line is one task with embedded samples.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path


SAMPLES_PER_TASK = 5
MAX_TASKS_PER_ARCHETYPE = 25  # cap for big archetypes (Cli has 88, ByteExact 71)


def main():
    out_dir = Path("distill_out/playbook_inputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = {json.loads(l)["task_id"]: json.loads(l) for l in open("distill_out/summaries.jsonl")}
    assignments = {json.loads(l)["task_id"]: json.loads(l)["archetype"]
                   for l in open("distill_out/task_archetypes.jsonl")}

    # Group tasks by archetype.
    by_arch: dict[str, list[str]] = defaultdict(list)
    for t, a in assignments.items():
        by_arch[a].append(t)

    # Load all test records, group by task.
    recs_by_task: dict[str, list[dict]] = defaultdict(list)
    for line in open("distill_out/features.all.jsonl"):
        r = json.loads(line)
        if not r.get("unparseable"):
            recs_by_task[r["task_id"]].append(r)

    rng = random.Random(42)
    for arch, task_list in by_arch.items():
        rng.shuffle(task_list)
        capped = task_list[:MAX_TASKS_PER_ARCHETYPE]
        out_path = out_dir / f"{arch}.jsonl"
        with out_path.open("w") as fh:
            for tid in capped:
                summary = summaries.get(tid)
                if not summary:
                    continue
                samples = rng.sample(recs_by_task.get(tid, []),
                                     min(SAMPLES_PER_TASK, len(recs_by_task.get(tid, []))))
                # Strip the raw assertion string to save space; keep target/op/expected
                trimmed_samples = []
                for s in samples:
                    trimmed_samples.append({
                        "file": s["test_file"],
                        "name": s["test_name"],
                        "doc": (s.get("docstring") or "")[:200],
                        "invs": [{"args": inv["args"][:5], "kwargs": list(inv["kwargs"])}
                                 for inv in s["invocations"][:2]],
                        "asserts": [{"target": a["target"], "op": a["op"],
                                     "expected": str(a["expected"])[:80]}
                                    for a in s["assertions"][:8]],
                    })
                record = {
                    "task_id": tid,
                    "n_tests": summary["n_tests"],
                    "assertion_distribution": summary["assertion_distribution"],
                    "invocation_patterns": summary["invocation_patterns"],
                    "popen_calls": summary["popen_calls"],
                    "expected_value_samples": summary.get("expected_value_samples", [])[:8],
                    "docstring_samples": summary.get("docstring_samples", [])[:3],
                    "test_samples": trimmed_samples,
                }
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        size_kb = out_path.stat().st_size / 1024
        print(f"  {arch:32s} {len(capped):3d}/{len(task_list):3d} tasks -> {size_kb:5.1f} KB")


if __name__ == "__main__":
    main()
