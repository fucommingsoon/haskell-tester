"""Download the full programbench/ProgramBench-Tests dataset (skipping already-cached files)."""
from huggingface_hub import snapshot_download
import sys
import time

REPO_ID = "programbench/ProgramBench-Tests"
REVISION = "main"

start = time.time()
print(f"snapshot_download {REPO_ID}@{REVISION} ...", flush=True)
path = snapshot_download(
    repo_id=REPO_ID,
    repo_type="dataset",
    revision=REVISION,
    max_workers=8,
)
elapsed = time.time() - start
print(f"\nDONE in {elapsed:.0f}s -> {path}", flush=True)
