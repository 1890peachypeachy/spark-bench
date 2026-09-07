#!/usr/bin/env python3
"""Graded capability runner: accuracy / intelligence / instruction-following.

Differences from run_capability_matrix.py:
- reasoning_effort=high pinned on every call
- every case has ground truth, scored deterministically (score.mode/value)
- difficulty tier recorded per case (1 easy -> 3 stress)
- custom instruction checks implemented in check_custom()

Usage: run_graded.py [model1,model2]  (default all)
"""
import json, os, re, sys, time, urllib.request, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results_graded")
os.makedirs(RESULTS, exist_ok=True)
TIMEOUT_S = 300

MODELS = {
    "deepseek": {"url": "http://100.106.81.35:8888/v1/chat/completions",
                 "id": "deepseek-v4-flash-0731"},
    "qwen":     {"url": "http://100.99.120.29:8888/v1/chat/completions",
                 "id": "qwen38-27b-unsloth-nvfp4"},
    "orinth":   {"url": "http://100.91.114.22:8100/v1/chat/completions",
                 "id": "ornith-1.5-35b-a3b-nvfp4"},
    # New fleet candidates — endpoints TBD, verify /v1/models served id before run
    "aeon27":   {"url": "http://10.73.0.2:8000/v1/chat/completions",
                 "id": "qwen38-27b-aeon-nvfp4-mixed"},
    "flash38":  {"url": "http://10.73.0.3:8000/v1/chat/completions",
                 "id": "qwen3.8-flash-next"},
}


def call(url, model_id, prompt, max_tokens):
    payload = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "reasoning_effort": "high",          # pinned high for a true measure
        "chat_template_kwargs": {"enable_thinking": True},
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            body = json.loads(r.read())
        dt = time.time() - t0
        msg = body["choices"][0]["message"]
        text = msg.get("content")
        if not text:
            return {"ok": False, "latency_s": round(dt, 2),
                    "error": f"empty content finish={body['choices'][0].get('finish_reason')}"}
        u = body.get("usage", {})
        return {"ok": True, "latency_s": round(dt, 2), "output": text,
                "prompt_tokens": u.get("prompt_tokens"),
                "completion_tokens": u.get("completion_tokens")}
    except Exception as e:
        return {"ok": False, "latency_s": round(time.time() - t0, 2),
                "error": f"{type(e).__name__}: {e}"}


# ---------------- scoring ----------------

def words(s):
    return re.findall(r"\S+", s)


def score_case(case, out):
    """Return {'pass': bool, 'detail': str}."""
    spec = case["score"]
    mode, val = spec["mode"], spec.get("value")

    if mode == "regex":
        m = re.search(val, out)
        return {"pass": bool(m), "detail": f"match={m.group(0)!r}" if m else "no match"}
    if mode == "contains_all":
        missing = [v for v in val if v.lower() not in out.lower()]
        return {"pass": not missing, "detail": f"missing={missing}" if missing else "all present"}
    if mode == "json_contains":
        try:
            blob = re.search(r"\{.*\}", out, re.S).group(0)
            got = json.loads(blob)
        except Exception as e:
            return {"pass": False, "detail": f"unparseable JSON: {e}"}
        flat_got = json.dumps(got).lower()
        missing = [k for k in _flatten_strings(val) if k.lower() not in flat_got]
        return {"pass": not missing, "detail": f"missing={missing}" if missing else "ok"}
    if mode == "custom":
        fn = CUSTOM_CHECKS[val]
        # functions that take (out, expected) get the score value as expected
        if val == "inst_ordered_ranking":
            exp = spec.get("value_list") or spec.get("value")
            return fn(out, exp)
        return fn(out)
    return {"pass": False, "detail": f"unknown mode {mode}"}


def _flatten_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, list):
        for i in o:
            yield from _flatten_strings(i)
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _flatten_strings(k)
            yield from _flatten_strings(v)


# ---- custom instruction-following checks ----

def inst_numbered_3_lines_max5w(out):
    lines = [l for l in out.strip().splitlines() if l.strip()]
    ok_lines = [l for l in lines if re.match(r"^\s*3?[\.\)]?\s*\d+[\.\)]", l) or re.match(r"^\s*[\.\)]?\d+", l)]
    numbered = len(ok_lines) == 3 and len(lines) == 3
    w_ok = all(len(words(re.sub(r"^\s*[\.\)]?\d*[\.\)]?", "", l))) <= 5 for l in lines)
    return {"pass": numbered and w_ok,
            "detail": f"lines={len(lines)} numbered3={numbered} max5w={w_ok}"}


def inst_two_paras_rules(out):
    body = re.sub(r"END OF NOTES\s*$", "", out.strip()).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    two = len(paras) == 2
    wc = [len(words(p)) for p in paras]
    range_ok = all(28 <= n <= 55 for n in wc)  # tolerance; "30-50" is fuzzy to models
    calm = len(re.findall(r"\bcalm\b", out, re.I)) == 2
    no_sleep = "sleep" not in out.lower()
    end_ok = out.rstrip().endswith("END OF NOTES")
    p = two and range_ok and calm and no_sleep and end_ok
    return {"pass": p, "detail": f"paras={len(paras)} wc={wc} calm2={calm} "
                                  f"no_sleep={no_sleep} end={end_ok} (para1 short is OK)"}


