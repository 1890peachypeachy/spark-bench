#!/usr/bin/env bash
# Bisect the mixed prefill+decode PAD corruption: run probe_mixed.py (and a short probe_concurrency.py) on
#   1) r-w4base  = Wave-4 build bb1c1a0 (+ env-gated e2 knobs, all off)  -> before antigravity's W1/W4/W5
#   2) r-prod    = the production binary (1c4f515cc3a3, W1+W4+W5)        -> reproducibility of the failure
# then restore production with the recipe launcher once the lane is idle. Each launch is idle-gated.
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
running() { local r; r=$(curl -s --max-time 3 http://127.0.0.1:8888/metrics | awk '$1=="tensorfold:requests_running"{print $2}'); echo "${r%.*}"; }
{
  for exp in r-w4base r-prod; do
    echo "== $(date -Is) $exp"
    if ! bash $HC/launch_exp.sh "$exp"; then echo "LAUNCH_FAILED $exp"; continue; fi
    sleep 10
    timeout 600 python3 -I $HC/probe_mixed.py --out $HC/results/probe-mixed-$exp.json
    timeout 300 python3 -I $HC/probe_concurrency.py --modes solo-nothink,c8-nothink --out $HC/results/probe-concurrency-$exp.json
  done
  echo "== $(date -Is) restore production (waiting for an idle lane)"
  for i in $(seq 1 120); do [ "$(running)" = 0 ] && break; sleep 5; done
  bash /var/tmp/ernie55/start_tensorfold.sh
  echo "== $(date -Is) done"
} 2>&1 | tee $HC/logs/w4probe.log
