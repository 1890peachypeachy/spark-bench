#!/usr/bin/env bash
# Profile one experiment's rank 0 by phase: launch with PROFILE=1, drive, summarize kernels per phase.
# Usage: prof_run.sh <exp name>   (the exp env must set PROFILE=1; it may also set
#        DRIVER=<driver .py in $HC> (default prof_drive.py)  PHASES="..." (default "dec1 dec4 pre16k")
#        EXP_N=<requests the driver sends> (default 8), which idle_chain.sh checks for contamination)
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
NAME=${1:?exp}
OUT=$HC/results/$NAME
mkdir -p "$OUT"
DRIVER=prof_drive.py
PHASES="dec1 dec4 pre16k"
eval "$(grep -E '^(DRIVER|PHASES|EXP_N)=' "$HC/exps/$NAME.env")"
{
  echo "== $(date -Is) $NAME (profile: $DRIVER, phases $PHASES)"
  bash $HC/launch_exp.sh "$NAME" || { echo LAUNCH_FAILED; exit 1; }
  sleep 10
  python3 -I $HC/$DRIVER tfprof "$OUT"
  sleep 5
  for ph in $PHASES; do
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
