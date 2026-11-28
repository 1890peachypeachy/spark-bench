#!/usr/bin/env python3
"""Agent-replay prompt-cache test: long-context agents taking turns, as Hermes agents do (stdlib only).

Each agent holds one conversation: a long first message (its working document, --sizes tokens), then turns that
append the server's reply and a tool-output message of 2-7K tokens, with "tool time" pauses between turns. Agents
start staggered and run concurrently, so 1-4 are mid-turn at a time.
- Branch-back: after turn --branch-turn, each agent also sends its PREVIOUS turn's prompt plus a different question
  (a forked subagent or side question from an older point of the conversation). Under cache pressure the store
  evicts such superseded ancestors first, so this is the case that misses.
- Side-calls: a separate thread sends a cold, unrelated 30-45K prompt every --side-every seconds (summaries,
  compaction calls), adding pressure like real background work.
Greedy, thinking off, fixed seeds: two arms send the same requests. A warm turn "hits" when the server resumed it at
or past the previous prompt's end (cached >= previous prompt - 256, the 128-token grid); "miss" when it resumed
below half of that.

Usage: python3 -I agent_replay.py --url http://127.0.0.1:8888 --out replay.json [--agents 4 --turns 12]
       python3 -I agent_replay.py --dry-run   (prints the planned sizes, sends nothing)
"""
import argparse
import json
import random
import statistics as st
import threading
import time
import urllib.request

WORDS = ("alpha river stone cloud ember quartz maple orbit cedar delta falcon harbor iris juniper kepler lumen "
         "meadow nickel onyx prism quill raven sierra tundra umber violet willow xenon yarrow zephyr").split()
TOK_PER_WORD = 1.55  # measured on this vocabulary with numbered lines (64K target words gave 76.3K tokens at 1.3)
SYSTEM = "You are a careful engineering agent. Answer briefly and precisely."


def text_of(n_tokens, rng):
    n_words, lines, words, i = int(n_tokens / TOK_PER_WORD), [], 0, 0
    while words < n_words:
        k = rng.randint(8, 16)
        lines.append(f"{i}. " + " ".join(rng.choice(WORDS) for _ in range(k)) + ".")
        words += k + 1
        i += 1
    return "\n".join(lines)


