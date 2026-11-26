#!/usr/bin/env python3
"""Long-context cold prefill + needle retrieval (thinking on, temperature 0). Prompts are unique (prefix cache cannot help).
   python3 -I longpf.py NAME [target ...]   targets are bench.document() sizes (~0.63 real tokens each)
   -> appends one JSON line to ledger-long.jsonl"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import Server, document

name = sys.argv[1]
targets = [int(x) for x in sys.argv[2:]] or [250000, 370000]
srv = Server({"base_url": "http://127.0.0.1:8888", "model": "GLM-5.3-Flash-EXL3"})
res = {"name": name, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
for t in targets:
    prompt, codes = document(t, seed=t)
    r = srv.chat(prompt, 1200, temperature=0.0)
    res[f"long_{t}"] = {"prompt_tokens": r["prompt_tokens"], "ttft_s": round(r["ttft"], 1),
                        "prefill": round(r["prompt_tokens"] / r["ttft"], 1) if r["prompt_tokens"] else None,
                        "retrieval": f"{sum(c in r['text'] for c in codes)}/{len(codes)}"}
    print(t, res[f"long_{t}"], flush=True)
open("ledger-long.jsonl", "a").write(json.dumps(res) + "\n")
print(json.dumps(res))
