#!/usr/bin/env python3
"""Landing-node verifier for the split MiniMax-M3.1-Flash download.

Waits for every helper's FANIN_DONE marker plus the landing node's own HALF_DONE,
then sha256-checks each LFS file (falling back to size equality for non-LFS blobs)
against the manifest built from the pinned revision's tree API.

Writes VERIFIED.txt with a pass/fail line per file and a final summary.
usage: m31_verify.py <model-dir> <manifest.json> <state-dir> <landing-tag> <helper1> [<helper2> ...]
"""
import hashlib, json, os, subprocess, sys, time

dest, manifest_path, state = sys.argv[1:4]
landing = sys.argv[4]
helpers = sys.argv[5:]

# helper tag -> fabric address (nodes cannot resolve the Mac's ssh aliases)
FABRIC = {"spark1": "10.73.0.1", "spark2": "10.73.0.2",
          "spark3": "10.73.0.3", "spark4": "10.73.0.4"}
HELPER_USER = {"spark1": "spark", "spark2": "spark2",
               "spark3": "spark3", "spark4": "spark4"}


def fabric_addr(tag):
    return f"{HELPER_USER.get(tag, tag)}@{FABRIC.get(tag, tag)}"
entries = json.load(open(manifest_path))

def need(path, timeout_h):
    t0 = time.time()
    while not os.path.exists(path):
        if time.time() - t0 > timeout_h * 3600:
            return False
        time.sleep(60)
    return True


def remote_marker(host, marker, timeout_h):
    """Helper half-markers are written ON the helper, never replicated to the landing
    node. Waiting for them locally deadlocks the verifier forever.
    Addresses go over the CX7 fabric (10.73.0.x) — the nodes do NOT resolve the Mac's
    spark1/spark4 ssh aliases."""
    t0 = time.time()
    while True:
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
                 f"test -f ~/m31-state/{marker} && echo yes"],
                capture_output=True, text=True, timeout=60)
            if "yes" in r.stdout:
                return True
        except Exception:
            pass
        if time.time() - t0 > timeout_h * 3600:
            return False
        time.sleep(60)

out_path = os.path.join(state, "VERIFIED.txt")
log = open(out_path, "w")

def w(msg):
    log.write(msg + "\n"); log.flush()

w(f"=== verify start {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ===")

# Landing node's own half-marker is LOCAL.
mk = os.path.join(state, f"HALF_DONE_{landing}")
if need(mk, 24):
    w(f"marker ok: HALF_DONE_{landing} (local)")
else:
    w(f"TIMEOUT waiting for HALF_DONE_{landing} (local)")
    w("RESULT: FAIL (missing landing half marker)"); log.close(); sys.exit(1)

# Helper half-markers live ON the helper; only FANIN_DONE_<helper> reaches this node.
for tag in helpers:
    if remote_marker(fabric_addr(tag), f"HALF_DONE_{tag}", 12):
        w(f"marker ok: HALF_DONE_{tag} (on {tag})")
    else:
        w(f"TIMEOUT waiting for HALF_DONE_{tag} on {tag}")
        w("RESULT: FAIL (missing helper half marker)"); log.close(); sys.exit(1)

for tag in helpers:
    mk = os.path.join(state, f"FANIN_DONE_{tag}")
    if not need(mk, 6):
        w(f"TIMEOUT waiting for FANIN_DONE_{tag}")
        w("RESULT: FAIL (missing fan-in marker)"); log.close(); sys.exit(1)
    w(f"marker ok: FANIN_DONE_{tag}")

bad, passed, sized = [], 0, 0
for e in entries:
    p = os.path.join(dest, e["name"])
    if not os.path.exists(p):
        bad.append((e["name"], "missing")); continue
    got = os.path.getsize(p)
    if got != e["size"]:
        bad.append((e["name"], f"size {got} != {e['size']}")); continue
    oid = e.get("sha256")
    if not oid:
        sized += 1; continue          # plain git blob: size gate only
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    if h.hexdigest() != oid:
        bad.append((e["name"], "sha256 mismatch")); continue
    passed += 1

total = sum(e["size"] for e in entries)
w(f"lfs sha256 verified: {passed}/{len([e for e in entries if e.get('sha256')])}")
w(f"size-only verified:  {sized}")
w(f"expected bytes: {total}  ({total/1024**3:.2f} GiB)")
if bad:
    for n, why in bad:
        w(f"BAD {n}: {why}")
    w(f"RESULT: FAIL ({len(bad)} bad files)")
    log.close(); sys.exit(1)
w("RESULT: PASS (all files present and hash/size verified)")
log.close()