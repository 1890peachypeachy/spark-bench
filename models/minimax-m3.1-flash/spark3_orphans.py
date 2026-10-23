#!/usr/bin/env python3
"""Per-item honest size on spark3: apparent bytes + whether ALL hardlinks live inside
the scanned candidate set (i.e. deleting the item actually frees the bytes).

An item whose files have st_nlink > occurrences-in-scan shares data with a path
outside the set (typically a registered lane), so deleting it frees ~nothing.
"""
import os, sys

ITEMS = [
 # (label, [paths])
 ("kit  GLM53-TP3 (TR3 lane, unregistered)", ["/home/spark3/GLM53-TP3"]),
 ("wts  TR3-4bpw  models/", ["/home/spark3/models/GLM-5.3-Flash-EXL3-TR3-4bpw"]),
 ("wts  TR3-4bpw  HF cache", ["/home/spark3/.cache/huggingface/hub/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw"]),
 ("wts  GLM-5.3-Flash-NVFP4  models/", ["/home/spark3/models/GLM-5.3-Flash-NVFP4"]),
 ("wts  DeepSeek-V4-Flash-Vision-Exp  HF cache", ["/home/spark3/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4-Flash-Vision-Exp"]),
 ("kit  dsv4-vision-tp3 + tp4", ["/home/spark3/dsv4-vision-tp3", "/home/spark3/dsv4-vision-tp4"]),
 ("wts  Qwen3.8-Flash-Next-NVFP4  HF cache", ["/home/spark3/.cache/huggingface/hub/models--Mia-AiLab--Qwen3.8-Flash-Next-NVFP4"]),
 ("wts  Step-5-Preview-Spark  export", ["/var/tmp/models/Step-5-Preview-Spark"]),
 ("tmp  tensorfold-spill", ["/var/tmp/tensorfold-spill"]),
 ("svc  qwen3-tts sidecar", ["/home/spark3/qwen3-tts"]),
 ("svc  ollama (minicpm-v)", ["/home/spark3/.ollama"]),
 ("exp  qwen38 / laguna / quanttrio / glm52 / bilikaz / topkfix",
   ["/home/spark3/qwen38-crash-logs", "/home/spark3/qwen38-drowzeys-256k-hermes-20260814-170324",
    "/home/spark3/laguna-s-2.1-nvfp4-sm121-vllm", "/home/spark3/quanttrio-exact-hybrid",
    "/home/spark3/quanttrio-exact-hybrid-20260810-220825", "/home/spark3/glm52-r9",
    "/home/spark3/glm52-r9-300k-20260802T061237m0700", "/home/spark3/bilikaz-qwen38-cluster",
    "/home/spark3/bilikaz-qwen38-cluster.bak-20260908T092215", "/home/spark3/glm53-topkfix",
    "/home/spark3/q27b-recipe", "/home/spark3/qfn-single-recipe",
    "/home/spark3/dspark-mia-ambitious"]),
 ("bak  stray launcher scripts + baks (~)", ["/home/spark3"]),   # handled separately below
]

seen = {}   # (dev,ino) -> [bytes, occurrences]

def scan(paths):
    out = []
    for root in paths:
        if not os.path.exists(root):
            continue
        for dp, dn, fns in os.walk(root, onerror=lambda e: None):
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    st = os.stat(p)          # follow symlinks: HF snapshots are symlinks
                except OSError:
                    continue
                out.append(((st.st_dev, st.st_ino), st.st_blocks * 512, st.st_nlink, p))
    return out

# pass 1: the "~ stray scripts" item must only count loose files at depth 1
results = []
all_rows = []
for label, paths in ITEMS:
    if label.startswith("bak"):
        rows = []
        for fn in sorted(os.listdir("/home/spark3")):
            p = os.path.join("/home/spark3", fn)
            if os.path.isfile(p) and (fn.endswith(".sh") or ".bak" in fn or fn.endswith(".log")):
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                rows.append(((st.st_dev, st.st_ino), st.st_blocks * 512, st.st_nlink, p))
    else:
        rows = scan(paths)
    all_rows.append((label, rows))
    for key, sz, nl, p in rows:
        rec = seen.setdefault(key, [0, 0])
        rec[0] = sz
        rec[1] += 1

G = 1024**3
print(f"{'item':52s} {'apparent GB':>11s} {'freeable GB':>11s}  note")
for label, rows in all_rows:
    app = sum(sz for _, sz, _, _ in rows)
    freeable = 0
    for key, sz, nl, p in rows:
        if seen[key][1] >= nl:      # every hardlink to this inode is inside our set
            freeable += sz // max(1, seen[key][1])
    note = "" if abs(freeable - app) / G < 0.5 else "shares data with a kept path"
    print(f"{label:52s} {app/G:11.1f} {freeable/G:11.1f}  {note}")