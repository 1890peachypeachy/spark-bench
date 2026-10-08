#!/usr/bin/env python3
"""Stream-protocol decode bench: single-stream median + N-stream aggregate. Usage: dsbench.py <label> [streams=4]"""
import json, sys, time, statistics, urllib.request, concurrent.futures as cf
BASE="http://127.0.0.1:8000/v1/chat/completions"; MODEL="deepseek-v4.1-flash"
PROMPTS=[
 "Write a long, detailed essay about the history of lighthouses: ancient origins, the Fresnel lens, electrification, automation, GPS redundancy. At least 1200 words.",
 "Write a Python module implementing an LRU cache with TTL, type hints, docstrings, unit tests, and ten usage examples. Return code only.",
 "Explain, step by step with all arithmetic shown, how to compute compound interest monthly for 30 years on $10,000 at 6%, then compare with continuous compounding.",
 "Write a vivid short story about a lighthouse keeper's last night before automation, 1000 words.",
]
def one(prompt, maxtok=1500):
    body=json.dumps({"model":MODEL,"messages":[{"role":"user","content":prompt}],"max_tokens":maxtok,"temperature":0,
        "stream":True,"stream_options":{"include_usage":True},"chat_template_kwargs":{"thinking":False}}).encode()
    req=urllib.request.Request(BASE,data=body,headers={"Content-Type":"application/json"})
    t0=time.monotonic(); t1=t2=None; n=None
    with urllib.request.urlopen(req,timeout=900) as r:
        for line in r:
            if not line.startswith(b"data:"): continue
            p=line[5:].strip()
            if p==b"[DONE]": break
            try: c=json.loads(p)
            except: continue
            if c.get("usage"): n=c["usage"].get("completion_tokens")
            ch=c.get("choices") or []
            if ch and ((ch[0].get("delta") or {}).get("content") or (ch[0].get("delta") or {}).get("reasoning")):
                now=time.monotonic(); t1=t1 or now; t2=now
    return (n or 0), (t2-t1 if t1 and t2 else 0), (t1-t0 if t1 else 0)
label=sys.argv[1]; streams=int(sys.argv[2]) if len(sys.argv)>2 else 4
one(PROMPTS[0],200)  # warm
single=[]
for i in range(5):
    n,d,ttft=one(PROMPTS[i%4]); single.append(n/d if d else 0)
with cf.ThreadPoolExecutor(streams) as ex:
    t0=time.monotonic(); res=list(ex.map(lambda p: one(p), PROMPTS*(streams//4) or PROMPTS[:streams])); wall=time.monotonic()-t0
agg=sum(r[0] for r in res)/wall
print(f"[{label}] single-stream median {statistics.median(single):.1f} tok/s (runs {[round(x,1) for x in single]}) | {streams}-stream aggregate {agg:.1f} tok/s ({sum(r[0] for r in res)} tok / {wall:.0f}s)")
