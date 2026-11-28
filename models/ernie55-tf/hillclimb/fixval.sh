#!/usr/bin/env bash
# Validate a fix candidate on the lane (spark3), end to end:
#   launch (idle-gated) -> gates -> probes incl. c8-mix -> sampled-mix stress -> perf sweep + 66K needle block.
# Prints PASS/FAIL per check and a final verdict line. Leaves the candidate running (the caller decides what's next).
# Usage: fixval.sh <exp name> [stress minutes=8]
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
NAME=${1:?exp}; MIN=${2:-8}
OUT=$HC/results/$NAME
mkdir -p "$OUT"
fail=0
v() { if [ "$2" = ok ]; then echo "PASS $1"; else echo "FAIL $1: $3"; fail=1; fi; }
{
  echo "== $(date -Is) fix validation $NAME"
  bash $HC/launch_exp.sh "$NAME" || { echo "LAUNCH_FAILED"; exit 1; }
  sleep 10
  python3 -I /var/tmp/ernie55/w3_bench.py --only gate > "$OUT/gate.txt" 2>&1
  if grep -q "ok=True ans='391'" "$OUT/gate.txt" && grep -q "GATE tools: ok=True" "$OUT/gate.txt"; then v gate ok; else v gate bad "$(grep GATE "$OUT/gate.txt" | tr '\n' ' ')"; fi
  timeout 900 python3 -I $HC/probe_concurrency.py --out "$OUT/probe-concurrency.json" > "$OUT/probe-concurrency.log" 2>&1
  grep -E '^\{"mode"' "$OUT/probe-concurrency.log" | cut -c1-240
  mix=$(grep -E '^\{"mode": "c8-mix"' "$OUT/probe-concurrency.log")
  if echo "$mix" | grep -q '"pad_replies": 0' && echo "$mix" | grep -q '"greedy_all3": 4'; then v c8-mix ok; else v c8-mix bad "$mix"; fi
  if grep -E '^\{"mode"' "$OUT/probe-concurrency.log" | grep -q -E '"pad_replies": [1-9]'; then v probes-no-pad bad "a mode had PAD"; else v probes-no-pad ok; fi
  timeout 600 python3 -I $HC/probe_mixed.py --out "$OUT/probe-mixed.json" > "$OUT/probe-mixed.log" 2>&1
  grep -E '^\{"phase"' "$OUT/probe-mixed.log" | cut -c1-200
  if grep -E '^\{"phase"' "$OUT/probe-mixed.log" | grep -q -E '"pad": (true|[1-9])|"all3": [0-7],'; then v probe-mixed bad "PAD or missing codes"; else v probe-mixed ok; fi
  timeout $((MIN * 60 + 600)) python3 -I $HC/stress_pad2.py --mix sampled --minutes "$MIN" --workers 8 --seed ernie55-stress-v3 --out "$OUT/stress-sampled.jsonl" > "$OUT/stress-sampled.log" 2>&1
  tail -1 "$OUT/stress-sampled.log" | cut -c1-200
  bad=$(grep -c '"bad": true' "$OUT/stress-sampled.jsonl"); tot=$(grep -c '' "$OUT/stress-sampled.jsonl")
  if [ "$bad" = 0 ] && [ "$tot" -gt 20 ]; then v stress-sampled ok; else v stress-sampled bad "$bad bad of $tot"; fi
  SKIP_LAUNCH=1 SKIP_LONG=0 SHORTCTX= LONGCTX= bash $HC/run_exp.sh "$NAME-perf" > "$OUT/perf.log" 2>&1
  grep -E '^\{"concurrency"|COLD|WARM|RESULT' "$OUT/perf.log" | cut -c1-200
  if grep -q "needle=True (3/3)" "$OUT/perf.log" && [ "$(grep -c 'needle=True' "$OUT/perf.log")" -ge 3 ]; then v needle-66k ok; else v needle-66k bad "$(grep -E 'COLD|WARM' "$OUT/perf.log" | tr '\n' ' ')"; fi
  if [ $fail = 0 ]; then echo "VERDICT: ALL PASS"; else echo "VERDICT: FAIL"; fi
  echo "== $(date -Is) done"
} 2>&1 | tee "$HC/logs/$NAME.fixval.log"
