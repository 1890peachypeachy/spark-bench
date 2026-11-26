#!/usr/bin/env python3
"""Concurrency sweep: cN aggregate for N in argv (default 8 16), 512-token replies, fixed panel, thinking on.
   python3 -I conc.py NAME [N ...]  -> appends one JSON line to ledger-conc.jsonl"""
import json, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import Server, PROMPTS
from concurrent.futures import ThreadPoolExecutor
name = sys.argv[1]; Ns = [int(x) for x in sys.argv[2:]] or [8, 16]
srv = Server({"base_url": "http://127.0.0.1:8888", "model": "GLM-5.3-Flash-EXL3", "temperature": 0.6})
res = {"name": name, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
for n in Ns:
    with ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(lambda i: srv.chat(PROMPTS[i % len(PROMPTS)], 512), range(n)))
    toks = sum((x["completion_tokens"] or 0) for x in rs)
    wall = max(x["t_end"] for x in rs) - min(x["t0"] for x in rs)
    res[f"c{n}_aggregate"] = round(toks / wall, 2)
    res[f"c{n}_per_stream_median"] = sorted(round(x["decode"] or 0, 2) for x in rs)[n // 2]
    print(n, res[f"c{n}_aggregate"], flush=True)
open("ledger-conc.jsonl", "a").write(json.dumps(res) + "\n"); print(json.dumps(res))
