#!/usr/bin/env python3
"""Download ONE shard-list of MiniMaxAI/MiniMax-M3.1-Flash on this node.

Split-download technique (fleet-bulk-transfers skill): each node pulls only its
slice of the repo in parallel, then the helpers fan their slice to the landing
node over the CX7 fabric (10.73.0.2). Resumable via hf_hub .incomplete blobs.

usage: m31_download.py <node-tag> <dest-dir> <list.json> <state-dir>
"""
import json, os, sys, time

from huggingface_hub import snapshot_download

REPO = "MiniMaxAI/MiniMax-M3.1-Flash"
REV = "9e7ebacac350497ad4a1272a2e817639bf11561c"

node, dest, listfile, state = sys.argv[1:5]
patterns = json.load(open(listfile))
os.makedirs(dest, exist_ok=True)
os.makedirs(state, exist_ok=True)
marker = os.path.join(state, f"HALF_DONE_{node}")

token = None
tok = os.path.expanduser("~/.cache/huggingface/token")
if os.path.exists(tok):
    token = open(tok).read().strip() or None

t0 = time.time()
print(f"[{node}] start {len(patterns)} files -> {dest}", flush=True)
snapshot_download(
    repo_id=REPO,
    revision=REV,
    local_dir=dest,
    allow_patterns=patterns,
    max_workers=8,
    token=token,
)

missing = [p for p in patterns if not os.path.exists(os.path.join(dest, p))]
if missing:
    print(f"[{node}] FAILED {len(missing)} missing: {missing[:5]}", flush=True)
    sys.exit(1)

open(marker, "w").write(f"{node} {len(patterns)} files {time.time()-t0:.0f}s\n")
print(f"[{node}] HALF_DONE {len(patterns)} files in {time.time()-t0:.0f}s", flush=True)