def inst_json_schema(out):
    try:
        blob = re.search(r"\{.*\}", out, re.S).group(0)
        obj = json.loads(blob)
    except Exception as e:
        return {"pass": False, "detail": f"bad json: {e}"}
    keys_ok = set(obj.keys()) == {"risk", "reason", "tags"}
    risk_ok = obj.get("risk") in ("low", "medium", "high")
    reason_ok = isinstance(obj.get("reason"), str) and len(words(obj.get("reason", ""))) <= 10
    tags = obj.get("tags")
    tags_ok = isinstance(tags, list) and len(tags) == 2 and all(isinstance(t, str) for t in tags)
    only_json = out.strip().startswith("{") and out.strip().endswith("}")
    p = keys_ok and risk_ok and reason_ok and tags_ok and only_json
    return {"pass": p, "detail": f"keys={keys_ok} risk={risk_ok} reason10={reason_ok} "
                                 f"tags2={tags_ok} onlyjson={only_json}"}


def inst_negation_summary(out):
    banned = ["late", "shipping", "refund", "angry", "order", "package"]
    low = out.lower()
    used = [b for b in banned if b in low]
    sents = [s for s in re.split(r"[.!?]+", out) if s.strip()]
    two = len(sents) == 2
    p = not used and two
    return {"pass": p, "detail": f"used_banned={used} sentences={len(sents)}"}


def inst_format_sandwich(out):
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    l1 = bool(lines) and lines[0].startswith("VERDICT:") and len(lines[0].split()) == 2
    l2 = len(lines) > 1 and 10 <= len(words(lines[1])) <= 16
    l3 = len(lines) > 2 and re.match(r"^2026-08-24$", lines[2]) is not None
    exactly3 = len(lines) == 3
    p = l1 and l2 and l3 and exactly3
    return {"pass": p, "detail": f"lines={len(lines)} verdict={l1} sent={l2} date={l3}"}


def _find_json_array(out):
    """Return first JSON array parsed from output, or None."""
    m = re.search(r"\[[^\[\]]*\]", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def inst_ordered_ranking(out, expected):
    """Score: the JSON array must contain the expected ids IN ORDER
    (as leading subsequence or exact match). value is a list of ids."""
    arr = _find_json_array(out)
    if arr is None:
        return {"pass": False, "detail": f"no JSON array found"}
    # normalize to strings
    norm = [str(x).strip() for x in arr]
    exp = [str(x).strip() for x in expected]
    # require expected appears as a contiguous ordered subsequence at the front
    if len(norm) < len(exp):
        return {"pass": False, "detail": f"array too short {norm}"}
    front = norm[:len(exp)]
    ok = front == exp
    return {"pass": ok, "detail": f"array={norm} expected_front={exp} ok={ok}"}


CUSTOM_CHECKS = {
    "inst_numbered_3_lines_max5w": inst_numbered_3_lines_max5w,
    "inst_two_paras_rules": inst_two_paras_rules,
    "inst_json_schema": inst_json_schema,
    "inst_negation_summary": inst_negation_summary,
    "inst_format_sandwich": inst_format_sandwich,
    "inst_ordered_ranking": inst_ordered_ranking,
}


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else list(MODELS)
    cfg = yaml.safe_load(open(os.path.join(HERE, "graded_prompts.yaml")))
    total = passed = 0
    tier_stats = {}  # (kind,tier) -> model -> [pass,bool]

    for cat, spec in sorted(cfg["categories"].items()):
        kind = spec["kind"]
        for mk in only:
            m = MODELS[mk]
            rec = {"category": cat, "kind": kind, "model": mk, "model_id": m["id"],
                   "reasoning_effort": "high",
                   "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cases": []}
            for case in spec["cases"]:
                r = call(m["url"], m["id"], case["prompt"], spec["max_tokens"])
                entry = {"case": case["id"], "tier": case.get("tier"), **r}
                if r["ok"]:
                    s = score_case(case, r["output"])
                    entry["score"] = s
                    key = (kind, case.get("tier"))
                    tier_stats.setdefault(key, {}).setdefault(mk, []).append(s["pass"])
                    passed += s["pass"]
                    total += 1
                    print(f"{mk:9s} {case['id']:28s} T{case.get('tier')} "
                          f"{'PASS' if s['pass'] else 'FAIL'} {r['latency_s']}s"
                          + ("" if s["pass"] else f"  [{s['detail'][:70]}]"))
                else:
                    total += 1
                    print(f"{mk:9s} {case['id']:28s} ERROR {r['error'][:80]}")
                rec["cases"].append(entry)
            with open(os.path.join(RESULTS, f"{mk}--{cat}.json"), "w") as f:
                json.dump(rec, f, indent=1)

    print("\n=== SUMMARY by kind × tier (pass rate) ===")
    models = only
    header = f"{'kind':22s} {'tier':4s} " + " ".join(f"{m:>9s}" for m in models)
    print(header)
    for key in sorted(tier_stats):
        kind, tier = key
        row = f"{kind:22s} T{tier:<4d}"
        for m in models:
            arr = tier_stats[key].get(m, [])
            rate = f"{sum(arr)}/{len(arr)}" if arr else "-"
            row += f" {rate:>9s}"
        print(row)
    print(f"\nTOTAL: {passed}/{total} graded cases passed")


if __name__ == "__main__":
    main()
