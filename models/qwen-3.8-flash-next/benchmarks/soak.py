#!/usr/bin/env python3
"""soak.py — >=30min varied-concurrency soak for final candidate validation.
Cycles C1/C2/C4/C8/C16 code generations + a prose round + a long-prefill round,
recording per-round throughput and ALL failures. Fail-closed summary.
"""
import json, sys, time, threading, uuid, urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8000"
MODEL = "qwen3.8-flash-next"
CODE = ("Write a complete, idiomatic Python implementation of a binary search tree with insert, "
        "delete, search, traversal, height, docstrings, and tests. Code only. Add exhaustive tests "
        "using pytest, covering edge cases.")
PROSE = ("Write a detailed, well-structured essay of at least 1000 words about the history of the "
         "transcontinental railroad, covering planning, financing, construction, labor, and legacy.")
LONGPREFILL = "Summarize the following text in one paragraph.\n\n" + ("The transcontinental railroad transformed commerce, migration, and the economy of North America. " * 700)
MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 30

def one(prompt, max_tokens, timeout=900):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            if not line.startswith(b"data:"): continue
            p = line[5:].strip()
            if p == b"[DONE]": break
            try: c = json.loads(p)
            except Exception: continue
            if c.get("usage"): u = c["usage"]
    return int(u["completion_tokens"] or 0)

def round_agg(n, prompt, max_tokens):
    outs = [None]*n; errs = [None]*n
    def w(i):
        try: outs[i] = one(prompt + " nonce=" + uuid.uuid4().hex, max_tokens)
        except Exception as e:  # noqa: BLE001
            errs[i] = repr(e)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    t0 = time.monotonic()
    for t in ts: t.start()
    for t in ts: t.join()
    wall = time.monotonic() - t0
    tot = sum(o for o in outs if o)
    fails = sum(1 for e in errs if e)
    if fails: print(f"  ROUND-ERRORS: {n} fails={fails}: {[e for e in errs if e][:2]}", flush=True)
    return {"n": n, "tokens": tot, "wall_s": round(wall,1), "tok_s": round(tot/wall,1) if wall else 0, "fails": fails}

t_end = time.monotonic() + MINUTES*60
rounds = []
i = 0
while time.monotonic() < t_end:
    phase = i % 5
    if phase == 4:
        r = round_agg(1, LONGPREFILL, 512)          # long prefill round (~30k tokens in)
        r["kind"] = "longprefill"
    else:
        n = (1, 2, 4, 8, 16)[phase]
        r = round_agg(n, CODE, 1200); r["kind"] = f"code_c{n}"
    rounds.append(r)
    print(json.dumps(r), flush=True)
    i += 1
    # prose round every 5th cycle
    if i % 5 == 0:
        r = round_agg(2, PROSE, 1000); r["kind"] = "prose_c2"
        rounds.append(r)
        print(json.dumps(r), flush=True)

fails_total = sum(r["fails"] for r in rounds)
tot_tokens = sum(r["tokens"] for r in rounds)
summary = {"ts": datetime.now(timezone.utc).isoformat(), "minutes": MINUTES,
           "rounds": len(rounds), "total_tokens": tot_tokens, "total_fails": fails_total,
           "ok": fails_total == 0 and tot_tokens > 0, "detail": rounds}
print(json.dumps(summary))
sys.exit(0 if summary["ok"] else 3)
