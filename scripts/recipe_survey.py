#!/usr/bin/env python3
"""Read-only survey of ~/recipe-db clones: fetch every remote, report ahead/behind vs each, dirty state."""
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.expanduser("~/recipe-db")
SKIP = {"_vet", "TensorFold-upstream"}  # _vet is scratch; TensorFold-upstream is a detached tag clone


def git(repo, *a, timeout=90):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def survey(name):
    repo = os.path.join(ROOT, name)
    out = {"name": name}
    if not os.path.isdir(os.path.join(repo, ".git")):
        out["note"] = "not a git repo"
        return out
    rc, remotes, _ = git(repo, "remote", "-v")
    rem = {}
    for line in remotes.splitlines():
        p = line.split()
        if len(p) >= 2 and line.endswith("(fetch)"):
            rem[p[0]] = p[1]
    out["remotes"] = rem
    rc, _, err = git(repo, "fetch", "--all", "-q", "--tags", timeout=120)
    out["fetch_err"] = err[:120] if rc else ""
    out["branch"] = git(repo, "branch", "--show-current")[1] or "(detached)"
    out["head"] = git(repo, "rev-parse", "--short", "HEAD")[1]
    out["dirty_tracked"] = len([l for l in git(repo, "status", "--porcelain")[1].splitlines() if not l.startswith("??")])
    out["untracked"] = len([l for l in git(repo, "status", "--porcelain")[1].splitlines() if l.startswith("??")])
    cmp = {}
    for r in rem:
        # default branch of that remote
        rc, sym, _ = git(repo, "symbolic-ref", "-q", f"refs/remotes/{r}/HEAD")
        ref = sym.replace("refs/remotes/", "") if sym else f"{r}/main"
        if git(repo, "rev-parse", "-q", "--verify", ref)[0]:
            ref = f"{r}/master"
            if git(repo, "rev-parse", "-q", "--verify", ref)[0]:
                continue
        rc, lr, _ = git(repo, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
        a, b = (lr.split() + ["?", "?"])[:2]
        cmp[ref] = {"ahead": a, "behind": b}
    out["cmp"] = cmp
    return out


names = sorted(d for d in os.listdir(ROOT) if d not in SKIP and os.path.isdir(os.path.join(ROOT, d)))
with ThreadPoolExecutor(max_workers=6) as ex:
    res = list(ex.map(survey, names))
json.dump(res, open(os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/recipe_survey.json"), "w"), indent=1)
print(f"{'repo':50} {'br':16} {'dirty':5} {'unt':4}  vs remotes (ahead/behind)")
for r in res:
    if "note" in r:
        print(f"{r['name']:50} {r['note']}")
        continue
    c = "  ".join(f"{k}:{v['ahead']}/{v['behind']}" for k, v in r["cmp"].items())
    print(f"{r['name'][:49]:50} {r['branch'][:15]:16} {r['dirty_tracked']:<5} {r['untracked']:<4}  {c}  {('FETCHERR ' + r['fetch_err']) if r['fetch_err'] else ''}")
