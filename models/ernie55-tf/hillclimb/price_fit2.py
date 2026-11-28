"""Fit shared-round costs from a TF_SHARED_PRICE_LOG rank-0 log, split by phase (short-context sweep vs long-context).

The long-context phase starts at the first `done` line whose prompt is >= --long-min tokens (longctx_conc.py's warm
requests); every priced round after it is a long-context round. Read-only.

Usage: python3 -I price_fit2.py <rank0.log> [--long-min 50000] [--json out.json]
"""
import json
import re
import statistics as st
import sys
from collections import defaultdict

RE = re.compile(r"shared price: round streams=(\d+) sampled=(\d) trial=(\d) rows=(\d+) ms=([\d.]+) head=([\d.]+) "
                r"forward=([\d.-]+)")
DONE = re.compile(r"\] done .*?prompt=(\d+) cached=(\d+).*?tokens=(\d+).*?rounds=(\d+).*?accepted=(\d+)/(\d+)"
                  r".*?decode=([\d.]+)")
path = sys.argv[1]
long_min = int(sys.argv[sys.argv.index("--long-min") + 1]) if "--long-min" in sys.argv else 50000
phase = "short"
by = {"short": defaultdict(list), "long": defaultdict(list)}
streams_rows = {"short": defaultdict(list), "long": defaultdict(list)}
table = {}
dones = {"short": [], "long": []}
for line in open(path, errors="replace"):
    m = DONE.search(line)
    if m:
        p = int(m[1])
        if p >= long_min:
            phase = "long"
        if int(m[4]) > 0:
            dones[phase].append({"prompt": p, "cached": int(m[2]), "tokens": int(m[3]), "rounds": int(m[4]),
                                 "acc": int(m[5]), "drafted": int(m[6]), "decode": float(m[7])})
        continue
    m = RE.search(line)
    if not m:
        continue
    s, rows, ms, fwd = int(m[1]), int(m[4]), float(m[5]), m[7]
    by[phase][rows].append(ms)
    streams_rows[phase][(s, rows)].append(ms)
    if fwd != "-":
        table[rows] = float(fwd)
out = {}
for ph in ("short", "long"):
    rows_ms = {r: round(st.median(v), 2) for r, v in sorted(by[ph].items()) if len(v) >= 3}
    out[ph] = {"rounds": sum(len(v) for v in by[ph].values()), "median_ms_by_rows": rows_ms}
    print(f"== {ph}: {out[ph]['rounds']} priced shared rounds")
    for r, ms in rows_ms.items():
        t = table.get(r)
        print(f"  rows {r:3d}  n={len(by[ph][r]):4d}  median {ms:7.1f} ms   table {t if t else '-':>6}   ratio {ms / t if t else 0:4.2f}")
    d = [x for x in dones[ph] if x["tokens"] >= 64]
    if d:
        msr = [1000 * x["decode"] / x["rounds"] for x in d]
        tpr = [x["tokens"] / x["rounds"] for x in d]
        dpr = [x["drafted"] / x["rounds"] for x in d]
        print(f"  requests {len(d)}: ms/round median {st.median(msr):.1f}, tokens/round {st.median(tpr):.2f}, "
              f"drafted/round {st.median(dpr):.2f}")
        out[ph]["requests"] = {"n": len(d), "ms_per_round": round(st.median(msr), 1),
                               "tokens_per_round": round(st.median(tpr), 2), "drafted_per_round": round(st.median(dpr), 2)}
if "--json" in sys.argv:
    json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
