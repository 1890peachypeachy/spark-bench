#!/usr/bin/env python3
"""rocetrace4.py DIR: the RoCE exchange trace (GLM53_TF_ROCE_TRACE_DUMP_S) of a four-rank run, ranks paired by seq.

Per exchange and rank: stage = doorbell - start, wait = flags - doorbell, copy = end - flags; compute before it =
start(seq) - end(seq - 1) on that rank (the GPU work between two exchanges, plus launch gaps). The rank that waits
least arrived last. Clocks differ between nodes, so only same-rank differences are used.
"""
import base64, glob, json, os, statistics as st, sys
from collections import Counter, defaultdict

import numpy as np

d = sys.argv[1]
ranks = {}
for f in sorted(glob.glob(os.path.join(d, "*-r[0-9].jsonl"))):
    rows = {}
    for line in open(f):
        try:
            j = json.loads(line)
        except Exception:
            continue
        if "stamps" not in j:
            continue
        a = np.frombuffer(base64.b64decode(j["stamps"]), dtype=np.int64).reshape(-1, 4)
        for i, s in enumerate(range(j["first"], j["first"] + len(a))):
            rows[s] = a[i]
    ranks[int(f[-7])] = rows
print("ranks", {r: len(v) for r, v in ranks.items()})
R = sorted(ranks)
common = sorted(set.intersection(*(set(v) for v in ranks.values())))
ok = [s for s in common if all((ranks[r][s] > 0).all() for r in R)]
print("paired exchanges", len(ok))

late = Counter()
wait = defaultdict(list); stage = defaultdict(list); copy = defaultdict(list); kern = defaultdict(list)
comp = defaultdict(list); comp_max_minus = []; comp_spread = []
skew_by = Counter()
okset = set(ok)
for s in ok:
    w = {r: ranks[r][s][2] - ranks[r][s][1] for r in R}
    late[min(w, key=w.get)] += 1
    for r in R:
        st_, db, fl, en = ranks[r][s]
        wait[r].append(w[r]); stage[r].append(db - st_); copy[r].append(en - fl); kern[r].append(en - st_)
    if s - 1 in okset:
        c = {r: ranks[r][s][0] - ranks[r][s - 1][3] for r in R}
        if all(0 < v < 50_000_000 for v in c.values()):
            for r in R:
                comp[r].append(c[r])
            m = max(c.values())
            comp_spread.append(m - min(c.values()))
            comp_max_minus.append(m - st.mean(c.values()))
            skew_by[max(c, key=c.get)] += 1

us = lambda xs: f"{st.median(xs)/1e3:6.2f} [{np.percentile(xs,10)/1e3:.2f}-{np.percentile(xs,90)/1e3:.2f}]"
print("\nlast to arrive (waits least), share of exchanges:", {r: f"{late[r]/len(ok):.0%}" for r in R})
print("slowest compute segment before an exchange, share:", {r: f"{skew_by[r]/max(1,sum(skew_by.values())):.0%}" for r in R})
for r in R:
    print(f"r{r}: stage {us(stage[r])}  wait {us(wait[r])}  copy {us(copy[r])}  kernel {us(kern[r])} us | "
          f"compute between exchanges sum {sum(comp[r])/1e6:.1f} ms")
n = len(comp_spread)
print(f"\nsegments {n}: compute spread (slowest - fastest) median {st.median(comp_spread)/1e3:.2f} us, "
      f"mean {st.mean(comp_spread)/1e3:.2f} us; slowest - mean {st.mean(comp_max_minus)/1e3:.2f} us a segment")
tot_k = st.mean([sum(kern[r]) for r in R]); tot_w = st.mean([sum(wait[r]) for r in R])
print(f"per exchange: kernel mean {tot_k/len(ok)/1e3:.2f} us (wait {tot_w/len(ok)/1e3:.2f}); "
      f"skew loss (slowest - mean compute) {st.mean(comp_max_minus)/1e3:.2f} us")
