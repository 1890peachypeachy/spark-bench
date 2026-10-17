#!/usr/bin/env python3
"""Harness-effect bench: qbench's tasks and graders, each task one fresh agent session in a fresh workspace.

    python3 bench/harness/run.py --harness pi --base-url http://engine:8000/v1 --model <served id> \
        --row B --out results/<run>/harness/B-pi.json

Rows (same tasks, same graders, same answer instruction; only the harness changes):
    pi           our pi coding agent, isolated agent dir (no extensions/skills/context files), OpenAI chat route
    claude-shim  Claude Code (`claude -p --safe-mode`) with an isolated config dir, ANTHROPIC_BASE_URL -> the engine's
                 Anthropic Messages route, a dummy key (the subscription is never read)
    claude       Claude Code with its own model on the subscription (the reference row; no engine)
    dsh          DeepSeek's harness, command line (see harness_dsh())

Tasks: qbench coding (5, hidden tests), math (GSM8K-30), mmlu (MMLU-200 every 4th item = 50, fixed), if (20),
json (6, as an instruction to write answer.json: an agent harness has no API-level response_format). qbench's tool-
calling area is not run: it scores the API's tool_calls against a fixed tool list, which has no counterpart inside a
harness that brings its own tools.

Every session's LLM traffic goes through a per-session passthrough tap (bench/harness/tap.py) that counts requests,
tokens, tool calls and thinking, and caps requests in flight at 4 across all sessions.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tap as tapmod  # noqa: E402

_spec = importlib.util.spec_from_file_location("qbench", HERE.parent / "qbench.py")
qbench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qbench)

AREAS = ["coding", "math", "mmlu", "if", "json"]
MMLU_STRIDE = 4
# the ONE instruction appended to every qbench prompt; only the file name differs by area (code -> solution.py)
INSTRUCTION = ("\n\n---\nDo not answer in chat. Write exactly what your reply would have been, and nothing else, "
               "to the file `{file}` in the current working directory, then stop.")


# --------------------------------------------------------------------------- tasks

def build_tasks(areas: list[str], limit: int | None = None) -> list[dict]:
    """Each task: area, id, prompt (qbench prompt + INSTRUCTION), file, and grade(text) -> (ok, detail)."""
    tasks: list[dict] = []
    if "coding" in areas:
        for t in qbench.load("coding.json")["tasks"]:
            tasks.append({"area": "coding", "id": t["id"], "prompt": t["prompt"], "file": "solution.py",
                          "grade": lambda text, t=t: qbench.grade_coding(qbench.extract_code(text), t)})
    if "math" in areas:
        for it in qbench.load("math.jsonl"):
            def g(text, it=it):
                ok, got, want = qbench.grade_math(text, it)
                return ok, f"got {got} want {want}"
            tasks.append({"area": "math", "id": it["id"], "prompt": qbench.math_prompt(it), "file": "answer.txt",
                          "grade": g})
    if "mmlu" in areas:
        items = qbench.load("mmlu200.jsonl")
        for i in range(0, len(items), MMLU_STRIDE):
            it = items[i]
            def g(text, it=it):
                ok, got = qbench.grade_mmlu(text, it)
                return ok, f"got {got} want {it['answer']}"
            tasks.append({"area": "mmlu", "id": f"mmlu-{i:03d}", "prompt": qbench.mmlu_prompt(it),
                          "file": "answer.txt", "grade": g})
    if "if" in areas:
        for it in qbench.load("if.jsonl"):
            def g(text, it=it):
                try:
                    return qbench.check_if(text, it["check"]), it["check"]["kind"]
                except Exception as e:
                    return False, f"checker error {e}"
            tasks.append({"area": "if", "id": it["id"], "prompt": it["prompt"], "file": "answer.txt", "grade": g})
    if "json" in areas:
        for t in qbench.load("json_tasks.json")["tasks"]:
            def g(text, t=t):
                errs = qbench.grade_json(text.strip(), t)
                return not errs, "; ".join(errs[:3])
            tasks.append({"area": "json", "id": t["name"], "prompt": t["prompt"], "file": "answer.json", "grade": g})
    for t in tasks:
        t["full_prompt"] = t["prompt"] + INSTRUCTION.format(file=t["file"])
    if limit:  # a few of each area (dry runs)
        tasks = [t for i, t in enumerate(tasks) if sum(u["area"] == t["area"] for u in tasks[:i]) < limit]
    return tasks


# --------------------------------------------------------------------------- harness adapters
# Each returns (argv, env) for one session; cwd is the task workspace. ``base`` is the tap's base URL (no /v1).

def harness_pi(a, base: str, ws: Path, prompt: str, cfg: Path):
    agent_dir = cfg / "pi-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    # thinking switch exactly as qbench sends it: chat_template_kwargs {enable_thinking: false}
    (agent_dir / "models.json").write_text(json.dumps({"providers": {"bench": {
        "baseUrl": base + "/v1", "api": "openai-completions", "apiKey": "none",
        "compat": {"supportsUsageInStreaming": True, "supportsDeveloperRole": False,
                   "thinkingFormat": "chat-template", "chatTemplateKwargs": {"enable_thinking": a.thinking}},
        "models": [{"id": a.model, "name": a.model, "reasoning": True, "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 262144, "maxTokens": 32768,
                    # as our sparks provider in pi is configured (qbench also sends temperature 0)
                    "samplingParams": {"temperature": 0}}]}}}, indent=1))
    (agent_dir / "settings.json").write_text(json.dumps({"defaultProvider": "bench", "defaultModel": a.model,
                                                        "quietStartup": True}))
    argv = [a.pi_bin, "-p", "--mode", "json", "--no-session", "--no-extensions", "--no-skills", "--no-context-files",
            "--no-prompt-templates", "--no-themes", "--offline", "--provider", "bench", "--model", a.model,
            "--thinking", "medium" if a.thinking else "off", prompt]
    return argv, {"PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1"}


def _claude_argv(a, model: str, prompt: str):
    return [a.claude_bin, "-p", "--output-format", "stream-json", "--verbose", "--safe-mode", "--strict-mcp-config",
            "--no-session-persistence", "--dangerously-skip-permissions", "--model", model, prompt]


def harness_claude_shim(a, base: str, ws: Path, prompt: str, cfg: Path):
    conf = cfg / "claude-config"
    conf.mkdir(parents=True, exist_ok=True)
    env = {"CLAUDE_CONFIG_DIR": str(conf), "ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": "sk-dummy-not-a-key",
           "ANTHROPIC_DEFAULT_HAIKU_MODEL": a.model, "ANTHROPIC_DEFAULT_SONNET_MODEL": a.model,
           "ANTHROPIC_DEFAULT_OPUS_MODEL": a.model, "ANTHROPIC_SMALL_FAST_MODEL": a.model,
           "CLAUDE_CODE_SUBAGENT_MODEL": a.model,
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1",
           "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"}
    if not a.thinking:
        env["MAX_THINKING_TOKENS"] = "0"
    return _claude_argv(a, a.model, prompt), env


def harness_claude(a, base: str, ws: Path, prompt: str, cfg: Path):
    # the subscription's own model: default config dir and auth, --safe-mode drops CLAUDE.md/hooks/plugins/MCP
    env = {"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"}
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"):
        env[k] = None  # unset
    return _claude_argv(a, a.model, prompt), env


def harness_dsh(a, base: str, ws: Path, prompt: str, cfg: Path):
    """DeepSeek's harness through its SDK (bench/harness/dsh_session.py), Anthropic Messages route like Claude Code."""
    argv = [a.dsh_python, str(HERE / "dsh_session.py"), "--base-url", base + "/v1", "--model", a.model,
            "--workspace", str(ws), "--home", str(cfg / "dsh-home"),
            "--effort", "high" if a.thinking else "off", "--max-tokens", "32768"]
    if a.dsh_repo:  # the local checkout's CLI (node + tsx, as its `pnpm dsh` script), not the wheel's bundled runtime
        repo = Path(a.dsh_repo).resolve()
        wrapper = cfg / "dsh"
        cfg.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(f"#!/bin/sh\nexec node --import {(repo / 'node_modules/tsx/dist/esm/index.mjs').as_uri()} "
                           f"{repo / 'apps/cli/src/bin.ts'} \"$@\"\n")
        wrapper.chmod(0o755)
        argv += ["--dsh-bin", str(wrapper), "--runtime-cwd", str(repo)]  # tsx needs the checkout's tsconfig
    argv.append(prompt)
    return argv, {"DSH_CONTEXT_WINDOW": "262144", "DEEPSEEK_API_KEY": "sk-dummy-not-a-key"}


