"""Measure how much of an agent's belief is aligned with grader-tested items.

For a given PB task:
  1. Read features.all.jsonl, filter to this task
  2. Synthesize each test's (invocation, assertion) into a 'grader claim' string
  3. LLM-dedup belief facts vs grader claims
  4. Output: total claims, belief facts, intersection, %aligned

This is EVALUATION only — we never feed grader info to the agent.
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    print("DEEPSEEK_API_KEY not set", file=sys.stderr)
    sys.exit(1)


def synth_claim(test: dict) -> str | None:
    """Build a short claim from one test's invocation + first assertion."""
    invs = test.get("invocations", [])
    asserts = test.get("assertions", [])
    if not asserts:
        return None
    a = asserts[0]
    target = a.get("target", "?")
    op = a.get("op", "?")
    expected = str(a.get("expected", ""))[:80]
    if invs:
        inv = invs[0]
        args = inv.get("args", [])
        kwargs = inv.get("kwargs", [])
        has_stdin = "stdin" in kwargs or "stdin_data" in kwargs or "input" in kwargs
        stdin_tag = " (with stdin)" if has_stdin else ""
        return f"running with args={args}{stdin_tag} → {target} {op} {expected}"
    return f"unknown invocation → {target} {op} {expected}"


def load_grader_claims(task_id: str, max_claims: int = 60) -> list[str]:
    """Pull grader assertions for one task, dedup, return as claim strings."""
    seen = set()
    claims = []
    with open("distill_out/features.all.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("task_id") != task_id:
                continue
            if r.get("unparseable"):
                continue
            c = synth_claim(r)
            if c and c not in seen:
                seen.add(c)
                claims.append(c)
                if len(claims) >= max_claims:
                    break
    return claims


def extract_belief_facts(belief_path: Path) -> list[str]:
    """Use LLM to extract atomic claim strings from belief.md."""
    md = belief_path.read_text()[:12000]
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content":
            "Extract every concrete, verifiable claim from this markdown about a binary. "
            "Each claim should describe ONE testable behavior. Reply with strict JSON: "
            '{"facts": ["claim 1", "claim 2", ...]}\n\n' + md
        }],
        "max_tokens": 3000,
        "temperature": 0.0,
        "stream": False,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    start = content.find("{")
    end = content.rfind("}") + 1
    parsed = json.loads(content[start:end])
    facts = parsed.get("facts", [])
    return [f if isinstance(f, str) else str(f) for f in facts]


def dedup_against_grader(belief_facts: list[str], grader_claims: list[str]) -> set[int]:
    """For each belief fact, decide if it touches a grader-tested behavior."""
    grader_blob = "\n".join(f"- {c}" for c in grader_claims)
    belief_blob = "\n".join(f"[{i}] {f}" for i, f in enumerate(belief_facts))

    prompt = (
        "Given a list of GRADER-TESTED behaviors and a list of agent BELIEF facts, "
        "decide which belief facts TOUCH any grader-tested behavior.\n\n"
        "A belief fact 'touches' a grader behavior if the agent's claim relates to the same "
        "observable surface the grader tests — for example:\n"
        "  - grader tests: 'running with args=[--help] → returncode eq 0'\n"
        "  - belief fact: 'binary accepts --help flag' → TOUCHES (same flag, related claim)\n\n"
        "  - grader tests: 'running with args=[] stdin=[...] → stdout eq b\"1\\n\"'\n"
        "  - belief fact: 'outputs 1 when filter .a on input {\"a\":1}' → TOUCHES (same I/O behavior)\n\n"
        "Bias: count as TOUCHES if there's any reasonable overlap.\n\n"
        "Grader-tested behaviors:\n" + grader_blob + "\n\n"
        "Belief facts (indexed):\n" + belief_blob + "\n\n"
        "Reply with strict JSON: {\"touches\": [<list of belief indices that touch any grader behavior>]}"
    )

    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.0,
        "stream": False,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    start = content.find("{")
    end = content.rfind("}") + 1
    parsed = json.loads(content[start:end])
    return set(parsed.get("touches", []))


def main():
    if len(sys.argv) < 3:
        print("Usage: grader_alignment.py <task_id> <belief.md>", file=sys.stderr)
        sys.exit(1)

    task_id = sys.argv[1]
    belief_path = Path(sys.argv[2])

    print(f"Task: {task_id}")
    print(f"Belief: {belief_path}")
    print()

    print("Loading grader claims from features.all.jsonl...")
    grader_claims = load_grader_claims(task_id)
    print(f"  → {len(grader_claims)} unique grader-tested claims (capped at 60)")

    print("\nExtracting belief facts...")
    belief_facts = extract_belief_facts(belief_path)
    print(f"  → {len(belief_facts)} belief facts")

    print("\nDeduping belief vs grader (LLM)...")
    touches = dedup_against_grader(belief_facts, grader_claims)

    aligned = len(touches)
    pct = 100 * aligned / max(len(belief_facts), 1)
    grader_coverage = 100 * aligned / max(len(grader_claims), 1)

    print()
    print(f"== GRADER-ALIGNMENT REPORT for {task_id} ==")
    print(f"  Grader-tested claims: {len(grader_claims)}")
    print(f"  Belief facts:         {len(belief_facts)}")
    print(f"  Belief touches grader: {aligned}  ({pct:.0f}% of belief)")
    print(f"  Grader coverage:      {grader_coverage:.0f}% of grader's tests touched by belief")

    print(f"\nBelief facts touching grader:")
    for i, f in enumerate(belief_facts):
        if i in touches:
            print(f"  ✓ {f}")

    print(f"\nBelief facts NOT touching grader (potentially low-value):")
    for i, f in enumerate(belief_facts):
        if i not in touches:
            print(f"  ✗ {f}")


if __name__ == "__main__":
    main()
