#!/usr/bin/env python3
"""Audit jspark3 lane prefill/resume health from the rank-0 engine log.

Why this exists: the lane is shared by ~15 Hermes profiles and is effectively
NEVER idle, so synthetic idle-gated decode benchmarks cannot be run against it
during the day (a 2026-10-07 attempt returned 8-10 tok/s purely from queueing,
with TTFT of 49-101 s). The engine log is better evidence than a contaminated
microbenchmark: it reports real production prefill, resume and decode per
request.

What to look for:
- Big-context requests (>=50K prompt tokens) arriving with `resumed=0` are the
  head-of-line blocker: each costs ~100 s of GPU monopoly at ~1400 tok/s and
  starves every other consumer. A handful of them can own most of the window's
  prefill time.
- Immediately after a cutover this is EXPECTED: v2.0.2 derives its session
  namespace from the wheel digest, so every session starts cold by design.
  Re-run this a few hours later. If big-context requests STILL show resumed=0
  once sessions are warm, it is a real defect worth chasing.

Usage:  lane-prefill-resume-audit.py [--since 40m] [--node spark3]
"""
import argparse, re, subprocess, sys

PAT = re.compile(
    r"request: (\d+) prompt tokens \((\d+) resumed(?:, (\d+) images)?\), "
    r"prefill ([\d.]+)s; (\d+) reply tokens in ([\d.]+)s \(([\d.]+) tok/s\)")
BIG = 50_000


def collect(node, since, container):
    cmd = ["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", node,
           f"docker logs --since {since} {container} 2>&1 | grep '^\\[tensorfold\\] request:'"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        m = PAT.search(line)
        if m:
            rows.append({
                "prompt": int(m.group(1)), "resumed": int(m.group(2)),
                "images": int(m.group(3) or 0), "prefill": float(m.group(4)),
                "reply": int(m.group(5)), "tps": float(m.group(7)),
                "tools": "tool_calls" in line,
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="40m")
    ap.add_argument("--node", default="spark3")
    ap.add_argument("--container", default="jspark3-rank0")
    a = ap.parse_args()

    rows = collect(a.node, a.since, a.container)
    if not rows:
        print(f"no request lines in the last {a.since} on {a.node} "
              f"({a.container}) — lane idle, log rotated, or container renamed")
        return 0

    n = len(rows)
    resumed = [r for r in rows if r["resumed"] > 0]
    big = [r for r in rows if r["prompt"] >= BIG]
    big_cold = [r for r in big if r["resumed"] == 0]
    pf_all = sum(r["prefill"] for r in rows) or 1.0
    pf_big = sum(r["prefill"] for r in big)

    print(f"window={a.since}  requests={n}")
    print(f"resume rate: {len(resumed)}/{n} = {len(resumed)/n*100:.0f}%")
    print(f"prefill GPU time: {pf_all:.0f}s total; "
          f">={BIG//1000}K-context share {pf_big:.0f}s = {pf_big/pf_all*100:.0f}%")
    print(f"big-context requests: {len(big)}  of which ZERO-resume: {len(big_cold)}")
    for r in sorted(big, key=lambda x: -x["prefill"])[:8]:
        rate = r["prompt"] / r["prefill"] if r["prefill"] else 0
        print(f"   prompt={r['prompt']:>7} resumed={r['resumed']:>7} "
              f"prefill={r['prefill']:>6.1f}s ({rate:>5.0f} tok/s) "
              f"reply={r['reply']:>4} @ {r['tps']:>5.1f} tok/s tools={r['tools']}")

    print("decode tok/s by reply length:")
    for lo, hi in ((0, 50), (50, 200), (200, 600), (600, 10**9)):
        s = sorted(r["tps"] for r in rows if lo <= r["reply"] < hi)
        if s:
            print(f"   reply {lo:>4}-{'+' if hi > 10**8 else hi:>5}: n={len(s):>3} "
                  f"median={s[len(s)//2]:>5.1f} max={max(s):>5.1f}")

    verdict = 0
    if big_cold and pf_big / pf_all > 0.5:
        print(f"\nFLAG: {len(big_cold)} big-context request(s) re-prefilled from "
              f"scratch and owned {pf_big/pf_all*100:.0f}% of prefill time.")
        print("      Post-cutover this is expected (fresh session namespace).")
        print("      Hours after a cutover it is a real resume defect — chase it.")
        verdict = 1
    else:
        print("\nOK: no dominant cold big-context prefill in this window.")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
