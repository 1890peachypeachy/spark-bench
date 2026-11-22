#!/usr/bin/env python3
"""READ-ONLY: is each directory we want to drop from spark4 present, file-for-file (relative path + size), on a peer Spark?
Signature = count, total bytes, sha256 of the sorted '<size> <relpath>' list. No content hashing (metadata only)."""
import json, os, subprocess
from concurrent.futures import ThreadPoolExecutor

SIG = "d={d}; [ -d \"$d\" ] || {{ echo MISSING; exit 0; }}; find \"$d\" -type f -printf '%s %P\\n' 2>/dev/null | sort | " \
      "awk '{{n++; b+=$1; print}} END {{print \"@@\" n \" \" b > \"/dev/stderr\"}}' 2>/tmp/sig.$$ | sha256sum | cut -c1-16; tail -1 /tmp/sig.$$; rm -f /tmp/sig.$$"

TARGETS = [  # (spark4 dir, [peers that might hold the same payload])
    ("/var/tmp/comfy/h3", ["spark1", "spark3"]),
    ("/var/tmp/comfy/models", ["spark1", "spark3"]),
    ("/var/tmp/comfy/yue2", ["spark1", "spark3"]),
    ("/var/tmp/comfy/data", ["spark1", "spark3"]),
    ("/var/tmp/tf1017/engram", ["spark2", "spark1", "spark3"]),
    ("/var/tmp/tf1017/cache", ["spark2", "spark1", "spark3"]),
    ("/var/tmp/tf1017/model", ["spark2", "spark1", "spark3"]),
    ("/var/tmp/tf1017/kit", ["spark2", "spark1", "spark3"]),
    ("/var/tmp/tf1017/engine-bin-v035", ["spark2", "spark1", "spark3"]),
]


def sig(node, d):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", node, "bash", "-c", "'" + SIG.format(d=d).replace("'", "'\\''") + "'"],
                       capture_output=True, text=True, timeout=1500)
    out = r.stdout.strip().split("\n")
    if out and out[0] == "MISSING":
        return "MISSING"
    h = out[0] if out else "?"
    tail = out[1] if len(out) > 1 else ""
    return f"{h} {tail.replace('@@', 'files/bytes=')}"


jobs = []
for d, peers in TARGETS:
    jobs.append(("spark4", d))
    for p in peers:
        jobs.append((p, d))
with ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(lambda j: sig(*j), jobs))
by = {j: r for j, r in zip(jobs, res)}
out = {}
for d, peers in TARGETS:
    s4 = by[("spark4", d)]
    print(f"\n{d}\n   spark4: {s4}")
    match = []
    for p in peers:
        s = by[(p, d)]
        same = (s == s4 and s != "MISSING")
        print(f"   {p}:  {s}   {'== IDENTICAL' if same else ''}")
        if same:
            match.append(p)
    out[d] = {"spark4": s4, "identical_on": match}
json.dump(out, open(os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/replica_check.json"), "w"), indent=1)
