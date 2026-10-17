#!/usr/bin/env python3
"""The harness-effect table: Row A from a qbench JSON (raw API), the other rows from bench/harness/run.py JSONs.

    python3 bench/harness/table.py --row-a results/<run>/qbench-<tag>.json results/<run>/harness/*.json

Row A's MMLU is scored on the same 50-item subset the harness rows use (every 4th of MMLU-200).
"""
import argparse
import json
from pathlib import Path

AREAS = ["coding", "math", "mmlu", "if", "json"]
STRIDE = 4


def row_a(path: str) -> dict:
    d = json.loads(Path(path).read_text())
    cells = {}
    for a in AREAS:
        r = d["areas"].get(a) or {}
        items = r.get("items") or []
        if a == "mmlu":
            items = items[::STRIDE]
        if items:
            cells[a] = (sum(bool(x["ok"]) for x in items), len(items))
    secs = sum((d["areas"].get(a) or {}).get("seconds") or 0 for a in AREAS)
    return {"label": "A", "harness": "raw API (qbench)", "version": f"qbench v{d.get('version')}", "model": d["model"],
            "cells": cells, "wall": f"{secs:.0f} s (all 200 MMLU)", "tools": "-", "llm": "1/task",
            "tokens": "see qbench JSON"}


def row_h(path: str) -> dict:
    d = json.loads(Path(path).read_text())
    s = d["summary"]
    v = d["harness_version"]
    ver = " ".join(str(v[k]) for k in ("version", "tag") if v.get(k))
    if v.get("commit"):
        ver += f" ({v['commit'][:10]})"
    t = s["totals"]
    tools = t.get("tap_tool_calls", t["harness_tool_calls"])
    em = d.get("engine_metrics_delta") or {}
    eng = {k: v for k, v in em.items() if "token" in k and "bucket" not in k}
    if eng:
        tokens = ", ".join(f"{k.split('{')[0].split(':')[-1]} {v:,.0f}" for k, v in sorted(eng.items())[:4])
    elif "tap_prompt_tokens" in t:
        tokens = f"prompt {t['tap_prompt_tokens']:,} / completion {t['tap_completion_tokens']:,} (tap)"
    else:  # no tap (the subscription row): Claude Code's own usage report
        us = [((x["harness_reported"].get("result") or {}).get("usage") or {}) for x in d["tasks"]]
        inp = sum((u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                  + (u.get("cache_creation_input_tokens") or 0) for u in us)
        tokens = f"prompt {inp:,} / completion {sum(u.get('output_tokens') or 0 for u in us):,} (harness-reported)"
    return {"label": d["row"], "harness": d["harness"], "version": ver, "model": d["model"],
            "cells": {a: (s["areas"][a]["correct"], s["areas"][a]["n"]) for a in AREAS if a in s["areas"]},
            "wall": f"{d['wall_s']:.0f} s", "tools": str(tools), "llm": str(t.get("tap_llm_requests", "-")),
            "tokens": tokens}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row-a", default=None)
    ap.add_argument("rows", nargs="*")
    a = ap.parse_args()
    rows = ([row_a(a.row_a)] if a.row_a else []) + [row_h(p) for p in a.rows]
    head = ["row", "harness", "version", "model"] + AREAS + ["total", "wall", "LLM calls", "tool calls", "tokens"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in rows:
        c = r["cells"]
        tot = (sum(x[0] for x in c.values()), sum(x[1] for x in c.values()))
        print("| " + " | ".join([r["label"], r["harness"], r["version"], r["model"]]
                                + [f"{c[x][0]}/{c[x][1]}" if x in c else "-" for x in AREAS]
                                + [f"{tot[0]}/{tot[1]}", r["wall"], r["llm"], r["tools"], r["tokens"]]) + " |")


if __name__ == "__main__":
    main()
