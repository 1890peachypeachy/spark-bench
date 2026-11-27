"""Aggregate an nsys cuda_gpu_trace CSV by kernel name: total ms, count, mean us. Read-only.

Usage: python3 -I trace_top.py <trace.csv> [top_n]
"""
import csv
import sys
from collections import defaultdict

path = sys.argv[1]
top = int(sys.argv[2]) if len(sys.argv) > 2 else 40
tot = defaultdict(float)
cnt = defaultdict(int)
first = None
last = 0
with open(path, newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        try:
            start = int(row["Start (ns)"])
            dur = int(row["Duration (ns)"])
        except (ValueError, KeyError):
            continue
        name = row.get("Name", "?")
        if len(name) > 90:
            name = name[:90]
        tot[name] += dur
        cnt[name] += 1
        first = start if first is None else min(first, start)
        last = max(last, start + dur)
span = (last - first) / 1e6 if first is not None else 0
busy = sum(tot.values()) / 1e6
print(f"span {span:.1f} ms, kernel+memcpy busy {busy:.1f} ms ({100 * busy / span if span else 0:.1f}%)")
for name, t in sorted(tot.items(), key=lambda kv: -kv[1])[:top]:
    print(f"{t / 1e6:9.1f} ms {100 * t / 1e6 / busy:5.1f}%  n={cnt[name]:7d}  mean={t / cnt[name] / 1e3:8.1f} us  {name}")
