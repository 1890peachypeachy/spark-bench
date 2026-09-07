#!/usr/bin/env python3
"""corrcheck.py — pre-bench correctness gate for the qwen38 tuning campaign.
Fails closed (exit 3) if ANY check fails. Usage: corrcheck.py [label]
Checks:
  1. /v1/models serves qwen3.8-flash-next
  2. chat completion returns non-empty content
  3. temp0 determinism (2 repeats, identical text)
  4. explicit tool call parses (qwen3_coder parser)
  5. tool history roundtrip (assistant tool_call -> tool result -> answer)
  6. structured JSON via response_format json_schema parses and validates
"""
import json, sys, hashlib, urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8000"
MODEL = "qwen3.8-flash-next"
LABEL = sys.argv[1] if len(sys.argv) > 1 else "unnamed"
results = []

def call(body, timeout=180):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    return r

def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(("PASS " if ok else "FAIL ") + name + (" — " + str(detail)[:200] if detail else ""), flush=True)

# 1. models
try:
    m = json.load(urllib.request.urlopen(BASE + "/v1/models", timeout=10))
    ids = [x["id"] for x in m.get("data", [])]
    check("models_endpoint", MODEL in ids, ids)
except Exception as e:  # noqa: BLE001
    check("models_endpoint", False, repr(e)); finish()

def finish():
    ok = all(r["ok"] for r in results)
    out = {"label": LABEL, "ts": datetime.now(timezone.utc).isoformat(), "ok": ok, "checks": results}
    print(json.dumps(out))
    sys.exit(0 if ok else 3)

base = {"model": MODEL, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}

# 2+3. nonempty + deterministic
try:
    hashes, texts = [], []
    for _ in range(2):
        r = call({**base, "messages": [{"role": "user", "content": "What is the capital of Australia? Just the city."}],
                  "max_tokens": 64})
        c = r["choices"][0]["message"].get("content") or ""
        hashes.append(hashlib.sha256(c.encode()).hexdigest()[:12]); texts.append(c)
    check("chat_nonempty", all(t.strip() for t in texts), texts[0][:60])
    check("temp0_deterministic", len(set(hashes)) == 1, hashes)
except Exception as e:  # noqa: BLE001
    check("chat_nonempty", False, repr(e)); finish()

# 4. explicit tool call
tools = [{"type": "function", "function": {
    "name": "get_weather",
    "description": "Get current weather for a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
try:
    r = call({**base, "messages": [{"role": "user", "content": "What is the weather in Paris right now? Use the tool."}],
              "tools": tools, "tool_choice": "auto", "max_tokens": 256})
    msg = r["choices"][0]["message"]
    tcs = msg.get("tool_calls") or []
    ok = bool(tcs) and tcs[0]["function"]["name"] == "get_weather"
    try:
        args = json.loads(tcs[0]["function"]["args"] if "args" in tcs[0]["function"] else tcs[0]["function"]["arguments"])
        ok = ok and "city" in args
    except Exception:  # noqa: BLE001
        ok = False
    check("tool_call_explicit", ok, tcs[:1])
except Exception as e:  # noqa: BLE001
    check("tool_call_explicit", False, repr(e))

# 5. tool history roundtrip
try:
    r = call({**base, "messages": [
        {"role": "user", "content": "What is the weather in Paris? Use the tool."},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function",
                                                              "function": {"name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"temp_c\": 18, \"condition\": \"cloudy\"}"}],
        "tools": tools, "max_tokens": 128})
    c = r["choices"][0]["message"].get("content") or ""
    check("tool_history_roundtrip", bool(c.strip()) and ("18" in c or "cloudy" in c.lower()), c[:120])
except Exception as e:  # noqa: BLE001
    check("tool_history_roundtrip", False, repr(e))

# 6. structured JSON (json_schema response_format)
schema = {"type": "object", "properties": {"name": {"type": "string"}, "population": {"type": "integer"}},
          "required": ["name", "population"], "additionalProperties": False}
try:
    r = call({**base, "messages": [{"role": "user", "content": "Give me the name and population of Tokyo as JSON."}],
              "response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": schema}},
              "max_tokens": 128})
    c = r["choices"][0]["message"].get("content") or ""
    j = json.loads(c)  # raises if not JSON
    ok = isinstance(j.get("name"), str) and isinstance(j.get("population"), int) and set(j) == {"name", "population"}
    check("structured_json", ok, j)
except Exception as e:  # noqa: BLE001
    check("structured_json", False, repr(e))

# 7. thinking opt-in smoke (nonempty reasoning when requested)
try:
    r = call({"model": MODEL, "temperature": 0, "max_tokens": 200,
              "messages": [{"role": "user", "content": "17*23? Think briefly."}],
              "chat_template_kwargs": {"enable_thinking": True}})
    msg = r["choices"][0]["message"]
    reasoning = (msg.get("reasoning") or msg.get("reasoning_content") or "")
    check("thinking_optin", bool((msg.get("content") or "").strip()) or bool(reasoning.strip()),
          {"content": (msg.get("content") or "")[:50], "reasoning_len": len(reasoning)})
except Exception as e:  # noqa: BLE001
    check("thinking_optin", False, repr(e))

finish()
