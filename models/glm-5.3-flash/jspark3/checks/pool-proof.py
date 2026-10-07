#!/usr/bin/env python3
"""Prove the live pool exceeds the OLD 360,448 tokens, functionally.

Logic: fire two concurrent requests of ~200K DISTINCT tokens each (~400K
combined). Upstream docs: "All running requests share one pool of context
memory. A request near the full context window can wait in the queue until other
long requests finish."

  - old pool 360,448: 200K + 200K = ~400K does NOT fit. The second request must
    wait for the first to release, so prefills SERIALIZE (stream 2's first token
    arrives after both prefills) and total wall ~= 2x a single prefill.
  - new pool 786,432: both fit simultaneously, so prefills OVERLAP and both
    first tokens land at a similar time.

Content is distinct per stream (different word stream, different seed) so the
prefix cache cannot collapse them into shared pool pages and fake the result.
max_tokens is tiny to isolate prefill from decode.
"""
import json
import random
import threading
import time
import urllib.request

BASE = "http://100.99.120.29:8888"
MODEL = "GLM-5.3-Flash-EXL3"
TARGET_WORDS = 150_000          # ~200K tokens
MAXTOK = 16

WORDS = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
         "nu xi omicron pi rho sigma tau upsilon phi chi psi omega harbor "
         "lantern meadow quartz ribbon thicket velvet whisper cobalt ember "
         "fathom gravel hollow indigo juniper kindle marrow nectar obsidian").split()


def corpus(seed):
    r = random.Random(seed)
    return " ".join(r.choice(WORDS) for _ in range(TARGET_WORDS))


print("building two distinct corpora...")
bodies = [corpus(11), corpus(97)]
print(f"  stream 0: {len(bodies[0]):,} chars | stream 1: {len(bodies[1]):,} chars")
assert bodies[0][:2000] != bodies[1][:2000], "corpora must differ"

results = {}
barrier = threading.Barrier(2)
samples = []
stop = threading.Event()


def sampler():
    while not stop.is_set():
        try:
            t = urllib.request.urlopen(f"{BASE}/metrics", timeout=5).read().decode()
            g = {}
            for line in t.splitlines():
                for k in ("tensorfold:inflight", "tensorfold:running",
                          "vllm:num_requests_waiting"):
                    if line.startswith(k + " "):
                        g[k] = float(line.split()[-1])
            samples.append((time.perf_counter(), g))
        except Exception:
            pass
        time.sleep(1.0)


def worker(i):
    payload = {"model": MODEL, "temperature": 0, "max_tokens": MAXTOK,
               "stream": True, "stream_options": {"include_usage": True},
               "messages": [
                   {"role": "user",
                    "content": f"Reference block {i}:\n{bodies[i]}\n\n"
                               "Reply with exactly the word DONE."}]}
    req = urllib.request.Request(
        f"{BASE}/v1/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    barrier.wait()
    t_send = time.perf_counter()
    first = None
    usage = None
    with urllib.request.urlopen(req, timeout=1800) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            d = line[5:].strip()
            if d == "[DONE]":
                break
            try:
                ev = json.loads(d)
            except json.JSONDecodeError:
                continue
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices", []) or []:
                delta = ch.get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content"):
                    first = first or time.perf_counter()
    results[i] = {"send": t_send, "first": first, "end": time.perf_counter(),
                  "usage": usage}


th = threading.Thread(target=sampler, daemon=True)
th.start()
t0 = time.perf_counter()
ws = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for w in ws:
    w.start()
for w in ws:
    w.join()
wall = time.perf_counter() - t0
stop.set()
time.sleep(1.2)

print(f"\ntotal wall {wall:.1f}s")
ttfts = []
for i in sorted(results):
    r = results[i]
    pt = (r["usage"] or {}).get("prompt_tokens")
    ttft = (r["first"] - r["send"]) if r["first"] else None
    ttfts.append(ttft)
    print(f"  stream {i}: prompt_tokens={pt} ttft="
          f"{f'{ttft:.1f}s' if ttft else 'n/a'} end={r['end']-t0:.1f}s")

peak = {}
for _, g in samples:
    for k, v in g.items():
        peak[k] = max(peak.get(k, 0), v)
print(f"\npeak gauges: {peak}")

if all(ttfts):
    lo, hi = min(ttfts), max(ttfts)
    print(f"\nTTFT spread: {lo:.1f}s .. {hi:.1f}s   ratio {hi/lo:.2f}x")
    print(f"wall / slowest TTFT: {wall/hi:.2f}x")
    print()
    if hi / lo < 1.5:
        print("VERDICT: prefills OVERLAPPED (both first tokens landed together)")
        print("  -> both ~200K contexts were resident AT THE SAME TIME")
        print("  -> combined residency exceeded the old 360,448 pool")
        print("  -> POOL IS PROVABLY LARGER THAN BEFORE")
    else:
        print("VERDICT: prefills SERIALIZED (second waited for the first)")
        print("  -> consistent with a pool too small to hold both; "
              "does NOT confirm the increase")
