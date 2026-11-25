"""Greedy outputs for an equivalence check: 8 fixed prompts, temperature 0, 256 tokens, thinking on. Saves text + usage.
    python3 -I equiv.py NAME        -> logs/NAME.equiv.json
    python3 -I equiv.py --cmp A B   -> per-prompt: identical? first differing character, and shared-prefix length
"""
import json, sys, urllib.request

API = "http://127.0.0.1:8888/v1/chat/completions"
PROMPTS = [
    "Write a Python function that merges two sorted lists, with a docstring.",
    "Explain what a hash table is to a new programmer in one paragraph.",
    "List the planets of the solar system in order from the sun.",
    "What is 1234 * 5678? Show the steps.",
    "Translate into French: The library opens at nine and closes at five.",
    "Give three tips for writing clear commit messages.",
    "Write a SQL query that returns the ten most recent orders per customer.",
    "Summarise the plot of Romeo and Juliet in three sentences.",
]

def run(name):
    out = []
    for p in PROMPTS:
        body = {"model": "GLM-5.3-Flash-EXL3", "messages": [{"role": "user", "content": p}], "max_tokens": 256,
                "temperature": 0.0, "seed": 1234, "logprobs": True, "top_logprobs": 5}
        req = urllib.request.Request(API, json.dumps(body).encode(), {"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=600))
        m = d["choices"][0]["message"]
        lp = ((d["choices"][0].get("logprobs") or {}).get("content") or [])
        out.append({"reasoning": m.get("reasoning") or m.get("reasoning_content") or "", "content": m.get("content") or "",
                    "usage": d["usage"], "finish": d["choices"][0]["finish_reason"],
                    "tokens": [[t["token"], round(t["logprob"], 4), [[a["token"], round(a["logprob"], 4)] for a in t.get("top_logprobs", [])[:3]]]
                               for t in lp]})
    json.dump(out, open(f"logs/{name}.equiv.json", "w"), indent=1)
    print(f"saved logs/{name}.equiv.json")

def cmp(a, b):
    A, B = json.load(open(f"logs/{a}.equiv.json")), json.load(open(f"logs/{b}.equiv.json"))
    same = 0
    # token-level: first differing generated token and the top-2 gap there in each run (a near-tie flip is not a bug)
    for i, (x, y) in enumerate(zip(A, B)):
        tx, ty = x.get("tokens") or [], y.get("tokens") or []
        k = next((j for j in range(min(len(tx), len(ty))) if tx[j][0] != ty[j][0]), None)
        if tx and ty and k is not None:
            gap = lambda t: round(t[k][2][0][1] - t[k][2][1][1], 4) if len(t[k][2]) > 1 else None
            print(f"  prompt {i}: first differing token #{k}: {tx[k][0]!r} vs {ty[k][0]!r}; top1-top2 gap {gap(tx)} / {gap(ty)} nats;"
                  f" top3 A {tx[k][2]} B {ty[k][2]}")
    for i, (x, y) in enumerate(zip(A, B)):
        tx, ty = x["reasoning"] + "\x00" + x["content"], y["reasoning"] + "\x00" + y["content"]
        if tx == ty:
            same += 1; print(f"  prompt {i}: identical ({len(tx)} chars)"); continue
        k = next((j for j in range(min(len(tx), len(ty))) if tx[j] != ty[j]), min(len(tx), len(ty)))
        print(f"  prompt {i}: DIFFER at char {k} of {len(tx)}/{len(ty)}: ...{tx[max(0,k-30):k+20]!r} vs ...{ty[max(0,k-30):k+20]!r}")
    print(f"identical {same}/{len(A)}")

if __name__ == "__main__":
    if sys.argv[1] == "--cmp":
        cmp(sys.argv[2], sys.argv[3])
    else:
        run(sys.argv[1])
