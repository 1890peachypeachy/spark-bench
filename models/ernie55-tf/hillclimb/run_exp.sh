#!/usr/bin/env bash
# One experiment, end to end, on spark3: launch (idle-gated) -> correctness gates -> concurrency sweep -> cold/warm long.
# Usage: run_exp.sh <name>   env: CONC (default 1,2,4,8,16)  LONG (bench.py cold prompt sizes, default 12000)
#        SKIP_LAUNCH=1 benchmarks the lane already up;  SKIP_LONG=1 skips the 66K cold/warm block.
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
NAME=${1:?exp name}
OUT=$HC/results/$NAME
mkdir -p "$OUT"
count() { curl -s --max-time 3 http://127.0.0.1:8888/metrics | awk '/^tensorfold:request_latency_seconds_count /{print $2}'; }
{
  echo "== $(date -Is) $NAME"
  if [ "${SKIP_LAUNCH:-0}" != 1 ]; then
    bash $HC/launch_exp.sh "$NAME" || { echo "LAUNCH_FAILED"; exit 1; }
  fi
  sleep 10
  c0=$(count); echo "requests before: $c0"
  echo "== gate"
  python3 -I /var/tmp/ernie55/w3_bench.py --only gate > "$OUT/gate.txt" 2>&1; echo "gate rc=$?"; grep -E "GATE" "$OUT/gate.txt"
  echo "== sweep"
  python3 -I $HC/bench.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 --label "$NAME" \
    --concurrency "${CONC:-1,2,4,8,16}" --max-tokens 384 --waves 2 --long "${LONG:-12000}" --out "$OUT/sweep.json" > "$OUT/sweep.log" 2>&1
  echo "sweep rc=$?"
  python3 -I -c "
import json,sys
d=json.load(open('$OUT/sweep.json'))
for k in ('decode','results','waves','levels'):
    pass
print(open('$OUT/sweep.log').read()[-3000:])
" 2>/dev/null | grep -E '^\{' | cut -c1-260
  if [ "${SKIP_LONG:-0}" != 1 ]; then
    echo "== long"
    python3 -I /var/tmp/ernie55/w3_bench.py --only cold66k,warm450,warm3312 > "$OUT/long.txt" 2>&1; echo "long rc=$?"
    grep -E "COLD|WARM" "$OUT/long.txt"
  fi
  c1=$(count); echo "requests after: $c1 (delta $((${c1%.*} - ${c0%.*})))"
  echo "== $(date -Is) done $NAME"
} 2>&1 | tee "$HC/logs/$NAME.run.log"
