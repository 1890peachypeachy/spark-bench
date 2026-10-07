#!/usr/bin/env python3
"""Does the jspark3 lane actually serve requests concurrently?

Motivation: /metrics reports vllm:num_requests_running=1 with
num_requests_waiting>=1 more or less permanently, which READS like a lane
serializing every request. But the same endpoint also exports
tensorfold:inflight, which was 3 at the same moment. One of those gauges is
lying about concurrency; this settles it from the client side.

Method: fire N streaming requests from a barrier and record, per stream, the
absolute time of its first and last token. If the engine serializes, the
intervals are disjoint and total wall ~= sum of individual walls. If it batches,
the intervals overlap heavily and total wall ~= the slowest single stream.
Also samples both gauges on a thread for the duration.
"""
import json, threading, time, urllib.request

BASE = "http://100.99.120.29:8888"
MODEL = "GLM-5.3-Flash-EXL3"
N = 3
MAXTOK = 160

PROMPTS = [
    "Count from 1 to 60, one number per line.",
    "List 60 common English nouns, one per line, no numbering.",
    "Write 60 short lines each naming a different colour.",
]

samples = []
stop = threading.Event()


def sampler():
    while not stop.is_set():
        try:
            t = urllib.request.urlopen(f"{BASE}/metrics", timeout=5).read().decode()
            g = {}
            for line in t.splitlines():
                for k in ("tensorfold:inflight", "tensorfold:running",
                          "vllm:num_requests_running", "vllm:num_requests_waiting"):
                    if line.startswith(k + " "):
                        g[k] = float(line.split()[-1])
            samples.append((time.perf_counter(), g))
        except Exception:
            pass
        time.sleep(0.4)


results = {}
barrier = threading.Barrier(N)


def worker(i):
    payload = {"model": MODEL, "temperature": 0, "max_tokens": MAXTOK,
               "stream": True, "stream_options": {"include_usage": True},
               "messages": [{"role": "user", "content": PROMPTS[i % len(PROMPTS)]}]}
    req = urllib.request.Request(
        f"{BASE}/v1/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    barrier.wait()
    t_send = time.perf_counter()
    first = last = None
    ntok = 0
    usage = None
    with urllib.request.urlopen(req, timeout=900) as resp:
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
                if delta.get("content") or delta.get("reasoning_content") \
                        or delta.get("reasoning"):
                    now = time.perf_counter()
                    first = first or now
                    last = now
                    ntok += 1
    results[i] = {"send": t_send, "first": first, "last": last,
                  "deltas": ntok, "usage": usage}


th = threading.Thread(target=sampler, daemon=True)
th.start()
t0 = time.perf_counter()
ws = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
for w in ws:
    w.start()
for w in ws:
    w.join()
wall = time.perf_counter() - t0
stop.set()
time.sleep(0.6)

print(f"N={N} streams, total wall {wall:.2f}s")
spans = []
for i in sorted(results):
    r = results[i]
    if not r["first"]:
        print(f"  stream {i}: no tokens")
        continue
    s, e = r["first"] - t0, r["last"] - t0
    spans.append((s, e))
    ct = (r["usage"] or {}).get("completion_tokens")
    print(f"  stream {i}: ttft={r['first']-r['send']:>6.2f}s  "
          f"active {s:>6.2f}s -> {e:>6.2f}s  ({e-s:>5.2f}s)  "
          f"deltas={r['deltas']:>4} completion_tokens={ct}")

# pairwise overlap
print()
tot_individual = sum(e - s for s, e in spans)
ov = 0.0
for a in range(len(spans)):
    for b in range(a + 1, len(spans)):
        s = max(spans[a][0], spans[b][0])
        e = min(spans[a][1], spans[b][1])
        if e > s:
            ov += e - s
            print(f"  streams {a}&{b} overlap {e-s:.2f}s")
if not ov:
    print("  NO pairwise overlap detected")

union = max(e for _, e in spans) - min(s for s, _ in spans) if spans else 0
print()
print(f"sum of individual decode spans : {tot_individual:.2f}s")
print(f"union (wall) of decode spans   : {union:.2f}s")
if union > 0:
    print(f"concurrency factor (sum/union) : {tot_individual/union:.2f}x  "
          f"(~1.0 = serialized, ~{N}.0 = fully parallel)")

print()
peak = {}
for _, g in samples:
    for k, v in g.items():
        peak[k] = max(peak.get(k, 0), v)
print("peak gauges during the run:")
for k in ("tensorfold:inflight", "tensorfold:running",
          "vllm:num_requests_running", "vllm:num_requests_waiting"):
    print(f"  {k:<32} {peak.get(k)}")