HARNESSES = {"pi": harness_pi, "claude-shim": harness_claude_shim, "claude": harness_claude, "dsh": harness_dsh}


def stream_json_tools(stdout: str) -> dict:
    """Tool calls / turns as the harness itself reports them (pi --mode json, claude stream-json)."""
    tools, turns, result = 0, 0, None
    for line in stdout.splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        t = d.get("type")
        if t == "assistant":  # claude
            turns += 1
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tools += 1
        elif t == "result":
            # token usage only: no cost fields in committed results
            result = {k: d.get(k) for k in ("subtype", "num_turns", "duration_ms", "is_error") if k in d}
            u = d.get("usage") or {}
            result["usage"] = {k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                                     "cache_read_input_tokens", "output_tokens") if k in u}
            result["usage"]["thinking_tokens"] = (u.get("output_tokens_details") or {}).get("thinking_tokens")
            result["models"] = sorted((d.get("modelUsage") or {}).keys())
        elif t == "tool_execution_start":  # pi
            tools += 1
        elif t == "turn_end":
            turns += 1
    return {"tool_calls": tools, "turns": turns, "result": result}


# --------------------------------------------------------------------------- one task

def run_task(a, task: dict, ws_root: Path, cfg: Path) -> dict:
    ws = ws_root / f"{task['area']}-{task['id']}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    rec = {"area": task["area"], "id": task["id"], "file": task["file"]}
    use_tap = a.harness != "claude"
    tap = tapmod.Tap(a.base_url, venice=a.venice, api_key=a.api_key, timeout=a.timeout,
                     force_temperature=a.force_temperature) if use_tap else None
    try:
        if tap:
            tap.__enter__()
        # per-session harness config (it holds this session's tap URL), outside the workspace the agent sees
        scfg = cfg / ws.name
        argv, extra = HARNESSES[a.harness](a, tap.base if tap else "", ws, task["full_prompt"], scfg)
        env = dict(os.environ)
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        t0 = time.time()
        p = subprocess.Popen(argv, cwd=ws, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True, stdin=subprocess.DEVNULL)
        try:
            out, err = p.communicate(timeout=a.timeout)
            rec["timed_out"] = False
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            out, err = p.communicate()
            rec["timed_out"] = True
        rec["wall_s"] = round(time.time() - t0, 2)
        rec["exit"] = p.returncode
    finally:
        if tap:
            tap.__exit__(None, None, None)
    (ws / ".harness-stdout.jsonl").write_text(out or "")
    (ws / ".harness-stderr.txt").write_text(err or "")
    if tap:
        (ws / ".tap.json").write_text(json.dumps(tap.requests, indent=1))
        rec["tap"] = tap.summary()
    rec["harness_reported"] = stream_json_tools(out or "")
    f = ws / task["file"]
    if f.exists():
        text = f.read_text(errors="replace")
        rec["answer"] = text[:300]
        try:
            ok, detail = task["grade"](text)
        except Exception as e:
            ok, detail = False, f"grader error {e}"
        rec["ok"], rec["detail"] = bool(ok), str(detail)[:200]
    else:
        rec["ok"], rec["detail"], rec["answer"] = False, "no answer file", None
        rec["stderr_tail"] = (err or "")[-300:]
    return rec


