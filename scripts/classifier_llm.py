"""Hybrid classifier: rule fast-path + LLM fallback.

Flow:
  rule classifier returns (archetype, confidence)
  if confidence >= HIGH_CONF_THRESHOLD: trust it
  else: send to LLM with archetype definitions + 2 few-shot examples per archetype

LLM uses Anthropic Sonnet 4 by default. Requires ANTHROPIC_API_KEY env var.

Usage:
  python3 scripts/classifier_llm.py                  # validate on full 199-task ground truth
  python3 scripts/classifier_llm.py --task <id>      # classify one task
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from classifier import classify as rule_classify, CANONICAL_ARCHETYPES

HIGH_CONF_THRESHOLD = 0.85
MODEL = os.getenv("CLASSIFIER_MODEL", "claude-sonnet-4-6")


ARCHETYPE_DEFS = {
    "ByteExactGolden": "stdout.eq or other.eq dominates; tests compare full bytes against golden fixtures; docstrings cite 'Golden files' / 'EXPECT' / 'byte-for-byte'.",
    "CliSurfaceAndExitCode": "returncode.eq leads + stdout/stderr.contains on help/usage/flag tokens; binary judged by exit semantics + diagnostic substrings, not byte output.",
    "FilesystemSideEffect": "other.truthy/contains/eq on file artifacts; grader inspects produced filesystem state rather than stdout.",
    "TuiScreenSnapshot": "Interactive TUI; assertions check captured screen state via 'other' + golden screens; returncode.eq is unusually low.",
    "LinterDiagnostic": "Static analyzer / linter; assertions check that specific diagnostic codes/messages fire on prepared inputs; expected literals are rule IDs.",
    "NumericTolerance": "other.gt/ge/lt/le bounds dominate; non-deterministic or numeric output validated by inequalities.",
    "OrchestrationDrivenWatcher": "Tool needs multi-step orchestration via popen + sleep + file/state mutation; popen_calls > 0.",
    "MassiveFixtureSuite": "Single task overwhelms with thousands of parameterized fixture tests sharing a template docstring.",
}


def pick_few_shot(ground_truth: dict[str, str], summaries: dict[str, dict], k_per_arch: int = 2) -> dict[str, list[dict]]:
    """For each archetype, pick k representative task summaries as few-shot examples."""
    rng = random.Random(42)
    by_arch: dict[str, list[str]] = {}
    for tid, arch in ground_truth.items():
        by_arch.setdefault(arch, []).append(tid)

    examples = {}
    for arch, tids in by_arch.items():
        rng.shuffle(tids)
        picked = tids[:k_per_arch]
        examples[arch] = [summaries[t] for t in picked if t in summaries]
    return examples


def trim_summary_for_prompt(s: dict) -> dict:
    """Reduce summary to essential fields for LLM prompt."""
    return {
        "task_id": s.get("task_id"),
        "n_branches": s.get("n_branches"),
        "n_tests": s.get("n_tests"),
        "popen_calls": s.get("popen_calls"),
        "assertion_distribution": s.get("assertion_distribution"),
        "invocation_patterns": s.get("invocation_patterns"),
        "expected_value_samples": (s.get("expected_value_samples") or [])[:10],
        "docstring_samples": (s.get("docstring_samples") or [])[:3],
        "test_files": (s.get("test_files") or [])[:8],
    }


def build_prompt(target: dict, few_shot: dict[str, list[dict]]) -> str:
    lines = ["You are classifying ProgramBench grader task summaries into 8 canonical archetypes.",
             "",
             "ARCHETYPE DEFINITIONS:"]
    for name, desc in ARCHETYPE_DEFS.items():
        lines.append(f"- {name}: {desc}")
    lines.append("")
    lines.append("FEW-SHOT EXAMPLES:")
    for arch, examples in few_shot.items():
        for ex in examples[:1]:
            lines.append(f"\nArchetype: {arch}")
            lines.append("Summary: " + json.dumps(trim_summary_for_prompt(ex), ensure_ascii=False))
    lines.append("")
    lines.append("=" * 40)
    lines.append("CLASSIFY THIS:")
    lines.append("Summary: " + json.dumps(trim_summary_for_prompt(target), ensure_ascii=False))
    lines.append("")
    lines.append("Pick exactly ONE archetype name from the 8 listed. Reply with strict JSON:")
    lines.append('{"archetype": "<name>", "reason": "<one short sentence>"}')
    return "\n".join(lines)


def llm_classify(target: dict, few_shot: dict[str, list[dict]], client) -> dict:
    """Call LLM. Returns {archetype, confidence, reasons}."""
    prompt = build_prompt(target, few_shot)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    # Extract JSON
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        obj = json.loads(text[start:end])
        return {
            "archetype": obj.get("archetype", "CliSurfaceAndExitCode"),
            "confidence": 0.85,
            "reasons": ["LLM: " + obj.get("reason", "")],
        }
    except Exception as e:
        return {
            "archetype": "CliSurfaceAndExitCode",
            "confidence": 0.40,
            "reasons": [f"LLM parse failed: {e}", f"raw: {text[:100]}"],
        }


def hybrid_classify(summary: dict, few_shot: dict[str, list[dict]], client) -> dict:
    """Rule first, LLM if confidence < HIGH_CONF_THRESHOLD."""
    rule_result = rule_classify(summary)
    if rule_result["confidence"] >= HIGH_CONF_THRESHOLD:
        rule_result["source"] = "rule"
        return rule_result
    llm_result = llm_classify(summary, few_shot, client)
    llm_result["source"] = "llm"
    llm_result["rule_predicted"] = rule_result["archetype"]
    return llm_result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", help="single task_id to classify")
    p.add_argument("--limit", type=int, default=0, help="validate only first N for cost control")
    p.add_argument("--summaries", default="distill_out/summaries.jsonl")
    p.add_argument("--ground-truth", default="distill_out/task_archetypes.jsonl")
    args = p.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Set it then re-run.", file=sys.stderr)
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic SDK not installed. Try: uv run --with anthropic python scripts/classifier_llm.py", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    summaries = {json.loads(l)["task_id"]: json.loads(l) for l in open(args.summaries)}
    ground_truth = {json.loads(l)["task_id"]: json.loads(l)["archetype"] for l in open(args.ground_truth)}
    few_shot = pick_few_shot(ground_truth, summaries, k_per_arch=2)

    if args.task:
        s = summaries.get(args.task)
        if not s:
            print(f"task not found: {args.task}", file=sys.stderr)
            sys.exit(1)
        result = hybrid_classify(s, few_shot, client)
        truth = ground_truth.get(args.task, "?")
        print(json.dumps({"task": args.task, "truth": truth, **result}, indent=2, ensure_ascii=False))
        return

    # Full validation
    tasks = list(summaries.keys())
    # Exclude few-shot examples from validation
    few_shot_ids = {ex["task_id"] for arch_list in few_shot.values() for ex in arch_list}
    tasks = [t for t in tasks if t not in few_shot_ids]
    if args.limit:
        tasks = tasks[:args.limit]

    correct_rule = 0; correct_llm = 0
    total_rule = 0; total_llm = 0
    confusion = {}

    for i, tid in enumerate(tasks, 1):
        s = summaries[tid]
        truth = ground_truth.get(tid)
        if not truth:
            continue
        t0 = time.time()
        result = hybrid_classify(s, few_shot, client)
        elapsed = time.time() - t0
        correct = result["archetype"] == truth
        if result["source"] == "rule":
            total_rule += 1
            correct_rule += int(correct)
        else:
            total_llm += 1
            correct_llm += int(correct)
        if not correct:
            confusion.setdefault((truth, result["archetype"]), 0)
            confusion[(truth, result["archetype"])] += 1
        marker = "✓" if correct else "✗"
        print(f"[{i:3d}/{len(tasks)}] {marker} {result['source']:4s} {tid[:50]:50s} -> {result['archetype']:30s} (truth={truth}, {elapsed:.1f}s)")

    total = total_rule + total_llm
    correct = correct_rule + correct_llm
    print()
    print(f"Overall: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  rule fast-path: {correct_rule}/{total_rule} = {100*correct_rule/max(total_rule,1):.1f}%")
    print(f"  llm fallback:   {correct_llm}/{total_llm} = {100*correct_llm/max(total_llm,1):.1f}%")
    print()
    print("Confusion (truth -> predicted):")
    for (t, p), n in sorted(confusion.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:3d}: {t} -> {p}")


if __name__ == "__main__":
    main()
