#!/usr/bin/env python3
"""niah2.py — tokenizer-calibrated small NIAH for final candidate validation.
Uses the server's /tokenize endpoint for EXACT prompt token counts (fixes the
nominal-length weakness of the archived niah.py). Varied needles. Fails closed.
"""
import json, sys, time, urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8000"
MODEL = "qwen3.8-flash-next"
NEEDLES = [
    ("The secret launch code for the observatory telescope is NEBULA-7742-KOALA.", "NEBULA-7742-KOALA"),
    ("Maria keeps her spare boat key taped under drawer seventeen in the workshop.", "drawer seventeen"),
    ("The backup archive passphrase is QUIET-OTTER-99-MARSH.", "QUIET-OTTER-99-MARSH"),
]
WORDS = ("the quick brown fox jumps over a lazy dog near the river bank while autumn leaves drift "
         "slowly past the old mill and distant thunder rolls over quiet hills").split()

def tokenize(text):
    req = urllib.request.Request(BASE + "/tokenize",
                                 data=json.dumps({"model": MODEL, "prompt": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    return len(json.load(urllib.request.urlopen(req, timeout=60))["tokens"])

def ask(prompt, mt=48):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": mt,
            "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    return (r["choices"][0]["message"].get("content") or ""), time.monotonic() - t0, r["choices"][0].get("finish_reason")

results = []
allok = True
import random
rnd = random.Random(7)
# filler bank built once, reused per size
bank = " ".join(rnd.choice(WORDS) for _ in range(120000))
for target in (4096, 32768, 131072):
    lo, hi = 0, len(bank)
    # binary search a prefix that tokenizes close to target
    for _ in range(18):
        mid = (lo + hi) // 2
        n = tokenize(bank[:mid] + "\n\nWhat?")
        if n < target: lo = mid
        else: hi = mid
    filler = bank[:lo]
    got = tokenize(filler + "\n\nWhat?")
    for needle, expect in NEEDLES:
        for depth in (0.25, 0.75):
            pos = int(len(filler) * depth)
            hay = filler[:pos] + " " + needle + " " + filler[pos:]
            q = hay + "\n\n" + ("What is the secret launch code for the observatory telescope? Answer with just the code."
                                if "NEBULA" in needle else
                                ("Where does Maria keep her spare boat key? Answer briefly."
                                 if "drawer" in expect else
                                 "What is the backup archive passphrase? Answer with just the passphrase."))
            ans, dt, fin = ask(q)
            ok = expect in ans
            allok = allok and ok
            row = {"target_ctx": target, "actual_prompt_tokens": got, "needle": needle[:30],
                   "depth": depth, "pass": ok, "s": round(dt, 1), "finish": fin, "ans": ans[:60]}
            results.append(row)
            print(json.dumps(row), flush=True)
out = {"ts": datetime.now(timezone.utc).isoformat(), "ok": allok, "tests": results}
print(json.dumps(out))
sys.exit(0 if allok else 3)