def post(url, model, messages, max_tokens):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.0, "stream": True,
            "stream_options": {"include_usage": True}, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    t1, usage, out = None, {}, []
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            obj = json.loads(line[5:].strip())
            if obj.get("usage"):
                usage = obj["usage"]
            for ch in obj.get("choices") or []:
                piece = (ch.get("delta") or {}).get("content") or ""
                if piece:
                    if t1 is None:
                        t1 = time.perf_counter()
                    out.append(piece)
    return {"text": "".join(out), "ptok": usage.get("prompt_tokens", 0),
            "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            "ctok": usage.get("completion_tokens", 0), "ttft": round((t1 or time.perf_counter()) - t0, 2),
            "s": round(time.perf_counter() - t0, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8888")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--sizes", default="48000,66000,84000,102000")
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--branch-turn", type=int, default=5)
    ap.add_argument("--stagger", type=float, default=20.0)
    ap.add_argument("--side-every", type=float, default=75.0)
    ap.add_argument("--max-tokens", type=int, default=160)
    ap.add_argument("--seed", default="ernie55-replay-v1")
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",")][: a.agents]
    plans = []
    for i, base in enumerate(sizes):
        rng = random.Random(f"{a.seed}-agent{i}")
        plans.append({"doc": text_of(base, rng), "tools": [text_of(rng.randint(2000, 7000), rng) for _ in range(a.turns)],
                      "pauses": [rng.uniform(3, 15) for _ in range(a.turns)]})
    if a.dry_run:
        for i, p in enumerate(plans):
            words = len(p["doc"].split())
            grow = sum(len(t.split()) for t in p["tools"]) * TOK_PER_WORD
            print(f"agent {i}: doc ~{int(words * TOK_PER_WORD)} tok, tool outputs +~{int(grow)} tok over {a.turns} turns")
        return
    lock = threading.Lock()
    recs, stop = [], threading.Event()

    def record(rec):
        with lock:
            recs.append(rec)
        print(json.dumps(rec), flush=True)

    def call(kind, agent, turn, msgs, expect):
        t = time.time()
        try:
            r = post(a.url, a.model, msgs, a.max_tokens)
        except Exception as e:  # keep going: a failed request is recorded, not fatal
            record({"kind": kind, "agent": agent, "turn": turn, "t": round(t, 1), "error": repr(e)[:160]})
            return None
        hit = None
        if expect:
            hit = "hit" if r["cached"] >= expect - 256 else ("miss" if r["cached"] < expect / 2 else "partial")
        record({"kind": kind, "agent": agent, "turn": turn, "t": round(t, 1), "ptok": r["ptok"], "cached": r["cached"],
                "expect": expect, "result": hit, "ttft": r["ttft"], "s": r["s"], "ctok": r["ctok"]})
        return r

    def agent(i):
        time.sleep(i * a.stagger)
        p = plans[i]
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"[agent {i}] The working log follows.\n{p['doc']}\n\nState its first line's first word."}]
        prev_ptok, prev_msgs = 0, None
        for t in range(a.turns):
            r = call("turn" if t else "cold", i, t, msgs, prev_ptok if t else 0)
            if r is None:
                return
            if t == a.branch_turn and prev_msgs is not None:  # fork from the previous turn's prompt
                call("branch", i, t, prev_msgs[:-1] + [{"role": "user", "content": prev_msgs[-1]["content"] + "\n\nSide question: name one risk."}],
                     branch_expect[i])
            branch_expect[i] = r["ptok"]
            prev_ptok, prev_msgs = r["ptok"], list(msgs)
            msgs = msgs + [{"role": "assistant", "content": r["text"] or "OK."},
                           {"role": "user", "content": f"Tool output {t + 1}:\n{p['tools'][t]}\n\nNext step, one sentence."}]
            time.sleep(p["pauses"][t])

    branch_expect = [0] * len(plans)

    def sides():
        rng = random.Random(f"{a.seed}-side")
        n = 0
        while not stop.wait(a.side_every):
            n += 1
            doc = text_of(rng.randint(30000, 45000), rng)
            call("side", -1, n, [{"role": "user", "content": f"[side {n}] {doc}\n\nSummarize in one sentence."}], 0)

    side_t = threading.Thread(target=sides, daemon=True)
    side_t.start()
    ths = [threading.Thread(target=agent, args=(i,)) for i in range(len(plans))]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    stop.set()
    side_t.join(timeout=900)

    def summ(kind):
        rs = [r for r in recs if r.get("kind") == kind and "error" not in r]
        out = {"n": len(rs), "errors": sum(1 for r in recs if r.get("kind") == kind and "error" in r)}
        if rs and kind in ("turn", "branch"):
            out.update({x: sum(r["result"] == x for r in rs) for x in ("hit", "partial", "miss")})
        if rs:
            tt = sorted(r["ttft"] for r in rs)
            out.update({"ttft_median": tt[len(tt) // 2], "ttft_p95": tt[min(len(tt) - 1, int(0.95 * len(tt)))],
                        "ttft_max": tt[-1], "ptok_max": max(r["ptok"] for r in rs)})
        if rs and kind == "turn":
            out["reprefill_tok"] = sum(max(0, r["expect"] - r["cached"]) for r in rs if r["result"] != "hit")
        return out
    summary = {k: summ(k) for k in ("cold", "turn", "branch", "side")}
    print(json.dumps({"summary": summary}), flush=True)
    if a.out:
        json.dump({"summary": summary, "requests": recs}, open(a.out, "w"), indent=1)
    print(json.dumps({"requests": len(recs)}), flush=True)


if __name__ == "__main__":
    main()