# --------------------------------------------------------------------------- engine metrics

def scrape(url: str | None) -> dict:
    if not url:
        return {}
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode()
    except Exception as e:
        return {"_error": str(e)}
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, val = line.rpartition(" ")
        if not (name.startswith("tensorfold") or name.startswith("vllm")):
            continue
        try:
            out[name] = float(val)
        except ValueError:
            pass
    return out


def delta(before: dict, after: dict) -> dict:
    return {k: round(after[k] - before.get(k, 0.0), 3) for k in after
            if not k.startswith("_") and after[k] != before.get(k, 0.0)}


# --------------------------------------------------------------------------- main

def harness_version(a) -> dict:
    def run(cmd, cwd=None):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd).stdout.strip()[:200]
        except Exception as e:
            return f"? {e}"
    if a.harness == "pi":
        return {"name": "pi coding agent", "version": run([a.pi_bin, "--version"])}
    if a.harness in ("claude", "claude-shim"):
        return {"name": "Claude Code", "version": run([a.claude_bin, "--version"])}
    if a.harness == "dsh":
        v = {"name": "DeepSeek harness (dsh)"}
        if a.dsh_repo:
            v["tag"] = run(["git", "describe", "--tags"], a.dsh_repo)
            v["commit"] = run(["git", "rev-parse", "HEAD"], a.dsh_repo)
        v["sdk"] = run([a.dsh_python, "-c", "import importlib.metadata as m; print(m.version('deepseek-harness-sdk'), "
                        "m.version('deepseek-harness-runtime-bin'))"])
        v["profile"] = "sdk-minimal"
        return v
    return {}


def go_file_wait(path: str | None):
    if not path:
        return
    announced = False
    while not os.path.exists(path):
        if not announced:
            print(f"  [paused: {path} absent, waiting]", flush=True)
            announced = True
        time.sleep(15)
    if announced:
        print("  [resumed]", flush=True)


