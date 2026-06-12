"""Batch run htester agent on PB tasks where we have a matching system binary.
Output: per-task density gain table.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

BIN_TO_TASK = {
    "/usr/bin/jq":             "jqlang__jq.b33a763",
    "/opt/homebrew/bin/rg":    "burntsushi__ripgrep.3b7fd44",
    "/opt/homebrew/bin/yq":    "mikefarah__yq.602586d",
    "/opt/homebrew/bin/gron":  "tomnomnom__gron.88a6234",
    "/opt/homebrew/bin/fd":    "sharkdp__fd.40d8eb3",
}

HF_ROOT = Path("/Users/kangxin/.cache/huggingface/hub/datasets--programbench--ProgramBench-Tests/"
               "snapshots/de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5")
PROJECT_ROOT = Path("/Users/kangxin/Documents/workspace/konceptosv18/haskell-tester")
HTESTER = PROJECT_ROOT / "dist-newstyle/build/aarch64-osx/ghc-9.6.7/haskell-tester-0.1.0.0/x/htester/build/htester/htester"


def load_truth():
    out = {}
    for line in (PROJECT_ROOT / "distill_out/task_archetypes.jsonl").read_text().splitlines():
        d = json.loads(line)
        out[d["task_id"]] = d["archetype"]
    return out


README_EXT_PRIORITY = (".md", ".mkd", ".markdown", ".rst", ".adoc", ".txt", ".org", "")


def find_readme_member(tar) -> str | None:
    """Find best readme file in tarball. Case-insensitive prefix match on 'readme'.
    Prefer .md > .mkd > .markdown > ... > no extension."""
    candidates = []
    for member in tar.getmembers():
        stem = member.name.split("/")[-1]
        low = stem.lower()
        if low.startswith("readme"):
            # Skip obvious non-text artifacts: screenshots, .png/.gif/.jsonl/.golden
            if any(low.endswith(e) for e in (".png", ".jpg", ".gif", ".jsonl", ".golden", ".js")):
                continue
            # Score by extension preference (lower score = better)
            score = len(README_EXT_PRIORITY)
            for i, ext in enumerate(README_EXT_PRIORITY):
                if low.endswith(ext) and (ext or "." not in stem[len("readme"):]):
                    score = i
                    break
            candidates.append((score, member.name))
    if not candidates:
        return None
    return min(candidates)[1]


def setup_test_dir(task_id: str, system_bin: str, work_dir: Path) -> bool:
    """Extract tarball + symlink binary. Returns True if any README variant found."""
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    tarballs = list((HF_ROOT / task_id / "tests").glob("*.tar.gz"))
    if not tarballs:
        return False

    with tarfile.open(tarballs[0]) as tf:
        chosen = find_readme_member(tf)
        if chosen:
            tf.extract(chosen, work_dir)
            extracted = work_dir / chosen
            target = work_dir / "README.md"
            if extracted.exists() and extracted != target:
                extracted.rename(target)

    if not (work_dir / "README.md").exists():
        print(f"  WARN: no readme found in tarball for {task_id}")
        return False

    os.symlink(system_bin, work_dir / "executable")
    return True


def run_agent(work_dir: Path) -> dict:
    """Run htester agent, return parsed stats."""
    result = subprocess.run(
        [str(HTESTER), "agent", str(work_dir)],
        capture_output=True, text=True, timeout=300
    )
    out = result.stdout
    archetype_m   = re.search(r"^Archetype:\s+(\S+)", out, re.MULTILINE)
    confidence_m  = re.search(r"^Confidence:\s+([\d.]+)", out, re.MULTILINE)
    rounds_m      = re.search(r"^Rounds run:\s+(\d+)", out, re.MULTILINE)
    probes_m      = re.search(r"^Probes executed:\s+(\d+)", out, re.MULTILINE)
    return {
        "archetype":  archetype_m.group(1) if archetype_m else "?",
        "confidence": float(confidence_m.group(1)) if confidence_m else 0,
        "rounds":     int(rounds_m.group(1)) if rounds_m else 0,
        "probes":     int(probes_m.group(1)) if probes_m else 0,
        "stderr":     result.stderr[-300:] if result.returncode else "",
    }


def run_density(work_dir: Path) -> dict | None:
    """Run info_density.py, parse the final ratio + per-cat counts."""
    result = subprocess.run(
        ["/opt/homebrew/bin/python3", str(PROJECT_ROOT / "scripts/info_density.py"),
         str(work_dir / "README.md"), str(work_dir / "belief.md")],
        capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT
    )
    if result.returncode != 0:
        return None
    text = result.stdout
    ratio_m  = re.search(r"= (\d+)/(\d+) = ([\d.]+)x", text)
    if not ratio_m:
        return None
    # parse net_new from new section "NET NEW (not in README):  <N>"
    netnew_m = re.search(r"NET NEW \(not in README\):\s+(\d+)", text)
    overlap_m = re.search(r"overlapping with README:\s+(\d+)", text)
    return {
        "belief_facts": int(ratio_m.group(1)),
        "readme_facts": int(ratio_m.group(2)),
        "ratio":        float(ratio_m.group(3)),
        "net_new":      int(netnew_m.group(1)) if netnew_m else 0,
        "overlap":      int(overlap_m.group(1)) if overlap_m else 0,
    }


def main():
    truth = load_truth()
    rows = []

    for system_bin, task_id in BIN_TO_TASK.items():
        short = task_id.split("__")[-1].split(".")[0]
        print(f"\n=== {short} (bin={system_bin}) ===")
        work_dir = Path(f"/tmp/pb_batch_{short}")

        if not setup_test_dir(task_id, system_bin, work_dir):
            print(f"  SKIP: no README in tarball")
            continue

        agent = run_agent(work_dir)
        if agent.get("stderr"):
            print(f"  agent stderr: {agent['stderr']}")
        print(f"  archetype  = {agent['archetype']} (truth={truth.get(task_id, '?')})  "
              f"conf={agent['confidence']:.2f}  rounds={agent['rounds']}  probes={agent['probes']}")

        density = run_density(work_dir)
        if density:
            print(f"  density    = {density['belief_facts']}/{density['readme_facts']} = {density['ratio']:.2f}x")
            rows.append({
                "task":       short,
                "truth":      truth.get(task_id, "?"),
                "predicted":  agent["archetype"],
                "match":      truth.get(task_id) == agent["archetype"],
                "rounds":     agent["rounds"],
                "probes":     agent["probes"],
                "readme":     density["readme_facts"],
                "belief":     density["belief_facts"],
                "net_new":    density["net_new"],
                "overlap":    density["overlap"],
                "ratio":      density["ratio"],
            })

    if not rows:
        print("\nno successful runs")
        return

    print("\n\n=== SUMMARY ===")
    print(f"{'task':10s} {'truth':22s} {'predicted':22s} {'OK':3s} "
          f"{'rounds':>6s} {'README':>6s} {'belief':>6s} {'overlap':>7s} {'NEW':>4s} {'NEW%':>5s}")
    print("-" * 110)
    for r in rows:
        mark = "✓" if r["match"] else "✗"
        new_pct = 100 * r["net_new"] / max(r["belief"], 1)
        print(f"{r['task']:10s} {r['truth']:22s} {r['predicted']:22s} {mark:3s} "
              f"{r['rounds']:6d} {r['readme']:6d} {r['belief']:6d} {r['overlap']:7d} {r['net_new']:4d} {new_pct:4.0f}%")
    avg_new = sum(r["net_new"] for r in rows) / len(rows)
    avg_pct = sum(100 * r["net_new"] / max(r["belief"], 1) for r in rows) / len(rows)
    print(f"\navg NET_NEW: {avg_new:.1f} facts  ({avg_pct:.0f}% of belief)")
    correct = sum(1 for r in rows if r["match"])
    print(f"classification: {correct}/{len(rows)} correct")


if __name__ == "__main__":
    main()
