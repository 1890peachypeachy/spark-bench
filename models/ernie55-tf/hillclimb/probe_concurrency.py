#!/usr/bin/env python3
"""Concurrency correctness probe: does a request decode the same when it shares rounds with others? (stdlib only)

Fixed short documents (~1.5K tokens), each hiding 3 access codes. Every mode asks each document for its codes:
  solo-nothink    one request at a time, greedy, thinking off          (the reference)
  c2-nothink      2 at a time, greedy, thinking off
  c8-nothink      8 at once, greedy, thinking off                      (batched == alone check vs solo)
  c8-think        8 at once, greedy, thinking on (max_tokens 1536 so it can answer)
  c8-nothink-t06  8 at once, temperature 0.6, thinking off
  solo-again      one at a time again (state did not degrade)
Prints one JSON line per mode: codes found, PAD replies, replies identical to solo, and {"requests": n} at the end.

Usage: python3 -I probe_concurrency.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 [--modes a,b] [--out f]
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import random
import time
import urllib.request

WORDS = ("alpha river stone cloud ember quartz maple orbit cedar delta falcon harbor iris juniper kepler lumen "
         "meadow nickel onyx prism quill raven sierra tundra umber violet willow xenon yarrow zephyr").split()
MODES = {  # name: (concurrency, thinking, temperature, max_tokens)
    # unscored: fills the prompt cache, so every scored mode resumes the same way (a cold first pass prefills
    # differently and can flip greedy formatting, e.g. newline vs comma, which reads as a batching difference)
    "warmup": (1, False, 0.0, 96),
    "solo-nothink": (1, False, 0.0, 96),
    "c2-nothink": (2, False, 0.0, 96),
    "c8-nothink": (8, False, 0.0, 96),
    "c8-think": (8, True, 0.0, 1536),
    "c8-nothink-t06": (8, False, 0.6, 96),
    "solo-again": (1, False, 0.0, 96),
}


def make_doc(n_tokens, tag):
    rng = random.Random(tag)
    n_words = int(n_tokens / 1.3)
    codes = [f"{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}-{rng.randint(1000, 9999)}"
             for _ in range(3)]
    marks = [int(n_words * f) for f in (0.2, 0.5, 0.8)]
    lines, words, i, ci = [], 0, 0, 0
    while words < n_words:
        if ci < 3 and words >= marks[ci]:
            lines.append(f"Note: access code number {ci + 1} for archive {tag} is {codes[ci]}.")
            ci += 1
        k = rng.randint(8, 16)
        lines.append(f"{i}. " + " ".join(rng.choice(WORDS) for _ in range(k)) + ".")
        words += k + 1
        i += 1
    return f"[archive {tag}]\n" + "\n".join(lines), codes


def post(url, model, content, max_tokens, temperature, thinking):
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": temperature, "top_p": 0.95, "stream": False}
    if not thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    msg = d["choices"][0]["message"]
    return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or "",
            "ctok": d.get("usage", {}).get("completion_tokens"), "finish": d["choices"][0].get("finish_reason"),
            "s": round(time.perf_counter() - t0, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--docs", type=int, default=8)
    ap.add_argument("--ctx", type=int, default=1500)
    ap.add_argument("--seed", default="ernie55-probe-v1")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--out")
    a = ap.parse_args()
    docs = [make_doc(a.ctx, f"{a.seed}-{i}") for i in range(a.docs)]
    q = "\n\nList the three access codes given in the document above, in order, codes only."
    sent, results, solo = 0, {}, None
    for mode in a.modes.split(","):
        conc, thinking, temp, mt = MODES[mode]
        t0 = time.perf_counter()
        with cf.ThreadPoolExecutor(conc) as ex:
            rs = list(ex.map(lambda i: post(a.url, a.model, docs[i][0] + q, mt, temp, thinking), range(a.docs)))
        sent += a.docs
        found = [sum(c in r["content"] for c in docs[i][1]) for i, r in enumerate(rs)]
        pad = sum("PAD" in (r["content"] + r["reasoning"]) for r in rs)
        shas = [hashlib.sha1(r["content"].encode()).hexdigest()[:10] for r in rs]
        row = {"mode": mode, "wall_s": round(time.perf_counter() - t0, 1), "codes_found": f"{sum(found)}/{3 * a.docs}",
               "all3": sum(f == 3 for f in found), "pad_replies": pad,
               "finish": sorted({r["finish"] for r in rs}), "ctok": [r["ctok"] for r in rs],
               "sample": [r["content"][:40] for r in rs[:3]]}
        if mode == "warmup":
            pass
        elif mode == "solo-nothink":
            solo = shas
        elif solo and not thinking and temp == 0.0:
            row["identical_to_solo"] = f"{sum(x == y for x, y in zip(shas, solo))}/{a.docs}"
        results[mode] = {"row": row, "replies": [r["content"] for r in rs]}
        print(json.dumps(row), flush=True)
    if a.out:
        json.dump(results, open(a.out, "w"), indent=1)
    print(json.dumps({"requests": sent}), flush=True)


if __name__ == "__main__":
    main()
