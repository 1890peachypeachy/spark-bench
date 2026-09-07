#!/bin/bash
# run-arm.sh — wrap one benchmark arm with metrics snapshots + per-rank telemetry.
# Runs ON FORGE. Usage: run-arm.sh <armname> -- <q38bench args...>
# Fails closed: nonzero exit if contamination detected, bench fails, or metrics missing.
set -uo pipefail
D=/home/jun/qwen38-tuning-20260906
ARM="$1"; shift; [ "${1:-}" = "--" ] && shift
OUT="$D/arms/$ARM"
TEL="$D/telemetry-$ARM"
mkdir -p "$OUT" "$TEL/r0"
RANKS=(192.168.10.2 192.168.10.3 192.168.10.4)
echo "[$0] arm=$ARM ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 1) contamination check: no in-flight requests
MET=$(curl -sf -m 10 http://127.0.0.1:8000/metrics) || { echo "FAIL: metrics fetch"; exit 5; }
RUNNING=$(echo "$MET" | grep '^vllm:num_requests_running' | awk '{print $2}')
WAITING=$(echo "$MET" | grep '^vllm:num_requests_waiting{' | awk '{print $2}')
echo "running=$RUNNING waiting=$WAITING" | tee "$OUT/contamination.txt"
[ "${RUNNING:-x}" = "0.0" ] || { echo "FAIL-CLOSED: requests running at arm start"; exit 4; }
[ "${WAITING:-x}" = "0.0" ] || { echo "FAIL-CLOSED: requests waiting at arm start"; exit 4; }

# 2) metrics before
echo "$MET" > "$OUT/metrics-before.txt"

# 3) telemetry collectors on all ranks
for h in "${RANKS[@]}"; do
  mkdir -p "$TEL/r_$h"
  ssh -o BatchMode=yes "$h" "rm -f /tmp/q38tel-host.csv" 2>/dev/null || true   # clear stale
  scp -q -o BatchMode=yes /home/jun/qwen38-tuning-20260906/tel-collect.sh "$h:/tmp/q38tel-collect.sh" || { echo "FAIL: stage collector $h"; exit 6; }
  ssh -o BatchMode=yes "$h" "nohup bash /tmp/q38tel-collect.sh > /tmp/q38tel-host.csv 2>/dev/null < /dev/null &" || { echo "FAIL: start collector $h"; exit 6; }
done
nohup bash /home/jun/qwen38-tuning-20260906/tel-collect.sh > "$TEL/r0/host.csv" 2>/dev/null < /dev/null &
LOCAL_TEL_PID=$!
sleep 2
echo "telemetry started (local pid $LOCAL_TEL_PID)"

# 4) run the bench
set +e
python3 /home/jun/qwen38-tuning-20260906/q38bench.py "$@" --out "$OUT/bench" 2>&1 | tee "$OUT/bench-stdout.txt"
RC=${PIPESTATUS[0]}
set -e

# 5) stop telemetry + gather
kill "$LOCAL_TEL_PID" 2>/dev/null || true
for h in "${RANKS[@]}"; do
  ssh -o BatchMode=yes "$h" "pkill -f '[q]38tel-collect.sh'; sleep 1" 2>/dev/null || true
  scp -q -o BatchMode=yes "$h:/tmp/q38tel-host.csv" "$TEL/r_$h/host.csv" 2>/dev/null || echo "WARN: no telemetry from $h"
  ssh -o BatchMode=yes "$h" "rm -f /tmp/q38tel-host.csv /tmp/q38tel-collect.sh" 2>/dev/null || true
done

# 6) metrics after + MTP delta
curl -sf -m 10 http://127.0.0.1:8000/metrics > "$OUT/metrics-after.txt" || { echo "FAIL: metrics fetch after"; exit 5; }
python3 - "$OUT" <<'PYEOF'
import sys, re
d = sys.argv[1]
names = {"vllm:spec_decode_num_drafts_total", "vllm:spec_decode_num_accepted_tokens_total",
         "vllm:spec_decode_num_draft_tokens_total"}
def grab(path):
    out = {}
    for line in open(path):
        m = re.match(r'^(\S+)\{.*\}\s+([0-9.e+-]+)$', line.strip())
        if m and m.group(1) in names:
            out.setdefault(m.group(1), float(m.group(2)))
    return out
b = grab(d + "/metrics-before.txt"); a = grab(d + "/metrics-after.txt")
deltas = {k: round(a[k] - b[k], 1) for k in names if k in a and k in b}
acc = deltas.get("vllm:spec_decode_num_accepted_tokens_total")
drafted = deltas.get("vllm:spec_decode_num_draft_tokens_total")
import json
open(d + "/mtp-delta.json", "w").write(json.dumps(deltas))
print("MTP deltas:", deltas, "accept-rate=", round(acc/drafted, 4) if drafted else "n/a")
PYEOF

# 7) contamination re-check
RUNNING2=$(curl -sf -m 10 http://127.0.0.1:8000/metrics | grep '^vllm:num_requests_running' | awk '{print $2}')
echo "running-after=$RUNNING2" >> "$OUT/contamination.txt"

# 8) metadata
cat > "$OUT/metadata.json" <<META
{"arm": "$ARM", "ts": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "bench_rc": $RC,
 "args": "$*",
 "mtp_tokens_env": "$(docker inspect qwen38-nvfp4 --format '{{range .Config.Env}}{{if eq (slice . 0 10) "MTP_TOKENS="}}{{.}}{{end}}{{end}}' 2>/dev/null)",
 "compaction": "$(cat /proc/sys/vm/compaction_proactiveness)",
 "cpuset": "$(docker inspect qwen38-nvfp4 --format '{{.HostConfig.CpusetCpus}}' 2>/dev/null)"}
META
echo "[$0] arm=$ARM done, bench_rc=$RC"
exit $RC
