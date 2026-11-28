#!/usr/bin/env python3
"""Mixed-traffic correctness probe: do short greedy requests stay correct while long-context requests run? (stdlib)

8 short documents (~1.5K tokens, 3 hidden access codes each) are asked for their codes (greedy, thinking off), in:
  control      the 8 short requests alone
  long-decode  while 2 long-context requests (~LONG tokens, thinking off, essay) are already DECODING
  long-prefill while 2 NEW long-context requests are still in PREFILL (sent just before the short ones)
Long requests are checked too (PAD tokens / empty output). Prints a JSON line per phase and {"requests": n}.

Usage: python3 -I probe_mixed.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 [--long 20000] [--out f]
"""
import argparse
import concurrent.futures as cf
import json
import random
import threading
import time
import urllib.request

WORDS = ("alpha river stone cloud ember quartz maple orbit cedar delta falcon harbor iris juniper kepler lumen "
         "meadow nickel onyx prism quill raven sierra tundra umber violet willow xenon yarrow zephyr").split()


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


def stream(url, model, content, max_tokens, first_evt=None):
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": 0.0, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    out, t0, t1 = [], time.perf_counter(), None
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            obj = json.loads(line[5:].strip())
            for ch in obj.get("choices") or []:
                piece = (ch.get("delta") or {}).get("content") or ""
                if piece:
                    if t1 is None:
                        t1 = time.perf_counter()
                        if first_evt:
                            first_evt.set()
                    out.append(piece)
    return {"text": "".join(out), "ttft": round((t1 or time.perf_counter()) - t0, 2), "s": round(time.perf_counter() - t0, 2)}


def shorts(a, docs):
    q = "\n\nList the three access codes given in the document above, in order, codes only."
    with cf.ThreadPoolExecutor(len(docs)) as ex:
        rs = list(ex.map(lambda d: stream(a.url, a.model, d[0] + q, 96), docs))
    found = [sum(c in r["text"] for c in d[1]) for r, d in zip(rs, docs)]
    return {"codes_found": f"{sum(found)}/{3 * len(docs)}", "all3": sum(f == 3 for f in found),
            "pad": sum("PAD" in r["text"] for r in rs), "max_s": max(r["s"] for r in rs),
            "sample": [r["text"][:30] for r in rs[:2]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--long", type=int, default=20000)
    ap.add_argument("--seed", default="ernie55-mixed-v1")
    ap.add_argument("--out")
    a = ap.parse_args()
    sdocs = [make_doc(1500, f"{a.seed}-s{i}") for i in range(8)]
    ldocs = [make_doc(a.long, f"{a.seed}-L{i}") for i in range(4)]
    essay = "\n\nUsing the document above only as background, write a long, detailed essay about how bridges carry load."
    sent, res = 0, {}

    res["control"] = shorts(a, sdocs)
    sent += 8
    print(json.dumps({"phase": "control", **res["control"]}), flush=True)

    # long-decode: two long requests, wait until both stream their first token, then the 8 short ones
    evts = [threading.Event(), threading.Event()]
    longs = [None, None]

    def run_long(i, doc, evt):
        longs[i] = stream(a.url, a.model, doc[0] + essay, 700, evt)
    ths = [threading.Thread(target=run_long, args=(i, ldocs[i], evts[i])) for i in range(2)]
    for t in ths:
        t.start()
    for e in evts:
        e.wait(600)
    res["long-decode"] = shorts(a, sdocs)
    for t in ths:
        t.join()
    sent += 10
    res["long-decode"]["longs"] = [{"ttft": x["ttft"], "pad": "PAD" in x["text"], "chars": len(x["text"])} for x in longs]
    print(json.dumps({"phase": "long-decode", **res["long-decode"]}), flush=True)

    # long-prefill: two NEW long requests (cold prefill), the 8 short ones 1 s later, while those prefill
    longs = [None, None]
    ths = [threading.Thread(target=run_long, args=(i, ldocs[2 + i], None)) for i in range(2)]
    for t in ths:
        t.start()
    time.sleep(1.0)
    res["long-prefill"] = shorts(a, sdocs)
    for t in ths:
        t.join()
    sent += 10
    res["long-prefill"]["longs"] = [{"ttft": x["ttft"], "pad": "PAD" in x["text"], "chars": len(x["text"])} for x in longs]
    print(json.dumps({"phase": "long-prefill", **res["long-prefill"]}), flush=True)
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)
    print(json.dumps({"requests": sent}), flush=True)


if __name__ == "__main__":
    main()
