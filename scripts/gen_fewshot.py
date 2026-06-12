"""Pick 2 representative tasks per archetype as few-shot examples for LLM classifier.

Strips task_id (so it's an abstract pattern, not a lookup) and keeps only the
signals that matter for classification.

Output: data/fewshot_examples.json (read at startup by Classifier/LLM.hs)
"""
import json
from collections import defaultdict
from pathlib import Path

K_PER_ARCHETYPE = 2

summaries = {json.loads(l)["task_id"]: json.loads(l)
             for l in open("distill_out/summaries.jsonl")}
assignments = {json.loads(l)["task_id"]: json.loads(l)["archetype"]
               for l in open("distill_out/task_archetypes.jsonl")}

by_arch = defaultdict(list)
for tid, arch in assignments.items():
    by_arch[arch].append(tid)


def score(s, arch):
    """Higher = more prototypical. Use the single strongest signal of the archetype."""
    d = s["assertion_distribution"]
    if arch == "ByteExactGolden":
        return d.get("stdout.eq", 0) + d.get("other.eq", 0)
    if arch == "CliSurfaceAndExitCode":
        return d.get("returncode.eq", 0) + d.get("stdout.contains", 0) + d.get("stderr.contains", 0)
    if arch == "FilesystemSideEffect":
        return d.get("other.truthy", 0) + d.get("other.contains", 0)
    if arch == "TuiScreenSnapshot":
        return -d.get("returncode.eq", 0) + d.get("other.truthy", 0)
    if arch == "LinterDiagnostic":
        return d.get("other.eq", 0) + d.get("other.contains", 0)
    if arch == "NumericTolerance":
        return d.get("other.gt", 0) + d.get("other.ge", 0) + d.get("other.lt", 0) + d.get("other.le", 0)
    if arch == "OrchestrationDrivenWatcher":
        return s.get("popen_calls", 0)
    if arch == "MassiveFixtureSuite":
        return s.get("n_tests", 0)
    return 0


# Pick top-K per archetype, strip task_id.
out = {}
fewshot_tids = []
for arch, tids in by_arch.items():
    sorted_tids = sorted(tids, key=lambda t: -score(summaries[t], arch))
    picks = []
    for tid in sorted_tids[:K_PER_ARCHETYPE]:
        fewshot_tids.append(tid)
        s = summaries[tid]
        picks.append({
            "n_tests": s["n_tests"],
            "popen_calls": s.get("popen_calls", 0),
            "assertion_distribution": s["assertion_distribution"],
            "expected_value_samples": (s.get("expected_value_samples") or [])[:6],
            "docstring_samples": [(d or "")[:200] for d in (s.get("docstring_samples") or [])[:2]],
            "test_files": (s.get("test_files") or [])[:6],
        })
    out[arch] = picks

# Write the task_id list used as few-shot — eval scripts use this to exclude them.
Path("distill_out/fewshot_task_ids.json").write_text(json.dumps(sorted(fewshot_tids), indent=2))
print(f"recorded {len(fewshot_tids)} few-shot task ids to distill_out/fewshot_task_ids.json")

Path("data").mkdir(exist_ok=True)
out_path = Path("data/fewshot_examples.json")
out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

# Print summary
total_bytes = out_path.stat().st_size
print(f"wrote {len(out)} archetypes x {K_PER_ARCHETYPE} examples each to {out_path}")
print(f"size: {total_bytes} bytes ({total_bytes/1024:.1f} KB)")
