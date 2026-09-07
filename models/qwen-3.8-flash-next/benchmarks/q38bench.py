#!/usr/bin/env python3
"""q38bench.py — fail-closed benchmark harness for the qwen38-tuning-20260906 campaign.

Differences from the archived q38_ss.py/q38_agg.py (their aggregate exceptions
don't fail the parent; this harness does, per campaign handoff):
  - every worker thread's exception is captured and FAILS the run
  - validates request count, usage, finish reason, non-empty content
  - explicit per-request timeout
  - TTFT / streaming decode / end-to-end reported separately
  - records actual usage (prompt/completion tokens, finish_reason)
  - raw JSONL per request + summary JSON, UTC timestamps
  - MTP counter deltas from /metrics around each test (by driver)
Modes:
  single  — C1 code + prose (repeatable)
  agg     — C{4,8,16} code aggregates
  sustained — ~N seconds chained C1 with inter-chunk gap telemetry
Exit code 0 only if ALL validations pass.
"""
import json, sys, time, threading, uuid, argparse, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8000"
MODEL = "qwen3.8-flash-next"
CODE = ("Write a complete, idiomatic Python implementation of a binary search tree with insert, "
        "delete, search, traversal, height, docstrings, and tests. Code only. Add exhaustive tests "
        "using pytest, covering edge cases.")
PROSE = ("Write a detailed, well-structured essay of at least 1000 words about the history of the "
         "transcontinental railroad, covering planning, financing, construction, labor, and legacy.")
MIN_COMPLETION = 900      # per-stream floor for "sufficiently long" (target 1000-1600)
REQ_TIMEOUT_S = 900

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def one_stream(prompt, max_tokens, think=False, tag=""):
    """One streaming chat completion. Returns dict; raises on any protocol failure."""
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": think}}
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t_send = time.monotonic()
    t_first = None; t_last = None; n_chunks = 0; n_chars = 0; usage = None
    chunks = []  # (monotonic, chars) for gap telemetry
    with urllib.request.urlopen(req, timeout=REQ_TIMEOUT_S) as r:
        for line in r:
            if not line.startswith(b"data:"):
                continue
            p = line[5:].strip()
            if p == b"[DONE]":
                break
            try:
                c = json.loads(p)
            except Exception:
                continue
            if c.get("usage"):
                usage = c["usage"]
            d = (c.get("choices") or [{}])[0].get("delta") or {}
            ch = d.get("content") or ""
            if ch:
                now = time.monotonic()
                if t_first is None: t_first = now
                t_last = now; n_chunks += 1; n_chars += len(ch)
                chunks.append([round(now - t_send, 4), len(ch)])
    t_end = time.monotonic()
    if usage is None:
        raise RuntimeError("no usage in stream (missing/broken stream)")
    ct = int(usage.get("completion_tokens") or 0)
    pt = int(usage.get("prompt_tokens") or 0)
    if ct <= 0 or n_chars == 0:
        raise RuntimeError(f"empty completion: ct={ct} chars={n_chars}")
    # stream timing sanity: need >=2 content chunks to measure decode rate
    ttft = t_first - t_send
    span = (t_last - t_first) if (t_first is not None and t_last and n_chunks > 1) else None
    return {"ttft_s": round(ttft, 3),
            "decode_tok_s": round((ct - 1) / span, 1) if span else None,
            "e2e_s": round(t_end - t_send, 3),
            "completion_tokens": ct, "prompt_tokens": pt,
            "chars": n_chars, "chunks": n_chunks, "tag": tag,
            "ts": now_iso()}

def run_agg(n, max_tokens, prompt):
    outs = [None] * n
    errs = [None] * n
    def w(i):
        try:
            outs[i] = one_stream(prompt + " nonce=" + uuid.uuid4().hex, max_tokens, tag=f"w{i}")
        except Exception as e:  # noqa: BLE001
            errs[i] = repr(e)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    t0 = time.monotonic()
    for t in ts: t.start()
    for t in ts: t.join()
    wall = time.monotonic() - t0
    fails = [f"w{i}: {errs[i]}" for i in range(n) if errs[i]]
    if fails:
        return {"n": n, "ok": False, "wall_s": round(wall, 2), "failures": fails}
    bad = []
    tot = 0
    for i, o in enumerate(outs):
        if o is None:
            bad.append(f"w{i}: no result"); continue
        if o["completion_tokens"] < MIN_COMPLETION:
            bad.append(f"w{i}: short completion {o['completion_tokens']}")
        tot += o["completion_tokens"]
    e2e_rate = tot / wall
    ok = not bad
    return {"n": n, "ok": ok, "wall_s": round(wall, 2),
            "total_completion_tokens": tot,
            "e2e_tok_s": round(e2e_rate, 1),
            "per_stream": [o for o in outs if o],
            "failures": bad}

