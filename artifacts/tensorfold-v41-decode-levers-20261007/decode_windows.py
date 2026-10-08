#!/usr/bin/env python3
"""decode_windows.py DIR [N]: four-rank RoCE trace dumps (DIR/*-r0..3.jsonl, GLM53_TF_ROCE_TRACE_DUMP_S) cut into
decode windows of N exchanges (92 on DeepSeek V4.1 Flash, TP=4): per-rank compute between exchanges, time inside
exchange kernels and waiting, the skew (slowest - mean compute, summed a window) and its systematic part."""
import base64, glob, json, statistics as st, sys
import numpy as np

d = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 92
ranks = {}
for f in sorted(glob.glob(d + "/*-r[0-9].jsonl")):
    rows = {}
    for line in open(f):
        try:
            j = json.loads(line)
        except Exception:
            continue
        if "stamps" in j:
            a = np.frombuffer(base64.b64decode(j["stamps"]), dtype="<i8").reshape(-1, 4)
            for i in range(len(a)):
                rows[j["first"] + i] = a[i]
    ranks[int(f[-7])] = rows
R = sorted(ranks); r0 = ranks[R[0]]
seqs = sorted(set.intersection(*(set(v) for v in ranks.values())))
groups, cur = [], [seqs[0]]
for a, b in zip(seqs, seqs[1:]):                 # rounds run back to back: break on a gap > 1.5 ms or a hole
    if b != a + 1 or r0[b][0] - r0[a][3] > 1_500_000:
        groups.append(cur); cur = [b]
    else:
        cur.append(b)
groups.append(cur)
sel = [g[i:i + n] for g in groups if len(g) % n == 0 for i in range(0, len(g), n)]
print("decode windows:", len(sel))
seg = np.array([[ranks[r][b][0] - ranks[r][a][3] for r in R] for w in sel for a, b in zip(w, w[1:])],
               dtype=float).reshape(len(sel), n - 1, len(R))
ker = np.array([[ranks[r][s][3] - ranks[r][s][0] for r in R] for w in sel for s in w], dtype=float).reshape(len(sel), n, len(R))
wai = np.array([[ranks[r][s][2] - ranks[r][s][1] for r in R] for w in sel for s in w], dtype=float).reshape(len(sel), n, len(R))
print("rank 0 span, first exchange start -> last end: %.2f ms" % st.median((r0[w[-1]][3] - r0[w[0]][0]) / 1e6 for w in sel))
print("compute between exchanges, ms a window:", np.round(np.median(seg.sum(1), 0) / 1e6, 2))
print("inside exchange kernels, ms:", np.round(np.median(ker.sum(1), 0) / 1e6, 2), "waiting:", np.round(np.median(wai.sum(1), 0) / 1e6, 2))
print("sum of slowest / mean / fastest segment: %.2f / %.2f / %.2f ms" % tuple(
    np.median(f(seg, 2).sum(1)) / 1e6 for f in (np.max, np.mean, np.min)))
sysm = (seg.mean(1) - seg.mean(1).mean(1, keepdims=True)).mean(0) / 1e3
print("systematic: rank compute - 4-rank mean, us a segment:", np.round(sysm, 2))
late = wai.argmin(2); print("last to arrive:", [round(float((late == i).mean()), 2) for i in range(len(R))])
med = np.median(seg, 0) / 1e3
for r in range(len(R)):
    print(f"r{R[r]} segment medians (us):", np.round(med[:, r]).astype(int).tolist())
