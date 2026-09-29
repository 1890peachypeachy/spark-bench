#!/usr/bin/env python3
"""Minimal c1 decode screen: streaming decode tok/s (TTFT excluded), temp 0.

Same script is run against the old and the new lane so the before/after is
apples-to-apples. Not rigmark: upstream's absolute numbers are not comparable,
only our own before/after is.
"""
import argparse
import json
import statistics
import threading
import time
import urllib.request

PROMPTS = {
    "prose": "Write a clear five-paragraph explanation of how solid-state drives wear out over time, "
             "aimed at a technically literate reader who is not a storage engineer.",
    "code":  "Write a complete Python module that implements a thread-safe LRU cache with a TTL per entry, "
             "including docstrings and a small unittest suite at the bottom.",
    "structured": "Produce a JSON array of 12 objects describing fictional server nodes. Each object must have "
                  "keys: hostname, rack, cpu_cores, ram_gb, role, commissioned (ISO date). Output only JSON.",
}


def requests_running(base):
    """Concurrent requests on the lane, or -1 if /metrics is unreadable.

    Required for c1: with GLM's batch-uniform speculative mode, ONE extra
    concurrent request drops the whole batch from 7 drafts to 5, and a "c1"
    sample taken next to live traffic reads 1.6-1.8x low.
    """
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/metrics", timeout=5) as r:
            for line in r.read().decode().splitlines():
                if line.startswith("vllm:num_requests_running{"):
                    return float(line.split()[-1])
    except Exception:
        return -1.0
    return -1.0


def wait_for_idle(base, tries=45, delay=4.0):
    """Block until the lane is idle so a c1 sample is really c1."""
    for _ in range(tries):
        if requests_running(base) == 0.0:
            return True
        time.sleep(delay)
    return False


class ConcurrencyWatch:
    """Poll /metrics during a sample and remember the peak concurrency.

    Checking only before/after misses traffic that joins AND leaves inside the
    sample window, which still cut the draft length for part of the decode.
    """

    def __init__(self, base, interval=1.0):
        self.base = base
        self.interval = interval
        self.peak = 0.0
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            n = requests_running(self.base)
            if n > self.peak:
                self.peak = n
            self._stop.wait(self.interval)

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        return False


def run_one(base, model, kind, max_tokens, effort):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPTS[kind]}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if effort:
        body["chat_template_kwargs"] = {"reasoning_effort": effort}
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    first = None
    last = None
    n = 0
    usage_tokens = None
    text_parts = []
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if ev.get("usage"):
                usage_tokens = ev["usage"].get("completion_tokens")
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                # GLM-5.3-Flash streams thinking tokens under "reasoning" (vLLM) or
                # "reasoning_content" (some builds); both are real generated tokens and
                # must start the decode window, or the rate is wildly inflated.
                piece = (d.get("content") or d.get("reasoning")
                         or d.get("reasoning_content") or "")
                if piece:
                    now = time.perf_counter()
                    if first is None:
                        first = now
                    last = now
                    n += 1
                    text_parts.append(piece)
    if first is None or last is None or last <= first:
        return None
    decode_s = last - first
    chunks = n
    toks = usage_tokens if usage_tokens else chunks
    # decode rate measured over the inter-token window (first token excluded)
    rate = (toks - 1) / decode_s if toks > 1 else 0.0
    return {
        "kind": kind,
        "decode_tok_s": round(rate, 1),
        "completion_tokens": toks,
        "stream_chunks": chunks,
        "ttft_s": round(first - t0, 2),
        "decode_s": round(decode_s, 2),
        "text": "".join(text_parts),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-tokens", type=int, default=600)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--effort", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--allow-busy", action="store_true",
                    help="measure without waiting for an idle lane; results are not c1")
    ap.add_argument("--max-attempts", type=int, default=6,
                    help="attempts per wanted sample before giving up on a clean c1")
    args = ap.parse_args()

    for _ in range(args.warmup):
        run_one(args.base, args.model, "prose", 128, args.effort)

    records = []
    discarded = 0
    for kind in ("prose", "code", "structured"):
        kept = 0
        for _ in range(args.repeat * args.max_attempts):
            if kept >= args.repeat:
                break
            if not args.allow_busy and not wait_for_idle(args.base):
                print(f"{kind}: no idle window found; skipping (use --allow-busy to "
                      f"measure anyway, but the result is NOT c1)", flush=True)
                break
            with ConcurrencyWatch(args.base) as watch:
                rec = run_one(args.base, args.model, kind, args.max_tokens, args.effort)
            if not rec:
                continue
            # Our own request counts as 1, so anything above that is foreign traffic.
            rec["peak_concurrent"] = watch.peak
            rec["concurrent_after"] = requests_running(args.base)
            # Traffic that overlapped ANY part of the sample makes this c2+, not c1:
            # batch-uniform spec decode cut the draft length, so the rate reads low.
            if not args.allow_busy and (watch.peak > 1 or rec["concurrent_after"] > 0):
                discarded += 1
                print(f"{kind:11s} {rec['decode_tok_s']:7.1f} tok/s  DISCARDED "
                      f"(peak concurrency {watch.peak:.0f} -> not c1)", flush=True)
                continue
            records.append(rec)
            kept += 1
            print(f"{kind:11s} {rec['decode_tok_s']:7.1f} tok/s  "
                  f"({rec['completion_tokens']} tok, ttft {rec['ttft_s']}s)", flush=True)
        if kept < args.repeat:
            print(f"{kind}: only {kept}/{args.repeat} clean c1 samples obtained", flush=True)

    print("\n=== median c1 decode tok/s ===")
    summary = {}
    for kind in ("prose", "code", "structured"):
        vals = [r["decode_tok_s"] for r in records if r["kind"] == kind]
        if vals:
            summary[kind] = round(statistics.median(vals), 1)
            print(f"{kind:11s} {summary[kind]}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"summary": summary, "records": records}, f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
