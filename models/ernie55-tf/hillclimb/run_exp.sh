#!/usr/bin/env bash
# One experiment, end to end, on spark3: launch (idle-gated) -> gates -> concurrency sweep -> long-context concurrency
# -> optional 66K cold/warm block. Each phase checks that the server finished exactly the requests the phase sent;
# any foreign request (the lane's live agents) writes $OUT/contaminated.
# Usage: run_exp.sh <name>   env: CONC (sweep levels, default 1,2,4,8; empty skips)  LONG (bench.py cold sizes, 12000)
#        LONGCTX (long-context levels, default 2,4; empty skips)  LONGCTX_TOK (default 64000)  LONGCTX_REPS (default 2)
#        SKIP_LAUNCH=1 benchmarks the lane already up;  SKIP_LONG=0 adds the w3 66K cold/warm block.
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
NAME=${1:?exp name}
OUT=$HC/results/$NAME
mkdir -p "$OUT"
rm -f "$OUT/contaminated"
# an exp env file may pin its own phases (SKIP_LONG=0 adds the 66K cold/warm block, CONC/SHORTCTX/LONGCTX levels)
eval "$(grep -E '^(SKIP_LONG|CONC|LONG|SHORTCTX|LONGCTX|LONGCTX_TOK|LONGCTX_REPS|PROBES|REPLAY)=' "$HC/exps/$NAME.env" 2>/dev/null)"
metric() { curl -s --max-time 3 http://127.0.0.1:8888/metrics | awk -v k="$1" '$1==k{print $2}'; }
count() { local c; c=$(metric tensorfold:request_latency_seconds_count); echo "${c%.*}"; }
running() { local r; r=$(metric tensorfold:requests_running); echo "${r%.*}"; }
check() { # phase, requests the phase sent, server count before the phase
  local now d r; now=$(count); d=$(( now - $3 )); r=$(running)
  if [ "$d" != "$2" ] || [ "${r:-0}" != 0 ]; then
    echo "CONTAMINATED in $1: server finished $d requests, phase sent $2, running ${r:-?}" | tee -a "$OUT/contaminated"
  else echo "clean $1: $d requests"; fi
}
{
  echo "== $(date -Is) $NAME"
  if [ "${SKIP_LAUNCH:-0}" != 1 ]; then
    bash $HC/launch_exp.sh "$NAME" || { echo "LAUNCH_FAILED"; exit 1; }
  fi
  sleep 10
  echo "== gate"
  python3 -I /var/tmp/ernie55/w3_bench.py --only gate > "$OUT/gate.txt" 2>&1; echo "gate rc=$?"; grep -E "GATE" "$OUT/gate.txt"
  if [ -n "${CONC-1,2,4,8}" ]; then
    echo "== sweep"
    c0=$(count)
    python3 -I $HC/bench.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 --label "$NAME" \
      --concurrency "${CONC:-1,2,4,8}" --max-tokens 384 --waves 2 --long "${LONG:-12000}" --out "$OUT/sweep.json" > "$OUT/sweep.log" 2>&1
    echo "sweep rc=$?"
    n=$(python3 -I -c "
import json
n=1  # bench.py's unprinted warm-up request
for l in open('$OUT/sweep.log'):
    l=l.strip()
    if l.startswith('{'):
        d=json.loads(l); n+=d.get('requests', 1 if 'target_prompt_tokens' in d else 0)
print(n)")
    check sweep "$n" "$c0"
    grep -E '^\{' "$OUT/sweep.log" | cut -c1-230
  fi
  if [ -n "${SHORTCTX-2,4,8}" ]; then
    # the same fixed greedy harness at a short context: drafting and launch overhead dominate there
    echo "== shortctx"
    c0=$(count)
    python3 -I $HC/longctx_conc.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 --ctx 1500 --seed ernie55-short-v1 \
      --conc "${SHORTCTX:-2,4,8}" --max-tokens 384 --reps 2 --out "$OUT/shortctx.json" > "$OUT/shortctx.log" 2>&1
    echo "shortctx rc=$?"
    n=$(grep -o '"requests": [0-9]*' "$OUT/shortctx.log" | tail -1 | awk '{print $2}')
    check shortctx "${n:-0}" "$c0"
    grep -E '^\{' "$OUT/shortctx.log" | grep -v '"warm"' | cut -c1-230
  fi
  if [ -n "${LONGCTX-2,4}" ]; then
    echo "== longctx"
    c0=$(count)
    python3 -I $HC/longctx_conc.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 --ctx "${LONGCTX_TOK:-64000}" \
      --conc "${LONGCTX:-2,4}" --max-tokens 384 --reps "${LONGCTX_REPS:-2}" --out "$OUT/longctx.json" > "$OUT/longctx.log" 2>&1
    echo "longctx rc=$?"
    n=$(grep -o '"requests": [0-9]*' "$OUT/longctx.log" | tail -1 | awk '{print $2}')
    check longctx "${n:-0}" "$c0"
    grep -E '^\{' "$OUT/longctx.log" | cut -c1-230
  fi
  if [ "${SKIP_LONG:-1}" != 1 ]; then
    echo "== long"
    python3 -I /var/tmp/ernie55/w3_bench.py --only cold66k,warm450,warm3312 > "$OUT/long.txt" 2>&1; echo "long rc=$?"
    grep -E "COLD|WARM" "$OUT/long.txt"
  fi
  if [ "${REPLAY:-0}" = 1 ]; then
    # prompt-cache sizing: agent replay (agent_replay.py) with MemAvailable sampled on all 4 Sparks every 10 s
    echo "== replay"
    grep -m1 "streams at once" "$HC/logs/${NAME}_r0.log" | sed 's/^.*model /model /' | cut -c1-260 > "$OUT/budget.txt"
    cat "$OUT/budget.txt"
    c0=$(count)
    MEMLOG="$OUT/memavail.log"; : > "$MEMLOG"
    ( while :; do t=$(date +%s); for h in local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
        if [ $h = local ]; then m=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
        else m=$(ssh -o BatchMode=yes -o ConnectTimeout=5 $h "awk '/MemAvailable/{print \$2}' /proc/meminfo" 2>/dev/null); fi
        echo "$t $h ${m:-NA}"; done >> "$MEMLOG"; sleep 10; done ) &
    sampler=$!
    timeout 3600 python3 -I $HC/agent_replay.py --url http://127.0.0.1:8888 --model GLM-5.3-Flash-EXL3 --out "$OUT/replay.json" > "$OUT/replay.log" 2>&1
    echo "replay rc=$?"
    kill $sampler 2>/dev/null; wait $sampler 2>/dev/null
    n=$(grep -o '"requests": [0-9]*' "$OUT/replay.log" | tail -1 | awk '{print $2}')
    check replay "${n:-0}" "$c0"
    grep -E '^\{"summary' "$OUT/replay.log" | cut -c1-600
    python3 -I -c "
import sys, collections
m = collections.defaultdict(list)
for l in open(sys.argv[1]):
    p = l.split()
    if len(p) == 3 and p[2].isdigit(): m[p[1]].append(int(p[2]) / 1048576)
print('min MemAvailable GiB:', {h: round(min(v), 1) for h, v in m.items()})" "$MEMLOG" | tee "$OUT/memavail-min.txt"
    grep -E "prompt cache: " "$HC/logs/${NAME}_r0.log" | tail -1 | sed 's/^.*prompt cache: /last prompt cache: /' | cut -c1-260
  fi
  if [ "${PROBES:-0}" = 1 ]; then
    # correctness on the WARM server, after the whole workload (the PAD corruption seen in x0 try 1 needed a long
    # session: fresh servers passed). Any PAD reply or missing code writes $OUT/probe_fail.
    echo "== probes (warm server)"
    timeout 900 python3 -I $HC/probe_mixed.py --out "$OUT/probe-mixed.json" > "$OUT/probe-mixed.log" 2>&1; echo "probe_mixed rc=$?"
    timeout 600 python3 -I $HC/probe_concurrency.py --out "$OUT/probe-concurrency.json" > "$OUT/probe-concurrency.log" 2>&1; echo "probe_concurrency rc=$?"
    cat "$OUT/probe-mixed.log" "$OUT/probe-concurrency.log" | grep -E '^\{"(phase|mode)"' | cut -c1-260
    if grep -h -E '^\{"(phase|mode)"' "$OUT/probe-mixed.log" "$OUT/probe-concurrency.log" | grep -q -E '"pad": true|"pad": [1-9]|"pad_replies": [1-9]|"all3": [0-7],'; then
      echo "PROBE FAIL: PAD or missing codes on the warm server" | tee "$OUT/probe_fail"
    else echo "probes clean"; fi
  fi
  if [ -f "$OUT/contaminated" ]; then echo "RESULT: CONTAMINATED"; else echo "RESULT: CLEAN"; fi
  echo "== $(date -Is) done $NAME"
} 2>&1 | tee "$HC/logs/$NAME.run.log"
