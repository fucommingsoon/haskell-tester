"""Split summaries.jsonl into N batches for parallel subagent processing."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--summaries", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--n-batches", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    lines = args.summaries.read_text().strip().splitlines()
    rng = random.Random(args.seed)
    rng.shuffle(lines)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(range(args.n_batches)):
        chunk = [l for j, l in enumerate(lines) if j % args.n_batches == b]
        out = args.out_dir / f"batch_{b:02d}.jsonl"
        out.write_text("\n".join(chunk) + "\n")
        print(f"batch_{b:02d}: {len(chunk)} tasks")

    print(f"\n{args.n_batches} batches written to {args.out_dir}")


if __name__ == "__main__":
    main()
