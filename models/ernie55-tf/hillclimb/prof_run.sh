#!/usr/bin/env bash
# Profile one experiment's rank 0 by phase (dec1, dec4, pre16k): launch with PROFILE=1, drive, summarize kernels.
# Usage: prof_run.sh <exp name>   (the exp env must set PROFILE=1)
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
NAME=${1:?exp}
OUT=$HC/results/$NAME
mkdir -p "$OUT"
{
  echo "== $(date -Is) $NAME (profile)"
  bash $HC/launch_exp.sh "$NAME" || { echo LAUNCH_FAILED; exit 1; }
  sleep 10
  python3 -I $HC/prof_drive.py tfprof "$OUT"
  sleep 5
  for ph in dec1 dec4 pre16k; do
    rep="$OUT/prof_$ph.nsys-rep"
    [ -f "$rep" ] || { echo "no $rep"; continue; }
    /usr/local/bin/nsys stats --force-export=true --report cuda_gpu_trace --format csv --output "$OUT/$ph" "$rep" >/dev/null 2>&1
    csv=$(ls "$OUT"/${ph}_cuda_gpu_trace.csv 2>/dev/null | head -1)
    echo "==== $ph"
    [ -n "$csv" ] && python3 -I $HC/trace_top.py "$csv" 28
  done
  /usr/local/bin/nsys shutdown --session=tfprof >/dev/null 2>&1 || true
  echo "== $(date -Is) done $NAME"
} 2>&1 | tee "$HC/logs/$NAME.prof.log"
