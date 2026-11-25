#!/usr/bin/env bash
# ERNIE vLLM hill-climb runner (spark3, rank 0). One experiment per boot, serialized by a lock, detached-safe.
#   hc.sh NAME [NAME ...]      NAME = exps/NAME.env (bash: exports overrides for the recipe's start.sh)
# Special names: probe-hw (lane stays down, measures bandwidth + GEMM in a throwaway container).
# exps/NAME.env may set PROFILE=1: capture a torch profile mid-decode instead of running the bench.
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb
KIT=/var/tmp/ernie55/recipe
API=http://127.0.0.1:8888
NODES=(local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4)
mkdir -p "$HC/logs" "$HC/configs"
exec 9>"$HC/.lock"; flock -n 9 || { echo "another hill-climb run holds $HC/.lock"; exit 1; }
log() { echo "$(date +%H:%M:%S) $*" | tee -a "$HC/logs/queue.log"; }
onnode() { if [[ "$1" == local ]]; then bash -c "$2"; else ssh -n -o BatchMode=yes -o ConnectTimeout=10 "$1" "$2"; fi; }

wait_idle() {  # we are the only client; still never stop mid-request
  local i run
  for i in $(seq 1 120); do
    run=$(curl -s -m 5 "$API/metrics" 2>/dev/null | awk '/^vllm:num_requests_(running|waiting)\{/ {s+=$2} END {print s+0}')
    [[ "${run:-0}" == 0 ]] && return 0
    sleep 5
  done
  log "WARN: requests still running after 10 min; stopping anyway"
}
lane_down() {
  wait_idle
  (cd "$KIT" && ./stop.sh) >> "$HC/logs/stop.log" 2>&1
  local n left=""
  for n in "${NODES[@]}"; do [[ -n "$(onnode "$n" 'docker ps -aq --filter name=^/ernie55-tp4$')" ]] && left="$left $n"; done
  [[ -z "$left" ]] || { log "FATAL: containers left on:$left"; exit 2; }
}
spec_snap() { curl -s -m 10 "$API/metrics" | awk '/^vllm:spec_decode_num_(drafts|draft_tokens|accepted_tokens)_total\{/ {split($1,a,"{"); print a[1], $2} /^vllm:spec_decode_num_accepted_tokens_per_pos_total\{/ {match($0,/position="[0-9]+"/); print "pos" substr($0,RSTART+10,RLENGTH-11), $2}'; }

for NAME in "$@"; do
  log "=== $NAME"
  if [[ "$NAME" == probe-hw ]]; then
    lane_down
    docker run --rm --gpus all --entrypoint python3 -v "$HC/scripts:/s:ro" ernie55-vllm:3f0400d1bc4d -I /s/probe_hw.py > "$HC/logs/probe-hw.json" 2> "$HC/logs/probe-hw.err"
    log "probe-hw rc=$? $(tr -d '\n' < "$HC/logs/probe-hw.json" | cut -c1-300)"
    continue
  fi
  [[ -f "$HC/exps/$NAME.env" ]] || { log "FATAL: no exps/$NAME.env"; exit 2; }
  lane_down
  t0=$(date +%s)
  ( set -a; PROFILE=0; KIT_DIR=$KIT; source "$HC/exps/$NAME.env"; set +a; cd "$KIT_DIR" && ./start.sh ) > "$HC/logs/$NAME.start.log" 2>&1
  rc=$?; startup=$(( $(date +%s) - t0 ))
  if [[ $rc -ne 0 ]] || ! grep -q '^READY' "$HC/logs/$NAME.start.log"; then
    log "START FAILED rc=$rc after ${startup}s: $(grep -E '^\[E_|rror' "$HC/logs/$NAME.start.log" | tail -2 | tr '\n' ' ' | cut -c1-240)"
    printf '{"name":"%s","ok":false,"error":"start failed","startup_s":%s}\n' "$NAME" "$startup" >> "$HC/ledger.jsonl"
    onnode local "docker logs --tail 80 ernie55-tp4" > "$HC/logs/$NAME.rank0.tail" 2>&1
    continue
  fi
  log "READY after ${startup}s"
  PROFILE=0; source "$HC/exps/$NAME.env"
  if [[ "${PROFILE:-0}" == 1 ]]; then
    curl -s -m 600 "$API/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model":"GLM-5.3-Flash-EXL3","messages":[{"role":"user","content":"Write a Python implementation of an LRU cache with O(1) get and put, with docstrings and tests."}],"max_tokens":1024,"temperature":0.6,"seed":1234}' \
      -o "$HC/logs/$NAME.req.json" &
    req=$!; sleep 6
    curl -s -m 120 -X POST "$API/start_profile" > "$HC/logs/$NAME.startprof" 2>&1; sleep 5
    curl -s -m 600 -X POST "$API/stop_profile" > "$HC/logs/$NAME.stopprof" 2>&1
    wait "$req"; log "profile captured: $(ls -1 /var/tmp/ernie55/cache/prof 2>/dev/null | tail -3 | tr '\n' ' ')"
    continue
  fi
  sed "s/@NAME@/$NAME/" "$HC/configs/bench.template.json" > "$HC/configs/run-$NAME.json"
  spec_snap > "$HC/logs/$NAME.m0"
  (cd "$HC" && python3 -I scripts/bench.py run "configs/run-$NAME.json" --reps 6) > "$HC/logs/$NAME.bench.log" 2>&1
  spec_snap > "$HC/logs/$NAME.m1"
  (cd "$HC" && python3 -I scripts/equiv.py "$NAME-$(date +%H%M)") >> "$HC/logs/$NAME.equiv.log" 2>&1
  python3 -I - "$NAME" "$startup" "$HC/logs/$NAME.m0" "$HC/logs/$NAME.m1" >> "$HC/spec.jsonl" <<'PY'
import json, sys
name, startup, a, b = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
rd = lambda p: {l.split()[0]: float(l.split()[1]) for l in open(p) if l.strip()}
m0, m1 = rd(a), rd(b)
d = {k: m1.get(k, 0) - m0.get(k, 0) for k in m1}
dr = d.get("vllm:spec_decode_num_drafts_total", 0); dt = d.get("vllm:spec_decode_num_draft_tokens_total", 0)
ac = d.get("vllm:spec_decode_num_accepted_tokens_total", 0)
out = {"name": name, "startup_s": startup, "drafts": int(dr), "accept_rate": round(ac / dt, 3) if dt else None,
       "tokens_per_step": round(1 + ac / dr, 3) if dr else None,
       "per_pos": {k[3:]: round(v / dr, 3) for k, v in sorted(d.items()) if k.startswith("pos")} if dr else {}}
print(json.dumps(out))
PY
  log "bench done: $(tail -1 "$HC/ledger.jsonl" | cut -c1-260)"
  log "spec: $(tail -1 "$HC/spec.jsonl")"
done
log "queue finished: $*"
