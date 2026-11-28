#!/usr/bin/env python3
"""Drive a long prefill (the workload that crashed the lane): N concurrent requests of ~K-token synthetic prompts, max_tokens 16.
usage: longprefill.py <approx_tokens> <concurrent>"""
import json, sys, threading, time, urllib.request, random

K, C = int(sys.argv[1]), int(sys.argv[2])
base = "http://100.99.120.29:8888/v1/chat/completions"
words = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango "
         "uniform the owner whiskey xray yankee zulu fabric tensor queue packet kernel buffer switch rank decode prefill cache latent").split()
res = [None] * C


def run(i):
    rnd = random.Random(1000 + i)
    text = " ".join(rnd.choice(words) + str(rnd.randint(0, 999)) for _ in range(int(K / 1.9)))  # ~1.9 tokens per word+number
    body = json.dumps({"model": "glm-5.3", "messages": [{"role": "user", "content": text + "\n\nReply with the single word: done"}],
                       "max_tokens": 16, "temperature": 0, "reasoning_effort": "low"}).encode()
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(base, body, {"Content-Type": "application/json"}), timeout=900))
        u = r.get("usage", {})
        res[i] = (round(time.time() - t0, 1), u.get("prompt_tokens"), None)
    except Exception as e:
        res[i] = (round(time.time() - t0, 1), None, str(e)[:100])


th = [threading.Thread(target=run, args=(i,)) for i in range(C)]
[t.start() for t in th]
[t.join() for t in th]
ok = [r for r in res if r[1]]
print(json.dumps({"concurrent": C, "results": res, "prefill_tok_s_each": [round(r[1] / r[0]) for r in ok]}))