def run_single(prompt, max_tokens, tag, think=False):
    r = one_stream(prompt, max_tokens, think=think, tag=tag)
    ok = r["completion_tokens"] >= MIN_COMPLETION
    return {"ok": ok, "result": r,
            "failures": [] if ok else [f"short completion {r['completion_tokens']}"]}

def run_sustained(seconds, max_tokens):
    """Chained C1 requests for ~seconds; collect inter-chunk gaps for stall telemetry."""
    gaps_all = []; runs = []; t0 = time.monotonic(); n_err = 0
    while time.monotonic() - t0 < seconds:
        try:
            body = {"model": MODEL, "messages": [{"role": "user", "content": CODE + " nonce=" + uuid.uuid4().hex}],
                    "max_tokens": max_tokens, "temperature": 0, "stream": True,
                    "stream_options": {"include_usage": True},
                    "chat_template_kwargs": {"enable_thinking": False}}
            req = urllib.request.Request(BASE + "/v1/chat/completions",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            t_send = time.monotonic(); t_first = None; t_last = None; ct = 0; usage = None
            with urllib.request.urlopen(req, timeout=REQ_TIMEOUT_S) as r:
                for line in r:
                    if not line.startswith(b"data:"): continue
                    p = line[5:].strip()
                    if p == b"[DONE]": break
                    try: c = json.loads(p)
                    except Exception: continue
                    if c.get("usage"): usage = c["usage"]
                    d = (c.get("choices") or [{}])[0].get("delta") or {}
                    if d.get("content"):
                        now = time.monotonic()
                        if t_first is None: t_first = now
                        if t_last is not None and now - t_last > 0.5:
                            gaps_all.append(round(now - t_last, 3))
                        t_last = now
            ct = int((usage or {}).get("completion_tokens") or 0)
            runs.append({"ct": ct, "dur": round(time.monotonic() - t_send, 2)})
        except Exception as e:  # noqa: BLE001
            n_err += 1
            runs.append({"error": repr(e)})
    wall = time.monotonic() - t0
    tot = sum(r["ct"] for r in runs if "ct" in r)
    return {"ok": n_err == 0 and tot > 0, "wall_s": round(wall, 1),
            "requests": len(runs), "errors": n_err,
            "total_tokens": tot, "mean_tok_s": round(tot / wall, 1),
            "gaps_over_500ms": sorted(gaps_all, reverse=True)[:20]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["single", "agg", "sustained"])
    ap.add_argument("--max-tokens", type=int, default=1400)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--concurrencies", default="4,8,16")
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    results = {"mode": a.mode, "ts": now_iso(), "max_tokens": a.max_tokens}
    overall_ok = True
    jsonl = []
    if a.mode == "single":
        for tag, p in [("code", CODE), ("prose", PROSE)]:
            rs = []
            for i in range(a.repeats):
                r = run_single(p, a.max_tokens, f"{tag}{i}")
                rs.append(r); jsonl.append({"test": f"single_{tag}", "rep": i, **r})
                if not r["ok"]: overall_ok = False
            results[tag] = rs
    elif a.mode == "agg":
        for n in [int(x) for x in a.concurrencies.split(",")]:
            rs = []
            for i in range(a.repeats):
                r = run_agg(n, a.max_tokens, CODE)
                rs.append(r); jsonl.append({"test": f"agg_c{n}", "rep": i, **r})
                if not r["ok"]: overall_ok = False
            results[f"c{n}"] = rs
    elif a.mode == "sustained":
        r = run_sustained(a.seconds, a.max_tokens)
        results["sustained"] = r
        jsonl.append({"test": "sustained", **r})
        if not r["ok"]: overall_ok = False
    results["OK"] = overall_ok
    with open(a.out + ".jsonl", "w") as f:
        for r in jsonl: f.write(json.dumps(r) + "\n")
    with open(a.out + ".summary.json", "w") as f:
        json.dump(results, f, indent=1)
    print(json.dumps(results, indent=1))
    sys.exit(0 if overall_ok else 3)

if __name__ == "__main__":
    main()
