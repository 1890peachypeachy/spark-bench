#!/usr/bin/env python3
"""Long-context concurrent decode: N agents, each on its own warm ~T-token context (stdlib only).

Fixed prompts (docs built from --seed), so every experiment sees the same requests:
  phase 1  warms N distinct documents one at a time (cold prefill, then kept by the prompt cache);
  phase 2  sends N concurrent turns that resume from those prefixes and decode --max-tokens (greedy by default,
           thinking on) - the way 2-4 Hermes agents sit on 64-150K contexts; repeated --reps times per level;
  phase 3  needle check: N concurrent greedy turns (thinking off) each list the 3 codes hidden in its document.
           Checks the sparse attention + indexer on the shared verify path at long context; the reply hashes let
           two builds be compared (equal hashes: the same tokens).
Prints one JSON line per row, then {"requests": n} = every request this run sent (for the contamination check).

Usage: python3 -I longctx_conc.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 \
           --ctx 64000 --conc 2,4 --max-tokens 384 --reps 2 --out res.json
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
TOPICS = ["the history of cartography", "how bridges carry load", "the chemistry of bread", "why tides happen",
          "the design of a good API", "how vaccines train immunity", "the economics of shipping",
          "how compilers optimize loops"]


def post(url, model, content, max_tokens, temperature, thinking=True):
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": temperature, "top_p": 0.95, "stream": True, "stream_options": {"include_usage": True}}
    if not thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    t_first = t_last = None
    usage, text = None, []
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            obj = json.loads(data)
            if obj.get("usage"):
                usage = obj["usage"]
            for ch in obj.get("choices") or []:
                d = ch.get("delta") or {}
                piece = (d.get("content") or "") + (d.get("reasoning_content") or d.get("reasoning") or "")
                if piece:
                    text.append(piece)
                    now = time.perf_counter()
                    if t_first is None:
                        t_first = now
                    t_last = now
    t_end = time.perf_counter()
    ctok = (usage or {}).get("completion_tokens", 0)
    ptok = (usage or {}).get("prompt_tokens", 0)
    cached = ((usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    ttft = (t_first - t0) if t_first else None
    dec = (ctok - 1) / (t_last - t_first) if (t_first and t_last and t_last > t_first and ctok > 1) else None
    return {"ptok": ptok, "cached": cached, "ctok": ctok, "ttft": ttft, "decode_tok_s": dec,
            "t0": t0, "t_first": t_first, "t_end": t_end, "text": "".join(text)}


def make_doc(n_tokens, tag):
    """~n_tokens of numbered lines, with 3 access codes at 20%, 50% and 80% depth."""
    rng = random.Random(tag)
    n_words = int(n_tokens / 1.3)  # ~1.3 tokens per word for this vocabulary
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--ctx", type=int, default=64000)
    ap.add_argument("--conc", default="2,4")
    ap.add_argument("--max-tokens", type=int, default=384)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", default="ernie55-longctx-v1")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    levels = [int(x) for x in a.conc.split(",") if x]
    n_docs = max(levels)
    docs = [make_doc(a.ctx, f"{a.seed}-{i}") for i in range(n_docs)]
    sent = 0
    out = {"ctx": a.ctx, "seed": a.seed, "temperature": a.temperature, "warm": [], "levels": [], "needle": []}
    for i, (d, _) in enumerate(docs):  # phase 1: cold prefill of each context, kept by the prompt cache
        r = post(a.url, a.model, d + "\n\nReply with the single word OK.", 8, 0.0)
        sent += 1
        r["prefill_tok_s"] = (r["ptok"] - r["cached"]) / r["ttft"] if r["ttft"] else None
        out["warm"].append({k: v for k, v in r.items() if k != "text"})
        print(json.dumps({"warm": i, "ptok": r["ptok"], "ttft_s": round(r["ttft"] or 0, 2),
                          "prefill_tok_s": round(r["prefill_tok_s"] or 0)}), flush=True)
    for c in levels:  # phase 2: concurrent long-context decode
        for rep in range(a.reps):
            def one(i):
                q = f"\n\nUsing the document above only as background, write a detailed essay about {TOPICS[i % 8]}."
                return post(a.url, a.model, docs[i][0] + q, a.max_tokens, a.temperature)
            t0 = time.perf_counter()
            with cf.ThreadPoolExecutor(c) as ex:
                rs = list(ex.map(one, range(c)))
            wall = time.perf_counter() - t0
            sent += c
            toks = sum(r["ctok"] for r in rs)
            decs = sorted(r["decode_tok_s"] for r in rs if r["decode_tok_s"])
            t_all = max(r["t_first"] for r in rs if r["t_first"])
            t_stop = max(r["t_end"] for r in rs)
            row = {"concurrency": c, "rep": rep, "wall_s": round(wall, 2), "completion_tokens": toks,
                   "aggregate_tok_s": round(toks / wall, 1),
                   "per_stream_decode_median": round(decs[len(decs) // 2], 1) if decs else None,
                   "per_stream_decode_min": round(decs[0], 1) if decs else None,
                   "ttft_max_s": round(max(r["ttft"] or 0 for r in rs), 2),
                   "cached_min": min(r["cached"] for r in rs), "ptok_max": max(r["ptok"] for r in rs),
                   "decode_window_s": round(t_stop - t_all, 2),
                   "sha": [hashlib.sha1(r["text"].encode()).hexdigest()[:10] for r in rs]}
            out["levels"].append(row)
            print(json.dumps(row), flush=True)

    def needle(i):  # phase 3: every stream at once, greedy, thinking off
        q = "\n\nList the three access codes given in the document above, in order, codes only."
        return post(a.url, a.model, docs[i][0] + q, 128, 0.0, thinking=False)
    with cf.ThreadPoolExecutor(n_docs) as ex:
        rs = list(ex.map(needle, range(n_docs)))
    sent += n_docs
    for i, r in enumerate(rs):
        found = sum(cd in r["text"] for cd in docs[i][1])
        row = {"needle": i, "found": found, "ok": found == 3, "ctok": r["ctok"],
               "sha": hashlib.sha1(r["text"].encode()).hexdigest()[:10], "reply": r["text"][:80]}
        out["needle"].append(row)
        print(json.dumps(row), flush=True)
    print(json.dumps({"needle_ok": sum(x["ok"] for x in out["needle"]), "of": n_docs}), flush=True)
    out["requests"] = sent
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({"requests": sent}), flush=True)


if __name__ == "__main__":
    main()
