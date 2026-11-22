#!/usr/bin/env python3
"""Sync selected ~/recipe-db clones with their REAL upstream. Local clones only; no node, lane or push.
ff   = fast-forward only (refuse otherwise)
merge= merge upstream into the current branch; any conflict -> abort and report (nothing half-merged)
Records pre-sync HEADs in recipe_sync_prev.json so each repo can be reset exactly."""
import json, os, subprocess, time

ROOT = os.path.expanduser("~/recipe-db")
SCR = os.path.expanduser("~/.hermes/profiles/spark/cache/scratch")
PLAN = [
    ("gr8", "origin/main", "ff"),
    ("jayleaton-dsv41-tensorfold-spark", "origin/main", "ff"),
    ("knapcio-dsv41-tp4", "origin/main", "ff"),
    ("DeepSeek-V4.1-Flash-1017-4x-TensorFold", "upstream-reference/main", "ff"),
    ("deepseek-v41-flash-tp4-recipe", "upstream/main", "ff"),
    ("qwen38-27b-nvfp4-dflash2-recipe", "upstream/main", "ff-stash"),
    ("glm-5.3-flash-4x-gx10", "upstream/main", "merge"),
    ("glm53-flash-nvfp4-4x-dspark-recipe", "upstream-reference/main", "merge"),
    ("GLM-5.3-Flash-EXL3-2x-DGX-Sparks", "origin/main", "merge"),
    ("spark-bench", "upstream/main", "merge"),
    ("DeepSeek-V4.1-Flash-1017-4x-GB10-TP4", "origin/1017", "merge"),
]
ENV = dict(os.environ, GIT_AUTHOR_NAME="spark", GIT_AUTHOR_EMAIL="spark@local", GIT_COMMITTER_NAME="spark", GIT_COMMITTER_EMAIL="spark@local")


def g(repo, *a, check=False):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, env=ENV)
    return r.returncode, (r.stdout + r.stderr).strip()


prev, rows = {}, []
for name, ref, mode in PLAN:
    repo = os.path.join(ROOT, name)
    head0 = g(repo, "rev-parse", "HEAD")[1]
    br = g(repo, "branch", "--show-current")[1]
    prev[name] = {"head": head0, "branch": br, "ref": ref, "mode": mode}
    rc, lr = g(repo, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
    ahead, behind = lr.split()
    row = {"repo": name, "branch": br, "ref": ref, "mode": mode, "ahead": int(ahead), "behind": int(behind), "result": "", "head1": head0[:8]}
    if int(behind) == 0:
        row["result"] = "already current"
        rows.append(row)
        continue
    stashed = False
    if mode == "ff-stash":
        rc, out = g(repo, "stash", "push", "-q", "-m", "recipe-sync-20261122")
        stashed = rc == 0 and "No local changes" not in out
    if mode.startswith("ff"):
        rc, out = g(repo, "merge", "--ff-only", ref)
        row["result"] = "fast-forwarded" if rc == 0 else f"FF REFUSED: {out[:120]}"
    else:
        rc, out = g(repo, "merge", "--no-edit", "-m", f"Merge {ref} (recipe sync 2026-11-22)", ref)
        if rc == 0:
            row["result"] = "merged clean"
        else:
            files = g(repo, "diff", "--name-only", "--diff-filter=U")[1].splitlines()
            g(repo, "merge", "--abort")
            row["result"] = f"CONFLICT in {len(files)} file(s), aborted: {', '.join(files[:5])}"
    if stashed:
        rc, out = g(repo, "stash", "pop", "-q")
        row["result"] += " | stash restored" if rc == 0 else f" | STASH POP FAILED: {out[:80]}"
    row["head1"] = g(repo, "rev-parse", "--short=8", "HEAD")[1]
    rows.append(row)

json.dump(prev, open(os.path.join(SCR, "recipe_sync_prev.json"), "w"), indent=1)
json.dump(rows, open(os.path.join(SCR, "recipe_sync_result.json"), "w"), indent=1)
for r in rows:
    print(f"{r['repo'][:42]:43} {r['mode']:9} +{r['ahead']}/-{r['behind']:<4} {r['result']}  [{prev[r['repo']]['head'][:7]} -> {r['head1'][:7]}]")
