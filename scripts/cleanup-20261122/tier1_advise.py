#!/usr/bin/env python3
"""Tier-1 targets from the sparkDash agent-junk scans: regenerable package/browser caches + OLD editor servers (never 'keep').
Ask the dashboard's delete advisor (read-only) to rate each path. Saves targets + advice to tier1_targets.json."""
import json, os, urllib.request, urllib.error

BASE = "http://127.0.0.1:5555"
SCAN = os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/storage_scan")
OUT = os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/tier1_targets.json")
RULES = {"package-cache", "browser-cache", "editor-server"}
targets = {}
for sid in ("spark1", "spark2", "spark3", "spark4"):
    items = json.load(open(f"{SCAN}/{sid}.json"))["junk"]["items"]
    sel = []
    for i in items:
        if i["rule"] in RULES and i["verdict"] in ("junk", "likely", "review") and i["bytes"] >= 50e6:
            codes = {s.get("code") for s in i.get("signals", []) if isinstance(s, dict)}
            if "current-version" in codes:
                continue
            # pip cache touched in the last few days may be in active use: skip anything the finder calls recent
            if "recent" in codes:
                continue
            m = i.get("modifiedAt")
            m = m / 1000 if m and m > 1e11 else m
            import time
            if m and (time.time() - m) < 5 * 86400:
                continue
            sel.append(i)
    targets[sid] = sel


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=180))
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read()[:400].decode("utf-8", "replace")}
    except Exception as e:
        return {"_error": str(e)[:200]}


total = 0
for sid, sel in targets.items():
    if not sel:
        print(f"{sid}: nothing selected")
        continue
    adv = post(f"/api/sparks/{sid}/storage/advise", {"paths": [i["path"] for i in sel]})
    targets[sid] = {"items": [{"path": i["path"], "bytes": i["bytes"], "rule": i["rule"], "verdict": i["verdict"]} for i in sel], "advice": adv}
    print(f"\n== {sid}: {len(sel)} items, {sum(i['bytes'] for i in sel)/1e9:.2f} GB")
    if "_error" in adv:
        print("   ADVISE ERROR", adv)
        continue
    res = adv.get("results") or adv.get("paths") or adv
    rows = res if isinstance(res, list) else list(res.values()) if isinstance(res, dict) else []
    for r in rows:
        if isinstance(r, dict):
            reasons = "; ".join((x.get("text") or x.get("rule") or str(x))[:60] for x in (r.get("reasons") or [])[:3])
            print(f"   {str(r.get('level')):7} {r.get('path')}  {reasons}")
    total += sum(i["bytes"] for i in sel)
print(f"\nTOTAL selected: {total/1e9:.2f} GB")
json.dump(targets, open(OUT, "w"), indent=1)
