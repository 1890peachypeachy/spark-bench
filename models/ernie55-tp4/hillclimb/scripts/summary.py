#!/usr/bin/env python3
"""Join ledger.jsonl + ledger-conc.jsonl + spec.jsonl (+ ledger-long.jsonl) by run order. Run in the hill-climb dir.
   python3 -I summary.py [since-ISO-time]"""
import json, sys

since = sys.argv[1] if len(sys.argv) > 1 else "2026-11-25T23:00"
rd = lambda p: [json.loads(l) for l in open(p) if l.strip()]
L = [d for d in rd("ledger.jsonl") if d.get("ok") and d["time"] >= since]
conc = [d for d in rd("ledger-conc.jsonl") if d["time"] >= since]
spec = rd("spec.jsonl")
try:
    long_ = rd("ledger-long.jsonl")
except FileNotFoundError:
    long_ = []
spec = spec[-len(L):] if L else []


def take(rows, name, used):
    for i, d in enumerate(rows):
        if i not in used and d["name"] == name:
            used.add(i)
            return d
    return {}


uc, ul = set(), set()
print(f"{'run':10} {'c1':>6} {'c4':>7} {'c8':>7} {'c16':>7} {'c32':>7} {'pf5K':>6} {'pf20K':>6} {'pf82K':>6} {'ttft':>5} {'tok/st':>6}  long")
for a, s in zip(L, spec):
    c = take(conc, a["name"], uc)
    lg = take(long_, a["name"], ul) if a["name"].endswith("L") else {}
    lgs = " ".join(f"{v['prompt_tokens']}:{v['prefill']}({v['retrieval']})" for k, v in lg.items() if k.startswith("long_"))
    print(f"{a['name']:10} {a.get('c1_decode') or 0:6.2f} {a.get('c4_aggregate') or 0:7.2f} {c.get('c8_aggregate') or 0:7.2f} "
          f"{c.get('c16_aggregate') or 0:7.2f} {c.get('c32_aggregate') or 0:7.2f} {a.get('prefill_8192') or 0:6.0f} "
          f"{a.get('prefill_32768') or 0:6.0f} {a.get('prefill_131072') or 0:6.0f} {a.get('ttft_short_ms') or 0:5.0f} "
          f"{s.get('tokens_per_step') or 0:6.3f}  {lgs}")
