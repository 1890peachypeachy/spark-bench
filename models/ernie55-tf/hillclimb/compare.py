"""Compare hill-climb experiments on spark3: gate, short sweep, long-context concurrency, needle, graph stats.

Usage (on spark3): python3 -I compare.py x0-w5-pricelog x1-gstats ...   (reads results/<name>/ and logs/<name>_r0.log)
Prints one table per section; '-' where a run has no data. Read-only.
"""
import json
import os
import re
import statistics as st
import sys

HC = "/var/tmp/ernie55/hillclimb/tf"
names = sys.argv[1:]


def jl(path):
    rows = []
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def gate(n):
    p = f"{HC}/results/{n}/gate.txt"
    if not os.path.exists(p):
        return "-"
    t = open(p, errors="replace").read()
    return "ok" if ("ok=True" in t and "Traceback" not in t) else "FAIL"


def contaminated(n):
    return os.path.exists(f"{HC}/results/{n}/contaminated")


print("== gate / contamination")
for n in names:
    print(f"  {n:22s} gate={gate(n):4s} contaminated={contaminated(n)}")

print("\n== short sweep (bench.py: 384 tok, sampled, thinking on) aggregate tok/s | per-stream median | ttft max")
levels = sorted({r["concurrency"] for n in names for r in jl(f"{HC}/results/{n}/sweep.log") if "concurrency" in r})
print("  " + " " * 22 + "".join(f"{'c' + str(c):>24s}" for c in levels))
for n in names:
    rows = {r["concurrency"]: r for r in jl(f"{HC}/results/{n}/sweep.log") if "concurrency" in r}
    cells = []
    for c in levels:
        r = rows.get(c)
        cells.append(f"{r['aggregate_tok_s']:7.1f} |{r['decode_tok_s_per_stream_median']:5.1f} |{r['ttft_s_max']:5.2f}" if r else "-")
    print(f"  {n:22s}" + "".join(f"{x:>24s}" for x in cells))
for n in names:
    longs = [r for r in jl(f"{HC}/results/{n}/sweep.log") if "target_prompt_tokens" in r]
    if longs:
        print(f"  {n:22s} cold prefill: " + ", ".join(f"{r['target_prompt_tokens']}: {r.get('prefill_tok_s_upper_bound', '-')} tok/s" for r in longs))

for phase in ("shortctx", "longctx"):
  print(f"\n== {phase} concurrency (longctx_conc.py: own warm ctx per stream, greedy, 384 tok) mean over reps")
  for n in names:
    rows = jl(f"{HC}/results/{n}/{phase}.log")
    warm = [r for r in rows if "warm" in r]
    lv = [r for r in rows if "concurrency" in r]
    nd = [r for r in rows if "needle" in r]
    if not rows:
        print(f"  {n:22s} -")
        continue
    pf = [r["prefill_tok_s"] for r in warm if r.get("prefill_tok_s")]
    parts = [f"cold {warm[0]['ptok'] if warm else '-'} tok prefill {st.median(pf):.0f} tok/s" if pf else "no warm"]
    for c in sorted({r["concurrency"] for r in lv}):
        rs = [r for r in lv if r["concurrency"] == c]
        agg = st.mean(r["aggregate_tok_s"] for r in rs)
        ps = st.mean(r["per_stream_decode_median"] for r in rs if r["per_stream_decode_median"])
        parts.append(f"c{c} {agg:.1f} agg / {ps:.1f} per-stream (ttft {max(r['ttft_max_s'] for r in rs):.2f}s)")
    parts.append(f"needle {sum(r['ok'] for r in nd)}/{len(nd)}")
    print(f"  {n:22s} " + " | ".join(parts))
    shas = {r["concurrency"]: r.get("sha") for r in lv if r["rep"] == 0}
    print(f"  {'':22s} reply sha rep0: {shas}  needle sha: {[r['sha'] for r in nd]}")

print("\n== graph stats (last report in each rank-0 log)")
pat = re.compile(r"graph stats: (\w+) streams=(\d+) launch=(\d+) \(([\d.]+) ms\) eager=(\d+) \(([\d.]+) ms\) capture=(\d+) \(([\d.]+) ms\)")
for n in names:
    p = f"{HC}/logs/{n}_r0.log"
    if not os.path.exists(p):
        continue
    last = {}
    for line in open(p, errors="replace"):
        m = pat.search(line)
        if m:
            last[(m[1], int(m[2]))] = m
    if not last:
        continue
    print(f"  {n}")
    for (w, s), m in sorted(last.items()):
        tot = int(m[3]) + int(m[5]) + int(m[7])
        print(f"    {w:6s} streams={s}  rounds={tot:5d}  launch {int(m[3]) / tot:4.0%} ({m[4]} ms)  eager {int(m[5]) / tot:4.0%} ({m[6]} ms)"
              f"  capture {int(m[7]) / tot:4.0%} ({m[8]} ms)")
