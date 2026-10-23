#!/usr/bin/env python3
"""Honest reclaimable-bytes computation for spark3.

freeable(tree) = sum over unique inodes in tree of size, but ONLY if every hardlink
to that inode lives inside the candidate trees (no link into a KEEP path). That is
what makes a deletion actually return bytes to the disk.

usage: spark3_reclaim.py [--json]
"""
import json, os, sys

KEEP = [
 "/var/tmp/models",                    # NFS export root served to workers
 "/home/spark3/.cache/huggingface",    # hardlink partner + dense/kernel assets
 "/home/spark3/GLM53-TF",              # glm53-tf2 kit
 "/home/spark3/GLM53-TF3",             # glm53-tp3 kit
 "/home/spark3/GLM53-TP3",             # TR3 kit (candidate lane, see report)
 "/var/tmp/glm53-tf4-trial",           # glm53-tp4 kit
 "/var/tmp/glm53-recipe-tp4",          # glm53-vllm4 kit
 "/home/spark3/dsv41-4x",              # live lane kit
 "/home/spark3/dsv41-3x",
 "/home/spark3/dsv41-engram-1017",     # live lane engram state
 "/home/spark3/dsv41-engram",
]

CAND = [
 ("DeepSeek-V4-Flash-Vision-Exp weights (HF cache)", "/home/spark3/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4-Flash-Vision-Exp"),
 ("GLM-5.3-Flash-NVFP4 weights (models/)", "/home/spark3/models/GLM-5.3-Flash-NVFP4"),
 ("GLM-5.3-Flash-EXL3-TR3-4bpw (models/)", "/home/spark3/models/GLM-5.3-Flash-EXL3-TR3-4bpw"),
 ("GLM-5.3-Flash-EXL3-TR3-4bpw (HF cache)", "/home/spark3/.cache/huggingface/hub/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw"),
 ("Step-5-Preview-Spark weights (export subdir)", "/var/tmp/models/Step-5-Preview-Spark"),
 ("tensorfold-spill scratch", "/var/tmp/tensorfold-spill"),
 ("Qwen3.8-Flash-Next-NVFP4 (HF cache)", "/home/spark3/.cache/huggingface/hub/models--Mia-AiLab--Qwen3.8-Flash-Next-NVFP4"),
 ("qwen3-tts sidecar", "/home/spark3/qwen3-tts"),
 ("ollama store (minicpm-v)", "/home/spark3/.ollama"),
]

G = 1024 ** 3


CAND_PATHS = [p for _l, p in CAND]


def inodes(path, acc=None, skip=None):
    """Walk path collecting (dev,ino)->(bytes,nlink). `skip` = prefixes to prune, so a
    candidate tree nested inside a KEEP root is not counted as kept."""
    acc = {} if acc is None else acc
    skip = skip or ()
    for dp, dns, fns in os.walk(path, onerror=lambda e: None):
        dns[:] = [d for d in dns if os.path.join(dp, d) not in skip]
        if dp in skip:
            continue
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.stat(p)          # follow symlink (HF snapshots)
            except OSError:
                continue
            key = (st.st_dev, st.st_ino)
            acc[key] = (st.st_blocks * 512, st.st_nlink)
    return acc


keep = {}
for p in KEEP:
    if os.path.exists(p):
        # prune candidate subtrees that live INSIDE a keep root (e.g. Step-5 sits in the export)
        inodes(p, keep, skip={c for c in CAND_PATHS if c.startswith(p + "/")})

rows = []
for label, path in CAND:
    if not os.path.exists(path):
        rows.append({"item": label, "path": path, "present": False,
                     "apparent_gb": 0, "freeable_gb": 0, "note": "absent"})
        continue
    d = inodes(path)
    apparent = sum(v[0] for v in d.values())
    freeable = 0
    outside = 0
    for ino, (sz, nl) in d.items():
        if ino in keep:            # at least one hardlink survives in a kept tree
            outside += sz
            continue
        freeable += sz
    rows.append({"item": label, "path": path, "present": True,
                 "apparent_gb": round(apparent / G, 1),
                 "freeable_gb": round(freeable / G, 1),
                 "shared_with_keep_gb": round(outside / G, 1)})

if "--json" in sys.argv:
    print(json.dumps(rows, indent=1))
    sys.exit(0)

print(f"{'item':50s} {'apparent':>9s} {'freeable':>9s} {'in KEEP':>9s}")
tf = ta = 0
for r in rows:
    if not r["present"]:
        print(f"{r['item']:50s} {'--':>9s} {'--':>9s} {'--':>9s}  (absent)")
        continue
    tf += r["freeable_gb"]; ta += r["apparent_gb"]
    print(f"{r['item']:50s} {r['apparent_gb']:9.1f} {r['freeable_gb']:9.1f} "
          f"{r.get('shared_with_keep_gb', 0):9.1f}")
print(f"{'TOTAL':50s} {ta:9.1f} {tf:9.1f}")