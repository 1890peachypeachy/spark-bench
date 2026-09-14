#!/usr/bin/env python3
"""Raw-decode concurrency sweep for the qwen38fn lane (v3 verification).

For each concurrency level: fire N worker threads that each send ONE chat request
(512 max_tokens, temp 0.6, top_p 0.95, thinking off), measure wall time from first
request sent to last request finished. Reports aggregate tok/s (= all completion
tokens / wall) and per-stream tok/s (= aggregate / concurrency).

Usage: sweep-decode.py --endpoint http://100.71.248.116:8000/v1 --model qwen3.8-flash-next-spark12 --out sweep-v3.json
"""
import argparse, json, threading, time, urllib.request

PROMPT = ("Write a detailed technical explanation of how speculative decoding works, "
          "covering draft models, acceptance criteria, and throughput tradeoffs.")

def one_request(endpoint, model, max_tokens, results, idx):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.6,
        "top_p": 0.95,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    wall = time.time() - t0
    comp = d["usage"]["completion_tokens"]
    results[idx] = {"completion_tokens": comp, "wall_s": round(wall, 2),
                    "tok_s": round(comp / wall, 1), "finish": d["choices"][0]["finish_reason"]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--levels", default="1,2,4,8")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = {"endpoint": args.endpoint, "model": args.model, "max_tokens": args.max_tokens, "levels": {}}
    for c in [int(x) for x in args.levels.split(",")]:
        results = {}
        threads = [threading.Thread(target=one_request, args=(args.endpoint, args.model, args.max_tokens, results, i)) for i in range(c)]
        t0 = time.time()
        for t in threads: t.start()
        for t in threads: t.join()
        wall = time.time() - t0
        tot = sum(r["completion_tokens"] for r in results.values())
        lvl = {"wall_s": round(wall, 2), "aggregate_tok_s": round(tot / wall, 1),
               "per_stream_tok_s": round(tot / wall / c, 1),
               "streams": results}
        out["levels"][str(c)] = lvl
        print(f"c={c}: aggregate {lvl['aggregate_tok_s']} tok/s, per-stream {lvl['per_stream_tok_s']} tok/s, wall {lvl['wall_s']}s")
    json.dump(out, open(args.out, "w"), indent=1)
    print("SAVED", args.out)

if __name__ == "__main__":
    main()
