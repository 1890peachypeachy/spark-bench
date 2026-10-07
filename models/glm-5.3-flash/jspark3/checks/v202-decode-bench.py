#!/usr/bin/env python3
"""Idle-gated streamed decode benchmark — jspark3 v2.0.2 TP3.

Closes the open item from the 2026-10-04 swap: jspark3 decode speed was never
measured against the Mia TensorFold TP3 baseline (2026-10-02, idle-gated,
streamed: code 104.1 / prose 71.9 tok/s).

Discipline (lane skill):
- Time decode from STREAMED content deltas, never a non-streamed wall-clock:
  (tokens-1)/(t_last_delta - t_first_delta). Non-streamed timing includes
  prefill+TTFT and reads a healthy lane ~35% slow.
- Gate on an idle lane BEFORE and DURING each run; the endpoint is shared.
- temp 0, warm first, bounded tokens.

CAVEAT recorded with the numbers: v2.0.2 has reasoning ALWAYS ON (known issue
9 — no reasoning setting runs High, a request to disable it is treated as low).
The Mia baseline was measured with thinking OFF. So we separate reasoning-phase
tokens from visible-answer tokens and report visible-text decode, which is the
closest honest comparison; it is still not a same-conditions claim.
"""
import json, time, urllib.request

BASE = "http://100.99.120.29:8888"
MODEL = "GLM-5.3-Flash-EXL3"

PROSE = ("Write a plain-English paragraph explaining why distributing one large "
         "language model across three machines can decode more slowly than "
         "running a smaller model on one machine. No lists, just prose.")
CODE = ("Write a single Python function `merge_intervals(intervals)` that merges "
        "overlapping closed intervals and returns them sorted. Include a short "
        "docstring. Code only, no explanation.")


def idle():
    try:
        with urllib.request.urlopen(f"{BASE}/metrics", timeout=20) as r:
            txt = r.read().decode()
    except Exception as e:
        return None, f"metrics unavailable: {e}"
    run = wait = None
    for line in txt.splitlines():
        if line.startswith("vllm:num_requests_running"):
            run = float(line.split()[-1])
        elif line.startswith("vllm:num_requests_waiting"):
            wait = float(line.split()[-1])
    return (run, wait), None


def stream(prompt, max_tokens, effort=None):
    """Return timing split by reasoning vs visible content deltas."""
    payload = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
               "stream": True, "stream_options": {"include_usage": True},
               "messages": [{"role": "user", "content": prompt}]}
    if effort:
        payload["reasoning_effort"] = effort
    req = urllib.request.Request(
        f"{BASE}/v1/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})

    t0 = time.perf_counter()
    r_first = r_last = c_first = c_last = None
    n_reason = n_content = 0
    usage = None
    text = []
    with urllib.request.urlopen(req, timeout=900) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except json.JSONDecodeError:
                continue
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices", []) or []:
                d = ch.get("delta") or {}
                now = time.perf_counter()
                rc = d.get("reasoning_content")
                if rc:
                    n_reason += 1
                    r_first = r_first or now
                    r_last = now
                cc = d.get("content")
                if cc:
                    n_content += 1
                    c_first = c_first or now
                    c_last = now
                    text.append(cc)
    return {
        "ttft_s": (r_first or c_first or time.perf_counter()) - t0,
        "visible_ttft_s": (c_first - t0) if c_first else None,
        "reason_deltas": n_reason,
        "content_deltas": n_content,
        "visible_decode_tps": ((n_content - 1) / (c_last - c_first))
                              if (c_first and c_last and c_last > c_first) else None,
        "reason_decode_tps": ((n_reason - 1) / (r_last - r_first))
                             if (r_first and r_last and r_last > r_first) else None,
        "usage": usage,
        "text": "".join(text),
    }


print("gate:", idle())
print("warming")
stream(PROSE, 64)
stream(CODE, 64)

BASELINE = {"prose": 71.9, "code": 104.1}
rows = []
for label, prompt in (("prose", PROSE), ("code", CODE)):
    for attempt in (1, 2):
        g, err = idle()
        if g and (g[0] > 0 or g[1] > 0):
            print(f"  !! lane NOT idle before {label}#{attempt}: running={g[0]} "
                  f"waiting={g[1]} — result would be contaminated")
        res = stream(prompt, 400)
        g2, _ = idle()
        rows.append((label, attempt, res, g2))
        v = res["visible_decode_tps"]
        print(f"{label}#{attempt}: visible_decode={v and round(v,1)} tok/s  "
              f"ttft={res['ttft_s']:.3f}s visible_ttft="
              f"{res['visible_ttft_s'] and round(res['visible_ttft_s'],3)}s  "
              f"reason_deltas={res['reason_deltas']} content_deltas={res['content_deltas']}  "
              f"reason_decode={res['reason_decode_tps'] and round(res['reason_decode_tps'],1)}  "
              f"during_idle={g2}")

print("=" * 78)
print(f"{'lane':<22}{'prose tok/s':>14}{'code tok/s':>14}")
for label in ("prose", "code"):
    vs = [r[2]["visible_decode_tps"] for r in rows
          if r[0] == label and r[2]["visible_decode_tps"]]
    best = max(vs) if vs else None
    med = (sorted(vs)[len(vs) // 2] if vs else None)
    print(f"  {label}: samples={[round(v,1) for v in vs]} best={best and round(best,1)} "
          f"median={med and round(med,1)}  Mia baseline={BASELINE[label]}")
    if best:
        d = (best - BASELINE[label]) / BASELINE[label] * 100
        print(f"         vs Mia TP3 baseline: {d:+.1f}%")
print()
print("CAVEAT: reasoning is always on in v2.0.2 (known issue 9); the Mia baseline")
print("was thinking-OFF. Visible-text decode is the closest honest comparison,")
print("not a same-conditions claim.")
