"""Compare information density between original README.md and agent-produced belief.md.

For each markdown:
  1. LLM extracts atomic facts about the binary
  2. Count: total facts + actionable/behavioral facts

Output: density gain ratio + per-facet breakdown.
Uses DEEPSEEK_API_KEY env var (same as the Haskell agent).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    print("DEEPSEEK_API_KEY not set", file=sys.stderr)
    sys.exit(1)

EXTRACT_PROMPT = """\
Extract every ATOMIC, VERIFIABLE fact about the binary from the markdown below.

Rules for what counts as an atomic fact:
- Each fact is ONE concrete claim: "binary accepts --help", "exit code is 0 on success", "outputs JSON to stdout"
- Skip marketing / promotional / cross-reference content ("see online docs", "try it online")
- Skip historical/licensing/contributor content
- Group facts by category: cli_flags, io_model, exit_codes, error_grammar, behavior, identity, other

Reply with strict JSON only:
{
  "facts": [
    {"category": "<category>", "claim": "<one short claim>"},
    ...
  ]
}

Markdown:
---
"""


def extract(md_path: Path, retry: int = 2) -> list[dict]:
    md = md_path.read_text()[:12000]  # cap large READMEs / beliefs
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": EXTRACT_PROMPT + md
                      + "\n\nIMPORTANT: produce VALID JSON. Close all brackets and commas."}],
        "max_tokens": 4000,
        "temperature": 0.0,
        "stream": False,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    last_err = None
    for attempt in range(retry + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            # Strip code fences
            start = content.find("{")
            end = content.rfind("}") + 1
            parsed = json.loads(content[start:end])
            return parsed.get("facts", [])
        except json.JSONDecodeError as e:
            last_err = e
            print(f"  retry {attempt + 1}/{retry + 1} after JSON parse error: {e}", file=sys.stderr)
    print(f"  EXTRACT FAILED after {retry + 1} attempts: {last_err}", file=sys.stderr)
    return []


def summarize(name: str, facts: list[dict]) -> dict:
    by_cat = {}
    for f in facts:
        by_cat.setdefault(f["category"], []).append(f["claim"])
    return {"source": name, "total": len(facts), "by_category": by_cat}


def main():
    if len(sys.argv) < 3:
        print("Usage: info_density.py <readme.md> <belief.md>", file=sys.stderr)
        sys.exit(1)

    readme_path = Path(sys.argv[1])
    belief_path = Path(sys.argv[2])

    print(f"Extracting facts from {readme_path.name}...")
    readme_facts = extract(readme_path)
    print(f"  → {len(readme_facts)} facts")

    print(f"Extracting facts from {belief_path.name}...")
    belief_facts = extract(belief_path)
    print(f"  → {len(belief_facts)} facts")

    print()
    print("=" * 60)

    readme_sum = summarize("README.md", readme_facts)
    belief_sum = summarize("belief.md", belief_facts)

    print(f"\n{readme_sum['source']:>12s}  {readme_sum['total']:>3d} facts")
    for cat, claims in sorted(readme_sum["by_category"].items()):
        print(f"    {cat:18s} {len(claims)}")
        for c in claims[:3]:
            print(f"      - {c}")

    print(f"\n{belief_sum['source']:>12s}  {belief_sum['total']:>3d} facts")
    for cat, claims in sorted(belief_sum["by_category"].items()):
        print(f"    {cat:18s} {len(claims)}")
        for c in claims[:3]:
            print(f"      - {c}")

    ratio = belief_sum["total"] / max(readme_sum["total"], 1)
    print()
    print(f"Total density: belief / README = {belief_sum['total']}/{readme_sum['total']} = {ratio:.2f}x")

    # === net_new computation (the real metric) ===
    # Use LLM to do semantic dedup: given (belief_fact, [readme_facts]),
    # determine if belief_fact already covered.
    print()
    print("Computing net_new (semantic dedup, this may take ~30s)...")
    net_new_facts, overlap_facts = compute_net_new(belief_facts, readme_facts)

    print()
    print(f"Belief total facts:   {belief_sum['total']}")
    print(f"  - overlapping with README:  {len(overlap_facts)}")
    print(f"  - NET NEW (not in README):  {len(net_new_facts)}")
    if belief_sum['total']:
        print(f"  net_new ratio: {len(net_new_facts) / belief_sum['total'] * 100:.0f}% of belief is genuinely new")

    print()
    print("== NET NEW facts (belief reveals what README hides) ==")
    for cat in sorted(set(f["category"] for f in net_new_facts)):
        cat_facts = [f for f in net_new_facts if f["category"] == cat]
        print(f"\n  {cat} ({len(cat_facts)} new):")
        for f in cat_facts[:5]:
            print(f"    + {f['claim']}")
        if len(cat_facts) > 5:
            print(f"    ... ({len(cat_facts) - 5} more)")

    print()
    print("== OVERLAP (belief just repeats README) ==")
    for f in overlap_facts[:5]:
        print(f"  ~ {f['claim']}")
    if len(overlap_facts) > 5:
        print(f"  ... ({len(overlap_facts) - 5} more)")


def compute_net_new(belief_facts: list[dict], readme_facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Use LLM to do semantic dedup. Returns (net_new, overlap) lists."""
    readme_blob = "\n".join(f"- {f['claim']}" for f in readme_facts)
    belief_blob = "\n".join(f"[{i}] {f['claim']}" for i, f in enumerate(belief_facts))

    prompt = (
        "Given a list of facts from a README and a list of facts from an agent-produced belief,\n"
        "decide for EACH belief fact whether it is GENUINELY covered by the README facts.\n\n"
        "STRICT CRITERIA — a belief fact is 'covered' ONLY IF:\n"
        "  - The README fact asserts the EXACT SAME specific claim, not just an abstract category.\n"
        "  - An ABSTRACT README claim like 'tool transforms JSON' does NOT cover a SPECIFIC belief\n"
        "    claim like 'binary outputs 1 on input {\"a\":1} with filter .a' — these are different\n"
        "    levels of detail and the specific fact should count as NEW.\n"
        "  - A specific README claim (e.g. 'accepts --json flag') covers a belief claim that\n"
        "    repeats it.\n\n"
        "Bias: when in doubt, mark NOT covered. We are measuring genuinely new operational facts.\n\n"
        "README facts:\n" + readme_blob + "\n\n"
        "Belief facts (indexed):\n" + belief_blob + "\n\n"
        "Reply with strict JSON: {\"covered\": [<list of indices that ARE strictly covered>]}"
    )

    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
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
    covered_idx = set(parsed.get("covered", []))

    overlap = [f for i, f in enumerate(belief_facts) if i in covered_idx]
    net_new = [f for i, f in enumerate(belief_facts) if i not in covered_idx]
    return net_new, overlap


if __name__ == "__main__":
    main()
