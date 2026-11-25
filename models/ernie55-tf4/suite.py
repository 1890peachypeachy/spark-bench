"""ERNIE TF lane regression + speed suite. Usage: python3 suite.py <tag> [quick]; writes suite_<tag>.json."""
import sys, json, time
sys.path.insert(0, "/Users/agent/.hermes/profiles/spark/cache/scratch")
import ebench as B

tag = sys.argv[1]
quick = len(sys.argv) > 2
out = {"tag": tag, "t": time.strftime("%H:%M:%S")}


def note(k, v):
    out[k] = v
    print(k, json.dumps(v, default=str)[:260], flush=True)
    json.dump(out, open(f"/Users/agent/.hermes/profiles/spark/cache/scratch/suite_{tag}.json", "w"), default=str, indent=1)


# correctness first
dt, d, e = B.call([{"role": "user", "content": "What is 17*23+9? Answer with the number only."}], 300)
note("math", e or d["choices"][0]["message"]["content"])
doc = B.filler(6000, seed=11)
q1 = [{"role": "user", "content": doc + "\n\nList the first 12 words of the text above, then say DONE."}]
want = " ".join(doc.split()[:12])
r = []
for i in range(2):
    dt, d, e = B.call(q1, 120, dict(B.NT, temperature=0))
    r.append(e or {"s": round(dt, 2), "cached": d["usage"]["prompt_tokens_details"], "ok": want in d["choices"][0]["message"]["content"], "text": d["choices"][0]["message"]["content"]})
note("cache_cold", r[0])
note("cache_warm", r[1])
note("cache_identical", isinstance(r[0], dict) and isinstance(r[1], dict) and r[0]["text"] == r[1]["text"])
# prefill throughput
for n in ([3000, 12000] if quick else [3000, 12000, 30000, 60000]):
    note(f"prefill_{n}w", B.prefill(n, seed=n))
note("prose", B.decode(B.PROSE, 300))
note("code", B.decode(B.CODE, 500))
if not quick:
    note("c4", B.conc(4))
tools = [{"type": "function", "function": {"name": "get_weather", "description": "Get weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
dt, d, e = B.call([{"role": "user", "content": "What's the weather in Tokyo? Use the tool."}], 400, {"tools": tools})
note("tool", e or [d["choices"][0]["finish_reason"], d["choices"][0]["message"].get("tool_calls")])
