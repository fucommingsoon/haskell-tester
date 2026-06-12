"""Step 1.5: aggregate per-test features.jsonl into per-task summary (~2 KB each).

Output: one jsonl line per task, suitable for feeding into LLM (step 2/3).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def task_summary(task_id: str, recs: list[dict]) -> dict:
    parsed = [r for r in recs if not r.get("unparseable")]
    n_branches = len(set(r["branch"] for r in recs))
    files = sorted(set(r["test_file"] for r in recs))

    pair_counts = Counter((a["target"], a["op"]) for r in parsed for a in r["assertions"])
    total_asserts = sum(pair_counts.values()) or 1
    pair_dist = {
        f"{t}.{o}": round(c / total_asserts, 3)
        for (t, o), c in pair_counts.most_common(8)
    }

    inv_pat: Counter = Counter()
    popen_calls = 0
    for r in parsed:
        for inv in r["invocations"]:
            if inv["call"] == "popen":
                popen_calls += 1
            has_args = len(inv["args"]) > 0
            has_stdin = any(k in inv["kwargs"] for k in ("stdin", "stdin_data", "input"))
            key = ("args" if has_args else "no-args", "stdin" if has_stdin else "no-stdin")
            inv_pat[key] += 1
    inv_pat_str = {f"{a}/{s}": c for (a, s), c in inv_pat.most_common(5)}

    rng = random.Random(42)
    samples: list[str] = []
    for r in parsed:
        for a in r["assertions"]:
            if a["target"] in ("stdout", "stderr") and isinstance(a["expected"], str) and a["expected"].startswith("b'"):
                samples.append(a["expected"])
    sample_uniq = sorted(set(samples))
    sample_repr = rng.sample(sample_uniq, min(15, len(sample_uniq)))

    docs = [r["docstring"] for r in parsed if r.get("docstring")]
    doc_sample = rng.sample(docs, min(5, len(docs)))

    return {
        "task_id": task_id,
        "n_branches": n_branches,
        "n_tests": len(recs),
        "n_unparseable": len(recs) - len(parsed),
        "popen_calls": popen_calls,
        "test_files": files[:30],  # cap; some tasks have 50+ files
        "n_test_files": len(files),
        "assertion_distribution": pair_dist,
        "invocation_patterns": inv_pat_str,
        "expected_value_samples": sample_repr,
        "docstring_samples": doc_sample,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--features", type=Path, required=True, help="features.all.jsonl from parse_graders")
    p.add_argument("--out", type=Path, required=True, help="output summaries jsonl")
    args = p.parse_args()

    by_task: dict[str, list[dict]] = defaultdict(list)
    for line in args.features.open():
        r = json.loads(line)
        by_task[r["task_id"]].append(r)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sizes: list[int] = []
    with args.out.open("w") as fh:
        for tid in sorted(by_task):
            s = task_summary(tid, by_task[tid])
            line = json.dumps(s, ensure_ascii=False, default=str)
            fh.write(line + "\n")
            sizes.append(len(line))

    print(f"wrote {len(sizes)} summaries to {args.out}")
    print(f"sizes: min={min(sizes)} avg={sum(sizes)//len(sizes)} max={max(sizes)} total={sum(sizes)} bytes")


if __name__ == "__main__":
    main()
