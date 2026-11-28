#!/usr/bin/env python3
"""Sustained mixed-traffic corruption hunter for the ERNIE TP4 lane (stdlib only).

Workers loop over request kinds that recreate the two observed PAD events: cold prefills (short ~1.8K and long
~10-22K) arriving while other streams decode, warm resumes, long greedy essays, thinking on and off. Every reply is
checked for PAD tokens and, for code questions, for its 3 access codes. One JSON line per request goes to --out,
with the server's request id (matches the rank-0 log's `done chatcmpl-...` line).

Foreign-traffic guard: if the server reports more running+waiting requests than this script has in flight, no new
request starts until that clears (protects live agents; logged as guard events).

Usage: python3 -I stress_pad.py --url http://127.0.0.1:8888 --minutes 12 --workers 6 --out stress.jsonl
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
CODES_Q = "\n\nList the three access codes given in the document above, in order, codes only."
ESSAY_Q = "\n\nUsing the document above only as background, write a long, detailed essay about how bridges carry load."
KINDS = [  # name, weight (--mix sampled adds sampled kinds: greedy and sampled streams then share rounds)
    ("short-codes", 4), ("fresh-short-codes", 3), ("long-essay", 2), ("fresh-long-codes", 2), ("think-short", 1),
]
SAMPLED_KINDS = [("sampled-think-essay", 3), ("sampled-random", 3), ("sampled-long-essay", 1)]
TOPICS = ["the history of cartography", "how bridges carry load", "the chemistry of bread", "why tides happen",
          "the design of a good API", "how vaccines train immunity", "the economics of shipping",
          "how compilers optimize loops"]


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


class Guard:
    def __init__(self, url):
        self.url, self.lock, self.inflight, self.foreign = url, threading.Lock(), 0, False
        self.events, self.stop = [], False

    def poll(self):
        bad = 0
        while not self.stop:
            try:
                txt = urllib.request.urlopen(self.url + "/metrics", timeout=3).read().decode()
                m = {l.split()[0]: float(l.split()[1]) for l in txt.splitlines()
                     if l.startswith("tensorfold:requests_") and len(l.split()) == 2}
                busy = m.get("tensorfold:requests_running", 0) + m.get("tensorfold:requests_waiting", 0)
                with self.lock:
                    own = self.inflight
                bad = bad + 1 if busy > own else 0
                now = bad >= 2
                if now != self.foreign:
                    self.events.append({"t": round(time.time(), 1), "foreign": now, "busy": busy, "own": own})
                self.foreign = now
            except Exception:
                pass
            time.sleep(1.0)

    def wait_clear(self):
        while self.foreign and not self.stop:
            time.sleep(1.0)


def post(url, model, content, max_tokens, thinking, temperature=0.0):
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": temperature, "top_p": 0.95, "stream": False}
    if not thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--minutes", type=float, default=12)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", default="ernie55-stress-v1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mix", default="greedy", choices=["greedy", "sampled"])
    a = ap.parse_args()
    rng = random.Random(a.seed)
    kinds = KINDS + (SAMPLED_KINDS if a.mix == "sampled" else [])
    shorts = [make_doc(1800, f"{a.seed}-s{i}") for i in range(12)]
    longs = [make_doc(22000, f"{a.seed}-L{i}") for i in range(3)]
    guard = Guard(a.url)
    threading.Thread(target=guard.poll, daemon=True).start()
    out = open(a.out, "a")
    olock = threading.Lock()
    stats = {"n": 0, "bad": 0}
    t_end = time.time() + 60 * a.minutes
    fresh_n = [0]

    def one(wid):
        while time.time() < t_end:
            guard.wait_clear()
            with olock:
                kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
                fresh_n[0] += 1
                fid = fresh_n[0]
            temp = 0.0
            if kind == "sampled-think-essay":
                doc, codes = rng.choice(shorts); q, mt, think, temp = ESSAY_Q, 384, True, 0.6
            elif kind == "sampled-random":
                doc, codes = f"[{fid}-{time.time()}] Explain in depth: {rng.choice(TOPICS)}.", []
                q, mt, think, temp = "", 384, True, 0.6
            elif kind == "sampled-long-essay":
                doc, codes = rng.choice(longs); q, mt, think, temp = ESSAY_Q, 384, True, 0.6
            elif kind == "short-codes":
                doc, codes = rng.choice(shorts); q, mt, think = CODES_Q, 64, False
            elif kind == "fresh-short-codes":
                doc, codes = make_doc(1800, f"{a.seed}-fs{fid}-{time.time()}"); q, mt, think = CODES_Q, 64, False
            elif kind == "long-essay":
                doc, codes = rng.choice(longs); q, mt, think = ESSAY_Q, 400, False
            elif kind == "fresh-long-codes":
                n = rng.choice([10000, 16000, 22000])
                doc, codes = make_doc(n, f"{a.seed}-fl{fid}-{time.time()}"); q, mt, think = CODES_Q, 64, False
            else:
                doc, codes = rng.choice(shorts); q, mt, think = CODES_Q, 700, True
            with guard.lock:
                guard.inflight += 1
            t0 = time.time()
            rec = {"t0": round(t0, 1), "w": wid, "kind": kind}
            try:
                d = post(a.url, a.model, doc + q, mt, think, temp)
                msg = d["choices"][0]["message"]
                text = (msg.get("content") or "")
                full = text + (msg.get("reasoning_content") or "")
                u = d.get("usage") or {}
                found = sum(c in text for c in codes)
                pad = "PAD" in full
                need_codes = kind.endswith("codes")
                bad = pad or (need_codes and found < 3)
                rec.update({"id": d.get("id"), "s": round(time.time() - t0, 2), "ptok": u.get("prompt_tokens"),
                            "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                            "ctok": u.get("completion_tokens"), "finish": d["choices"][0].get("finish_reason"),
                            "pad": pad, "found": found if need_codes else None, "bad": bad,
                            "head": text[:60]})
            except Exception as e:
                rec.update({"error": repr(e)[:200], "bad": None})
            finally:
                with guard.lock:
                    guard.inflight -= 1
            with olock:
                stats["n"] += 1
                stats["bad"] += 1 if rec.get("bad") else 0
                out.write(json.dumps(rec) + "\n")
                out.flush()
                if rec.get("bad"):
                    print("BAD", json.dumps(rec), flush=True)

    with cf.ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, range(a.workers)))
    guard.stop = True
    print(json.dumps({"requests": stats["n"], "bad": stats["bad"], "guard_events": guard.events[-10:]}), flush=True)


if __name__ == "__main__":
    main()
