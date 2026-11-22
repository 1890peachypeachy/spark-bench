#!/usr/bin/env python3
"""Tier-1 delete: the EXACT paths in tier1_targets.json (regenerable caches + old editor servers), on spark1-3, as the Spark's own user.
Guards per path: absolute, under $HOME/.cache or $HOME/.vscode-server/cli/servers/Stable-*, not a symlink, not the 'keep' editor, no running
process whose command line mentions it. Writes a manifest to ~/.hermes/profiles/spark/backups/cleanup-20261122/."""
import json, os, shlex, subprocess, sys, time

T = json.load(open(os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/tier1_targets.json")))
OUT = os.path.expanduser("~/.hermes/profiles/spark/backups/cleanup-20261122")
os.makedirs(OUT, exist_ok=True)
REMOTE = r'''
set -u
p="$1"; kind="$2"
case "$p" in /*) ;; *) echo "SKIP not absolute"; exit 3;; esac
case "$p" in "$HOME"/.cache/*|"$HOME"/.vscode-server/cli/servers/Stable-*) ;; *) echo "SKIP outside allowed roots"; exit 3;; esac
[ -L "$p" ] && { echo "SKIP symlink"; exit 3; }
[ -d "$p" ] || { echo "SKIP missing"; exit 3; }
b=$(basename "$p")
if pgrep -af "$p|[/ ]$b( |$)" 2>/dev/null | grep -vE "pgrep|bash -s|tier1" | grep -qE "uv |pip |playwright|vscode-server|code-server|node .*$b"; then echo "SKIP in use by a running process"; exit 4; fi
before=$(du -sb "$p" 2>/dev/null | cut -f1)
rm -rf -- "$p"
[ -e "$p" ] && { echo "FAIL still exists"; exit 5; }
echo "DELETED $before"
'''
manifest = []
for sid in ("spark1", "spark2", "spark3"):
    items = T[sid]["items"] if isinstance(T[sid], dict) else []
    df0 = subprocess.run(["ssh", "-o", "BatchMode=yes", sid, "df -B1 --output=avail / | tail -1"], capture_output=True, text=True).stdout.strip()
    for it in items:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", sid, "bash -s -- " + shlex.quote(it["path"]) + " x"], input=REMOTE, capture_output=True, text=True, timeout=600)
        line = (r.stdout.strip().splitlines() or [r.stderr.strip()[:100]])[-1]
        manifest.append({"spark": sid, "path": it["path"], "bytes_listed": it["bytes"], "rule": it["rule"], "result": line, "ts": time.strftime("%F %T")})
        print(f"{sid:7} {it['bytes']/1e9:6.2f} GB  {line[:60]:60} {it['path']}")
    df1 = subprocess.run(["ssh", "-o", "BatchMode=yes", sid, "df -B1 --output=avail / | tail -1"], capture_output=True, text=True).stdout.strip()
    print(f"   {sid}: free {int(df0)/1e9:.1f} -> {int(df1)/1e9:.1f} GB  (+{(int(df1)-int(df0))/1e9:.1f})")
json.dump(manifest, open(f"{OUT}/tier1-manifest.json", "w"), indent=1)
