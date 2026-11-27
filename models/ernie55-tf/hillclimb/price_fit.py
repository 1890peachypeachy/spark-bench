"""Fit ERNIE-5.5 TensorFold shared-round costs from TF_SHARED_PRICE_LOG lines.

Usage: python3 -I price_fit.py <rank0.log> [--json out.json]
Prints, per total rows: rounds, median measured ms, the table's forward ms, and the ratio; then per stream count.
"""
import json
import re
import statistics as st
import sys
from collections import defaultdict

RE = re.compile(r"shared price: round streams=(\d+) sampled=(\d) trial=(\d) rows=(\d+) ms=([\d.]+) head=([\d.]+) "
                r"forward=([\d.-]+) plain=(\S+) row=(\S+) drafts=(\S+) depths=(\S+)")
path = sys.argv[1]
by_rows = defaultdict(list)
by_sr = defaultdict(list)
table = {}
n = 0
for line in open(path, errors="replace"):
    m = RE.search(line)
    if not m:
        continue
    streams, sampled, trial, rows = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    ms, head, fwd = float(m[5]), float(m[6]), m[7]
    n += 1
    by_rows[rows].append(ms)
    by_sr[(streams, rows)].append(ms)
    if fwd != "-":
        table[rows] = float(fwd)
print(f"{n} priced shared rounds")
print("rows  n   med_ms  p25    p75    table  ratio")
fit = {}
for r in sorted(by_rows):
    v = sorted(by_rows[r])
    med = st.median(v)
    p25 = v[len(v) // 4]
    p75 = v[(3 * len(v)) // 4]
    t = table.get(r)
    fit[r] = {"n": len(v), "median_ms": round(med, 2), "p25": round(p25, 2), "p75": round(p75, 2), "table": t}
    print(f"{r:4d} {len(v):4d} {med:7.1f} {p25:6.1f} {p75:6.1f} {t if t else '-':>6} {med / t if t else 0:5.2f}")
print("\nstreams rows n med_ms")
for (s, r) in sorted(by_sr):
    v = by_sr[(s, r)]
    if len(v) >= 3:
        print(f"{s:7d} {r:4d} {len(v):3d} {st.median(v):7.1f}")
if "--json" in sys.argv:
    json.dump({"by_rows": fit, "by_streams_rows": {f"{s}x{r}": round(st.median(v), 2) for (s, r), v in by_sr.items() if len(v) >= 3}},
              open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
