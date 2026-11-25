"""Qualification gates for a clean build: chat + reasoning, a tool-call round trip, and needles at ~50% / ~100% of a 100K doc."""
import json, random, string, sys, time, urllib.request

API = "http://127.0.0.1:8888/v1/chat/completions"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "GLM-5.3-Flash-EXL3"

def post(body, timeout=1800):
    req = urllib.request.Request(API, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

res = {}
# 1. chat + reasoning
d = post({"model": MODEL, "messages": [{"role": "user", "content": "What is the capital of Japan? One word."}], "max_tokens": 300, "temperature": 0})
m = d["choices"][0]["message"]
res["chat"] = {"content": (m.get("content") or "").strip()[:40], "reasoning_present": bool(m.get("reasoning") or m.get("reasoning_content")),
               "ok": "tokyo" in (m.get("content") or "").lower()}

# 2. tool-call round trip
tools = [{"type": "function", "function": {"name": "get_weather", "description": "Current weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["c", "f"]}},
                         "required": ["city", "unit"]}}}]
msgs = [{"role": "user", "content": "What's the weather in Paris in celsius? Use the tool."}]
d = post({"model": MODEL, "messages": msgs, "tools": tools, "tool_choice": "auto", "max_tokens": 800, "temperature": 0})
m = d["choices"][0]["message"]; calls = m.get("tool_calls") or []
args = json.loads(calls[0]["function"]["arguments"]) if calls else {}
step1 = bool(calls) and calls[0]["function"]["name"] == "get_weather" and args.get("city", "").lower().startswith("paris")
final = ""
if step1:
    msgs += [{"role": "assistant", "content": m.get("content") or "", "tool_calls": calls},
             {"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps({"temp": 17, "unit": "c", "sky": "cloudy"})}]
    d2 = post({"model": MODEL, "messages": msgs, "tools": tools, "max_tokens": 800, "temperature": 0})
    final = (d2["choices"][0]["message"].get("content") or "")
res["tools"] = {"call": calls[0]["function"] if calls else None, "args_valid_json": bool(args), "final": final.strip()[:120],
                "ok": step1 and "17" in final}

# 3. needles: three 8-char codes at 25/50/75% of a ~100K-token filler document, then the same at ~50K
WORDS = "river stone paper cloud engine garden silver market winter orange signal harbor violet candle forest mirror".split()
for target in (50000, 100000):
    rng = random.Random(target)
    n = int(target / 1.4); w = [rng.choice(WORDS) for _ in range(n)]
    codes = ["".join(rng.choices(string.ascii_uppercase + string.digits, k=8)) for _ in range(3)]
    for i, c in enumerate(codes):
        w.insert(int(n * (i + 1) / 4), f". The secret code number {i + 1} is {c}. ")
    doc = f"[qual {time.time_ns()}] " + " ".join(w) + "\n\nList every secret code number and its value from the document. Answer only with the codes."
    t0 = time.time()
    d = post({"model": MODEL, "messages": [{"role": "user", "content": doc}], "max_tokens": 1500, "temperature": 0})
    txt = (d["choices"][0]["message"].get("content") or "") + (d["choices"][0]["message"].get("reasoning") or "")
    res[f"needle_{target}"] = {"prompt_tokens": d["usage"]["prompt_tokens"], "found": f"{sum(c in txt for c in codes)}/3",
                               "wall_s": round(time.time() - t0, 1), "ok": all(c in txt for c in codes)}
res["all_ok"] = all(v.get("ok") for v in res.values() if isinstance(v, dict))
print(json.dumps(res, indent=1))
