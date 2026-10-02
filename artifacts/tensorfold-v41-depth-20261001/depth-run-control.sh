#!/usr/bin/env bash
set -euo pipefail
D=/home/jun/tensorfold-v41-campaign-20261001/depth
label=${1:?label required}
extra=()
if [ -n "${2:-}" ]; then extra=( --depths "$2" ); fi
rule=( '!' -i lo -p tcp --dport 8000 -m comment --comment tensorfold-v41-depth -j REJECT )
if sudo -n iptables -C INPUT "${rule[@]}" 2>/dev/null; then echo 'Isolation already present'; exit 1; fi
guard_pid=''
cleanup() {
 if [ -n "$guard_pid" ]; then kill "$guard_pid" 2>/dev/null || true; wait "$guard_pid" 2>/dev/null || true; fi
 sudo -n iptables -D INPUT "${rule[@]}" || true
}
sudo -n iptables -I INPUT 1 "${rule[@]}"
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
python3 "$D/depth_guard.py" > "$D/$label-memory.jsonl" 2>&1 &
guard_pid=$!
curl -fsS http://127.0.0.1:8000/v1/loads > "$D/$label-loads-before.json"
python3 "$D/bench-v41-depth-ab.py" run --fixtures "$D/fixtures.json" --output "$D/$label.jsonl" --label "$label" --tokens 512 --reps 3 "${extra[@]}" | tee "$D/$label-progress.log"
curl -fsS http://127.0.0.1:8000/v1/loads > "$D/$label-loads-after.json"