def summarize(rows: list[dict]) -> dict:
    by = {}
    for area in AREAS:
        rs = [r for r in rows if r["area"] == area]
        if not rs:
            continue
        ok = sum(r["ok"] for r in rs)
        by[area] = {"n": len(rs), "correct": ok, "accuracy": round(ok / len(rs), 4),
                    "no_answer_file": sum(1 for r in rs if r["detail"] == "no answer file"),
                    "timeouts": sum(1 for r in rs if r.get("timed_out"))}
    tot = {"tasks": len(rows), "wall_s_sum": round(sum(r.get("wall_s") or 0 for r in rows), 1),
           "harness_tool_calls": sum(r["harness_reported"]["tool_calls"] for r in rows)}
    taps = [r["tap"] for r in rows if r.get("tap")]
    if taps:
        for k in ("llm_requests", "errors", "prompt_tokens", "completion_tokens", "tool_calls", "reasoning_chars"):
            tot["tap_" + k] = sum(t[k] for t in taps)
        tot["tap_thinking_asked"] = sorted({x for t in taps for x in t["thinking_asked"]})
    return {"areas": by, "totals": tot}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--harness", required=True, choices=sorted(HARNESSES))
    ap.add_argument("--row", required=True, help="table row label, e.g. B")
    ap.add_argument("--base-url", default="", help="engine OpenAI base (…/v1); the tap maps /v1/* onto it")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default=None, help="venice mode only: upstream key")
    ap.add_argument("--venice", action="store_true", help="dry-run against Venice (see tap.py)")
    ap.add_argument("--thinking", action="store_true", help="thinking ON (default OFF, as qbench's default)")
    ap.add_argument("--areas", default=",".join(AREAS))
    ap.add_argument("--limit", type=int, default=None, help="first N tasks of each area (dry runs)")
    ap.add_argument("--only", default=None, help="comma list of task ids")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=600.0, help="per task (session) seconds, identical per row")
    ap.add_argument("--force-temperature", type=float, default=None,
                    help="control runs: the tap sets this temperature in every request (default: change nothing)")
    ap.add_argument("--metrics-url", default=None, help="engine /metrics, scraped before and after the row")
    ap.add_argument("--go-file", default=None, help="start a task only while this file exists")
    ap.add_argument("--ws-root", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pi-bin", default=shutil.which("pi") or "pi")
    ap.add_argument("--claude-bin", default=shutil.which("claude") or "claude")
    ap.add_argument("--dsh-python", default="python3", help="python of a venv with deepseek-harness-sdk")
    ap.add_argument("--dsh-repo", default=None, help="the harness checkout (for tag/commit in the result)")
    a = ap.parse_args()

    tasks = build_tasks([x for x in a.areas.split(",") if x], a.limit)
    if a.only:
        keep = set(a.only.split(","))
        tasks = [t for t in tasks if t["id"] in keep]
    ws_root = Path(a.ws_root or tempfile.mkdtemp(prefix=f"harness-{a.row}-"))
    cfg = ws_root / "_config"
    cfg.mkdir(parents=True, exist_ok=True)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"bench": "qbench-harness", "row": a.row, "harness": a.harness, "harness_version": harness_version(a),
              "model": a.model, "thinking": a.thinking, "timeout_s": a.timeout, "workers": a.workers,
              "mmlu_subset": f"mmlu200.jsonl items 0,{MMLU_STRIDE},...,196 (every {MMLU_STRIDE}th, 50 items)",
              "instruction": INSTRUCTION, "venice_dry_run": a.venice, "force_temperature": a.force_temperature, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "tasks": []}
    print(f"harness row {a.row}: {a.harness} model={a.model} thinking={a.thinking} tasks={len(tasks)} ws={ws_root}",
          flush=True)
    before = scrape(a.metrics_url)
    t0 = time.time()
    rows: list[dict] = []

    def one(t):
        go_file_wait(a.go_file)
        r = run_task(a, t, ws_root, cfg)
        tp = r.get("tap") or {}
        print(f"  {r['area']:6} {r['id']:22} {'PASS' if r['ok'] else 'fail'} {r.get('wall_s', 0):7.1f}s "
              f"llm={tp.get('llm_requests', '-')} tools={tp.get('tool_calls', r['harness_reported']['tool_calls'])} "
              f"{'' if r['ok'] else r['detail'][:60]}", flush=True)
        return r

    with cf.ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(one, tasks):
            rows.append(r)
            result["tasks"] = rows
            out.write_text(json.dumps(result, indent=1))
    after = scrape(a.metrics_url)
    result["wall_s"] = round(time.time() - t0, 1)
    result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result["engine_metrics_delta"] = delta(before, after) if before and after else None
    result["summary"] = summarize(rows)
    out.write_text(json.dumps(result, indent=1))
    s = result["summary"]
    print(json.dumps(s, indent=1))
    print(f"wrote {out}  wall {result['wall_s']}s")


if __name__ == "__main__":
    main()
