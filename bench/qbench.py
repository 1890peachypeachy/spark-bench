#!/usr/bin/env python3
"""qbench — ONE model-agnostic quality/speed bench for whatever OpenAI-compatible server is up.

Endpoint and model id are arguments, so the same frozen inputs and the same scoring can be pointed at a
different engine/model and the numbers compare directly.

    python3 bench/qbench.py --base-url http://forge:8000/v1 --model deepseek-v4.1-flash \
        --areas all --out results/qbench-dsv41-zig-20261015.json

Areas (frozen inputs in bench/inputs/, built by bench/mkfixtures.py):
    speed    fixed prompts, fixed output length: TTFT, prefill tok/s, decode tok/s, C1 and C4
    mmlu     MMLU-200, 0-shot, first A-D letter (knowledge/QA)
    math     GSM8K test first 30, exact final number (reasoning/math)
    coding   5 tasks with hidden stdlib-unittest tests, run locally (coding)
    if       20 items with programmatic checkers (instruction following)
    json     6 JSON-Schema tasks via response_format (structured output)
    tools    8 single-call cases + 2 dependent chains (tool use)
    longctx  passkey at fixed sizes/depths (long context)
    summary  planted-fact fidelity of a compaction summary (summarization)

Scoring is deterministic and offline. Thinking is OFF by default (--thinking to enable). Never more than
--workers requests in flight (default 4, the tailnet's limit).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
AREAS = ["speed", "mmlu", "math", "coding", "if", "json", "tools", "longctx", "summary"]


# --------------------------------------------------------------------------- HTTP

class Engine:
    def __init__(self, base_url: str, model: str, api_key: str = "none", thinking: bool = False,
                 timeout: float = 1800.0):
        self.base = base_url.rstrip("/")
        self.model = model
        self.key = api_key
        self.thinking = thinking
        self.timeout = timeout
        self.calls = 0
        self.errors = 0

    def chat(self, messages, *, max_tokens=1024, temperature=0, tools=None, tool_choice=None,
             response_format=None, extra=None, stream=False, retry=True):
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": stream,
                "chat_template_kwargs": {"enable_thinking": bool(self.thinking)}}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format
        if extra:
            body.update(extra)
        if stream:
            body["stream_options"] = {"include_usage": True}
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + "/chat/completions", data=data,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.key}"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            self.errors += 1
            if retry:
                time.sleep(2.0)
                return self.chat(messages, max_tokens=max_tokens, temperature=temperature, tools=tools,
                                 tool_choice=tool_choice, response_format=response_format, extra=extra,
                                 stream=stream, retry=False)
            raise RuntimeError(f"transport error: {e}") from e
        self.calls += 1
        if stream:
            return self._parse_stream(raw, t0)
        d = json.loads(raw)
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or "",
                "tool_calls": msg.get("tool_calls") or [], "finish": ch.get("finish_reason"),
                "usage": d.get("usage") or {}, "tensorfold": d.get("tensorfold") or {},
                "content_len": len(msg.get("content") or ""),
                "reasoning_len": len(msg.get("reasoning_content") or ""),
                "seconds": time.time() - t0}

    @staticmethod
    def _parse_stream(raw: bytes, t0: float) -> dict:
        content, reasoning, calls, finish, usage, tf = "", "", {}, None, {}, {}
        first = None
        for line in raw.decode(errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                continue
            try:
                d = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if d.get("usage"):
                usage = d["usage"]
            if d.get("tensorfold"):
                tf = d["tensorfold"]
            if not d.get("choices"):
                continue
            ch = d["choices"][0]
            delta = ch.get("delta") or {}
            if first is None and (delta.get("content") or delta.get("tool_calls") or delta.get("reasoning_content")):
                first = time.time()
            if delta.get("content"):
                content += delta["content"]
            if delta.get("reasoning_content"):
                reasoning += delta["reasoning_content"]
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", 0)
                slot = calls.setdefault(i, {"id": None, "type": "function",
                                            "function": {"name": None, "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                if (tc.get("function") or {}).get("name"):
                    slot["function"]["name"] = tc["function"]["name"]
                slot["function"]["arguments"] += (tc.get("function") or {}).get("arguments") or ""
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
        t1 = time.time()
        return {"content": content, "reasoning": reasoning, "tool_calls": list(calls.values()),
                "finish": finish, "usage": usage, "tensorfold": tf, "content_len": len(content),
                "reasoning_len": len(reasoning), "seconds": t1 - t0,
                "ttft_s": (first - t0) if first else None}


def tokenize(eng: Engine, text: str) -> int | None:
    body = json.dumps({"model": eng.model, "messages": [{"role": "user", "content": text}]}).encode()
    req = urllib.request.Request(eng.base + "/tokenize", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return int(json.loads(r.read())["count"])
    except Exception:
        return None


def load(name: str):
    p = INPUTS / name
    if name.endswith(".jsonl"):
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return json.loads(p.read_text())


# --------------------------------------------------------------------------- area: speed

SPEED_PROMPTS = {
    "code": "Write a Python function that merges two sorted lists into one sorted list. Include a docstring "
            "and a short usage example. Do not explain outside the code.",
    "prose": "Write a calm 250-word description of a harbour at dawn, in plain prose. No lists, no headings.",
}
SPEED_TOKENS = 320


def measured(eng: Engine, prompt: str, max_tokens: int) -> dict:
    """One generation with honest speed numbers: stream for TTFT, usage for the token count.

    Prefers the server's own ``tensorfold`` block (ttft_s / prefill_s / decode_s) when present; otherwise
    falls back to the streamed timestamps, so the same harness measures a different engine the same way.
    """
    r = eng.chat([{"role": "user", "content": prompt}], max_tokens=max_tokens, stream=True)
    comp = (r.get("usage") or {}).get("completion_tokens")
    tf = r.get("tensorfold") or {}
    if comp is None:  # no usage in the stream: redo once without streaming for a token count
        r2 = eng.chat([{"role": "user", "content": prompt}], max_tokens=max_tokens)
        comp = (r2.get("usage") or {}).get("completion_tokens")
        tf = r2.get("tensorfold") or tf
        r = r2
    ttft = tf.get("ttft_s") or r.get("ttft_s")
    dec_s = tf.get("decode_s") or (r["seconds"] - (ttft or 0))
    return {"ttft_s": round(ttft, 3) if ttft else None,
            "prefill_tok_s": round(float(tf.get("prompt", 0)) / tf["prefill_s"], 1)
            if tf.get("prefill_s") else None,
            "completion_tokens": comp, "wall_s": round(r["seconds"], 2),
            "decode_s": round(dec_s, 3),
            "decode_tok_s": round(comp / dec_s, 2) if comp and dec_s > 0 else None,
            "finish": r.get("finish")}


def area_speed(eng: Engine, workers: int) -> dict:
    out = {"c1": {}, "c4": {}}
    for name, prompt in SPEED_PROMPTS.items():
        out["c1"][name] = measured(eng, prompt, SPEED_TOKENS)
    # C4: four concurrent streams of the same prompts (deterministic load, aggregate measured)
    prompts = [SPEED_PROMPTS[k] for k in ("code", "prose", "code", "prose")]
    t0 = time.time()
    with cf.ThreadPoolExecutor(len(prompts)) as ex:
        rs = list(ex.map(lambda p: measured(eng, p, SPEED_TOKENS), prompts))
    wall = time.time() - t0
    toks = sum(r["completion_tokens"] or 0 for r in rs)
    out["c4"] = {"streams": len(prompts), "completion_tokens": toks, "wall_s": round(wall, 2),
                 "aggregate_tok_s": round(toks / max(1e-9, wall), 2),
                 "per_stream_tok_s": [r["decode_tok_s"] for r in rs],
                 "ttft_s": [r["ttft_s"] for r in rs]}
    return out


# --------------------------------------------------------------------------- area: mmlu

LETTERS = "ABCD"


def area_mmlu(eng: Engine, workers: int) -> dict:
    items = load("mmlu200.jsonl")
    def one(it):
        prompt = (it["question"] + "\n" + "\n".join(f"{LETTERS[i]}. {c}" for i, c in enumerate(it["choices"]))
                  + "\nAnswer with a single letter (A, B, C or D) and nothing else.")
        r = eng.chat([{"role": "user", "content": prompt}], max_tokens=8)
        m = re.search(r"[ABCD]", r["content"].strip().upper())
        got = LETTERS.index(m.group(0)) if m else -1
        return {"subject": it["subject"], "ok": got == it["answer"], "got": got, "answer": it["answer"],
                "finish": r.get("finish"), "reply": r["content"][:12]}
    with cf.ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, items))
    ok = sum(r["ok"] for r in rows)
    return {"n": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 4), "items": rows}


# --------------------------------------------------------------------------- area: math

NUM = re.compile(r"-?\$?\d[\d,]*\.?\d*")


def area_math(eng: Engine, workers: int) -> dict:
    items = load("math.jsonl")
    def norm(s: str) -> str:
        return s.replace(",", "").replace("$", "").rstrip(".").strip()
    def one(it):
        r = eng.chat([{"role": "user", "content": it["question"] +
                       "\nEnd your reply with: 'ANSWER: <number>'"}], max_tokens=1024)
        nums = NUM.findall(r["content"].replace("**", ""))
        got = norm(nums[-1]) if nums else ""
        want = norm(it["answer"])
        try:
            ok = abs(float(got) - float(want)) < 1e-6
        except ValueError:
            ok = got == want
        return {"id": it["id"], "ok": ok, "got": got, "want": want, "finish": r.get("finish"),
                "reasoning_tokens": (r.get("usage") or {}).get("completion_tokens")}
    with cf.ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, items))
    ok = sum(r["ok"] for r in rows)
    return {"n": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 4), "items": rows}


# --------------------------------------------------------------------------- area: coding

FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract_code(reply: str) -> str:
    m = FENCE.findall(reply)
    return m[0] if m else reply


def area_coding(eng: Engine, workers: int) -> dict:
    tasks = load("coding.json")["tasks"]
    def one(t):
        r = eng.chat([{"role": "user", "content": t["prompt"]}], max_tokens=2048)
        code = extract_code(r["content"])
        ok, detail = False, ""
        with tempfile.TemporaryDirectory(prefix="qbench-") as d:
            (Path(d) / "solution.py").write_text(code)
            (Path(d) / "test_hidden.py").write_text(t["test"])
            try:
                p = subprocess.run([sys.executable, "test_hidden.py"], cwd=d, capture_output=True,
                                   text=True, timeout=120)
                ok = p.returncode == 0
                detail = (p.stderr or p.stdout).strip().splitlines()[-1][:200] if not ok else ""
            except subprocess.TimeoutExpired:
                detail = "timeout"
        return {"id": t["id"], "ok": ok, "detail": detail, "finish": r.get("finish"),
                "code_lines": len(code.splitlines())}
    with cf.ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, tasks))
    ok = sum(r["ok"] for r in rows)
    return {"n": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 4), "items": rows}


# --------------------------------------------------------------------------- area: if

def check_if(reply: str, c: dict) -> bool:
    text = reply.strip()
    kind = c["kind"]
    if kind == "exact":
        return text == c["value"]
    if kind == "exact_ci":
        return text.lower() == c["value"].lower()
    if kind == "one_of":
        return text.lower().rstrip(".") in [v.lower() for v in c["values"]]
    if kind == "startswith":
        return text.lower().startswith(c["prefix"].lower()) and c["contains"] in text.lower()
    if kind == "substring":
        low = text.lower()
        return all(s in low for s in c.get("must", [])) and not any(s in low for s in c.get("must_not", []))
    if kind == "absent_char":
        return (c["char"] not in text.lower()) and len(text.split()) >= c.get("min_words", 1)
    if kind == "max_words":
        return len(text.split()) <= c["n"]
    if kind == "lines":
        lines = [l for l in text.splitlines() if l.strip()]
        if "prefix" in c:
            return len(lines) == c["n"] and all(l.startswith(c["prefix"]) for l in lines)
        return len(lines) == c["n"]
    if kind == "lines_prefix_end":
        lines = [l for l in text.splitlines() if l.strip()]
        return (len(lines) == c["n"] + 1 and all(l.startswith(c["prefix"]) for l in lines[:c["n"]])
                and lines[-1].strip().upper() == c["end"])
    if kind == "lines_matching":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return sum(1 for l in lines if re.match(c["pattern"], l)) >= c["n"]
    if kind == "sentences":
        n = len([s for s in re.split(r"[.!?]+\s", text) if s.strip()])
        return n == c["n"]
    if kind == "words_n_lower":
        ws = text.split()
        return len(ws) == c["n"] and all(w == w.lower() for w in ws)
    if kind == "comma_n":
        parts = [p.strip() for p in text.split(",")]
        return len(parts) == c["n"] and all(parts) and (not c.get("lower") or all(p == p.lower() for p in parts))
    if kind == "int_only":
        return text.strip().rstrip(".") == str(c["value"])
    if kind == "json_keys":
        try:
            d = json.loads(re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip())
        except Exception:
            return False
        return isinstance(d, dict) and sorted(d.keys()) == sorted(c["keys"])
    raise ValueError(f"unknown checker {kind}")


def area_if(eng: Engine, workers: int) -> dict:
    items = load("if.jsonl")
    def one(it):
        r = eng.chat([{"role": "user", "content": it["prompt"]}], max_tokens=512)
        try:
            ok = check_if(r["content"], it["check"])
        except Exception as e:
            ok = False
        return {"id": it["id"], "kind": it["check"]["kind"], "ok": ok, "finish": r.get("finish"),
                "reply": r["content"][:120]}
    with cf.ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, items))
    ok = sum(r["ok"] for r in rows)
    return {"n": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 4), "items": rows}


# --------------------------------------------------------------------------- area: json

def validate(value, schema, path="$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t == "object" or "properties" in schema or "additionalProperties" in schema:
        if not isinstance(value, dict):
            return [f"{path}: not an object"]
        props = schema.get("properties") or {}
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}: missing {k}")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{path}: unexpected {k}")
        if isinstance(schema.get("additionalProperties"), dict):
            for k, v in value.items():
                if k not in props:
                    errs += validate(v, schema["additionalProperties"], f"{path}.{k}")
        for k, sub in props.items():
            if k in value:
                errs += validate(value[k], sub, f"{path}.{k}")
        return errs
    if t == "array" or "items" in schema:
        if not isinstance(value, list):
            return [f"{path}: not an array"]
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: too many items")
        for i, v in enumerate(value):
            errs += validate(v, schema.get("items") or {}, f"{path}[{i}]")
        return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: not in enum")
    if t == "string" and not isinstance(value, str):
        errs.append(f"{path}: not a string")
    if t == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        errs.append(f"{path}: not an integer")
    if t == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        errs.append(f"{path}: not a number")
    if t == "boolean" and not isinstance(value, bool):
        errs.append(f"{path}: not a boolean")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above maximum")
    return errs


def area_json(eng: Engine, workers: int) -> dict:
    data = load("json_tasks.json")
    def one(t):
        rf = {"type": "json_schema", "json_schema": {"name": t["name"], "strict": True,
                                              "schema": t["schema"]}}
        r = eng.chat([{"role": "user", "content": t["prompt"]}], max_tokens=768, response_format=rf)
        text = r["content"].strip()
        leaked = bool(r.get("reasoning")) or "```" in text or "<" in text[:1]
        try:
            val = json.loads(text)
            errs = validate(val, t["schema"])
        except Exception as e:
            val, errs = None, [f"unparsable: {e}"]
        return {"name": t["name"], "ok": not errs, "errors": errs[:3], "finish": r.get("finish"),
                "markup_leak": leaked, "content": text[:160]}
    with cf.ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, data["tasks"]))
    ok = sum(r["ok"] for r in rows)
    return {"n": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 4), "items": rows}


# --------------------------------------------------------------------------- area: tools

def parse_calls(eng: Engine, calls) -> list[dict]:
    out = []
    for c in calls or []:
        fn = c.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = None
        out.append({"name": fn.get("name"), "args": args, "raw": (fn.get("arguments") or "")[:200]})
    return out


def call_ok(call: dict, expect: dict, tools_spec: list[dict]) -> tuple[bool, str]:
    if expect.get("no_tool"):
        return (call["name"] is None), "expected no tool call"
    tool = next((t for t in tools_spec if t["function"]["name"] == call["name"]), None)
    if tool is None:
        return False, f"unknown tool {call['name']}"
    if call["args"] is None:
        return False, "arguments not JSON"
    schema = tool["function"]["parameters"]
    errs = validate(call["args"], schema)
    for k in expect.get("required", []):
        if k not in call["args"]:
            errs.append(f"missing required {k}")
    for k, v in (expect.get("const") or {}).items():
        if call["args"].get(k) != v:
            errs.append(f"{k}={call['args'].get(k)!r} expected {v!r}")
    return (not errs), "; ".join(errs[:2])


def area_tools(eng: Engine, workers: int) -> dict:
    data = load("tool_tasks.json")
    tools_spec = data["tools"]

    def one(case):
        r = eng.chat([{"role": "user", "content": case["prompt"]}], max_tokens=768, tools=tools_spec,
                     tool_choice="auto")
        calls = parse_calls(eng, r["tool_calls"])
        if case["expect"].get("no_tool"):
            ok, why = call_ok({"name": None, "args": None}, case["expect"], tools_spec)
            why = why or "no tool expected"
        elif not calls:
            ok, why = False, "no call emitted"
        else:
            ok, why = call_ok(calls[0], case["expect"], tools_spec)
        leaked = any(ch in r["content"] for ch in ("｜DSML｜", "<tool_result>"))
        return {"id": case["id"], "ok": ok, "why": why, "name": calls[0]["name"] if calls else None,
                "calls": len(calls), "markup_leak": leaked, "finish": r.get("finish")}

    with cf.ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, data["cases"]))

    chains = []
    for ch in data["chains"]:
        messages = []
        calls_seen, ok_all, why = [], True, ""
        for turn in ch["turns"]:
            messages.append({"role": "user", "content": turn["prompt"]})
            r = eng.chat(messages, max_tokens=768, tools=tools_spec, tool_choice="auto")
            calls = parse_calls(eng, r["tool_calls"])
            if not calls:
                ok_all, why = False, f"{ch['id']}: no call"
                break
            call = calls[0]
            ok, why = call_ok(call, turn["expect"], tools_spec)
            calls_seen.append(call)
            messages.append({"role": "assistant", "content": r["content"] or None,
                             "tool_calls": r["tool_calls"]})
            result = CHAIN_SIM.get(call["name"], lambda a: "unknown tool")(call["args"] or {})
            messages.append({"role": "tool", "tool_call_id": (r["tool_calls"][0].get("id") or "call_1"),
                             "content": result})
            if not ok:
                ok_all = False
        # final answer must reflect the last tool result deterministically
        last = calls_seen[-1] if calls_seen else {}
        fc = ch.get("final_check") or {}
        if ok_all and fc:
            got = (last.get("args") or {}).get(fc["arg"])
            if got != fc["value"]:
                ok_all, why = False, f"final {fc['arg']}={got!r} expected {fc['value']!r}"
        chains.append({"id": ch["id"], "ok": ok_all, "why": why,
                       "calls": [{"name": c["name"], "args": c["args"]} for c in calls_seen]})

    n = len(rows) + len(chains)
    ok = sum(r["ok"] for r in rows) + sum(c["ok"] for c in chains)
    return {"n": n, "correct": ok, "accuracy": round(ok / n, 4),
            "single": {"n": len(rows), "correct": sum(r["ok"] for r in rows), "items": rows},
            "chains": {"n": len(chains), "correct": sum(c["ok"] for c in chains), "items": chains}}


CHAIN_SIM = {
    "get_weather": lambda a: f"{a.get('city', '?')}: 4 degrees, sleet, wind 20 km/h",
    "create_task": lambda a: f"created task {a.get('title', '?')} priority {a.get('priority', '?')}",
    "run_sql": lambda a: ("id|created_at\n9012|2026-09-24\n9007|2026-09-23\n9001|2026-09-22\n"
                          "8990|2026-09-21\n8984|2026-09-20"),
    "convert_currency": lambda a: f"{a.get('amount', '?')} {a.get('from', '?')} = 41800 {a.get('to', '?')}",
}


# --------------------------------------------------------------------------- area: longctx

FILLER_WORDS = ("the quarterly ledger notes a routine check of valves pumps and gauges beside the western "
                "dock where the crew records tide height wind drift and the state of every mooring line").split()


def build_filler(n_tokens: int) -> str:
    n_words = max(64, int(n_tokens * 0.75 * 1.02))
    parts = []
    for i in range(n_words):
        parts.append(FILLER_WORDS[i % len(FILLER_WORDS)])
    return " ".join(parts)


def area_longctx(eng: Engine, workers: int) -> dict:
    cfg = load("longctx.json")
    rows = []
    for item in cfg["items"]:
        target = item["size"]
        text = build_filler(target)
        # size to the server's tokenizer, then place the passkey at the requested depth
        counted = tokenize(eng, text) or 0
        for _ in range(8):
            if not counted or abs(counted - target) <= max(8, target * 0.02):
                break
            ratio = target / max(1, counted)
            text = build_filler(int(len(text.split()) * ratio))
            counted = tokenize(eng, text) or 0
        words = text.split()
        at = int(len(words) * item["depth"])
        words.insert(at, f"\nIMPORTANT: the passkey is {item['passkey']}.\n")
        doc = f"Here is a long operations log.\n\n{' '.join(words)}\n\nThe log ends here."
        prompt = f"{doc}\n\n{cfg['question']}"
        r = eng.chat([{"role": "user", "content": prompt}], max_tokens=32)
        got = r["content"].strip()
        rows.append({"size_target": target, "size_actual": counted, "depth": item["depth"],
                     "ok": item["passkey"] in got, "reply": got[:40], "finish": r.get("finish"),
                     "prompt_tokens": (r.get("usage") or {}).get("prompt_tokens"),
                     "ttft_s": (r.get("tensorfold") or {}).get("ttft_s")})
    ok = sum(r["ok"] for r in rows)
    return {"n": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 4), "items": rows}


# --------------------------------------------------------------------------- area: summary

def area_summary(eng: Engine, workers: int) -> dict:
    fx = load("summary.json")
    transcript, prompt = fx["transcript"], fx["prompt"]
    r = eng.chat([{"role": "user", "content": f"{prompt}\n\n<log>\n{transcript}\n</log>"}], max_tokens=2048)
    summary = r["content"]
    kept = [f["key"] for f in fx["facts"] if f["value"] in summary]
    missing = [f["key"] for f in fx["facts"] if f["value"] not in summary]
    stale_hits = [s["key"] for s in fx["stale"] if s["old"] in summary]
    extra_ok = fx["extra_fact"]["value"] in summary
    src_numbers = set(re.findall(r"\d{3,}", transcript))
    out_numbers = set(re.findall(r"\d{3,}", summary))
    invented = sorted(out_numbers - src_numbers)
    return {"facts_total": len(fx["facts"]), "facts_kept": len(kept), "facts_kept_rate": round(len(kept) / len(fx["facts"]), 4),
            "missing": missing, "stale_returned": stale_hits, "stale_rate": round(len(stale_hits) / len(fx["stale"]), 4),
            "extra_fact_kept": extra_ok, "invented_numbers": invented,
            "invented_rate": round(len(invented) / max(1, len(out_numbers)), 4),
            "transcript_tokens": (r.get("usage") or {}).get("prompt_tokens"),
            "finish": r.get("finish"), "summary_words": len(summary.split())}


# --------------------------------------------------------------------------- driver

def run_area(name: str, eng: Engine, workers: int) -> dict:
    t0 = time.time()
    fn = {"speed": area_speed, "mmlu": area_mmlu, "math": area_math, "coding": area_coding, "if": area_if,
          "json": area_json, "tools": area_tools, "longctx": area_longctx, "summary": area_summary}[name]
    try:
        res = fn(eng, workers)
        res["error"] = None
    except Exception as e:  # an area failure is a data point, not a crash
        res = {"error": f"{type(e).__name__}: {e}"}
    res["seconds"] = round(time.time() - t0, 1)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Model-agnostic quality/speed bench (spark-bench)")
    ap.add_argument("--base-url", default="http://forge:8000/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default=os.environ.get("QBENCH_API_KEY", "none"))
    ap.add_argument("--areas", default="all", help="comma list or 'all'")
    ap.add_argument("--tag", default=None, help="label for this run (default: model + date)")
    ap.add_argument("--out", default=None, help="result JSON path (default results/qbench-<tag>.json)")
    ap.add_argument("--workers", type=int, default=4, help="max requests in flight (tailnet limit is 4)")
    ap.add_argument("--thinking", action="store_true", help="leave thinking ON (default OFF)")
    ap.add_argument("--timeout", type=float, default=1800.0)
    a = ap.parse_args()

    names = AREAS if a.areas.strip() == "all" else [x.strip() for x in a.areas.split(",") if x.strip()]
    bad = [n for n in names if n not in AREAS]
    if bad:
        sys.exit(f"unknown area(s): {bad}; known: {AREAS}")
    tag = a.tag or f"{a.model.replace('/', '_')}-{time.strftime('%Y%m%d')}"
    out = Path(a.out) if a.out else (HERE.parent / "results" / f"qbench-{tag}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    eng = Engine(a.base_url, a.model, a.api_key, thinking=a.thinking, timeout=a.timeout)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"qbench {tag}: {a.base_url} model={a.model} thinking={a.thinking} areas={names} workers={a.workers}")

    result = {"bench": "qbench", "version": 1, "tag": tag, "base_url": a.base_url, "model": a.model,
              "thinking": a.thinking, "started": started, "areas": {}}
    for name in names:
        res = run_area(name, eng, a.workers)
        result["areas"][name] = res
        acc = res.get("accuracy")
        print(f"  {name:8} {res['seconds']:>7.1f}s  " +
              (f"accuracy {acc:.3f} ({res.get('correct')}/{res.get('n')})" if acc is not None else
               ("ok" if not res.get("error") else res["error"])))
        out.write_text(json.dumps(result, indent=1))  # incremental, so a long run is never lost
    result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result["requests"] = eng.calls
    result["transport_errors"] = eng.errors
    out.write_text(json.dumps(result, indent=1))
    print(f"wrote {out}  ({eng.calls} requests, {eng.errors} transport errors)")


if __name__ == "__main__":
    main()
