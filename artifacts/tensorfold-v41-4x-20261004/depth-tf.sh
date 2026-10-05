#!/usr/bin/env bash
# depth-tf.sh LABEL [DEPTHS]: the published depth sweep against the live TensorFold server, isolated like depth-run.sh.
set -euo pipefail
D=/home/jun/tf4; label=${1:?label}; extra=(); [ -n "${2:-}" ] && extra=( --depths "$2" )
mkdir -p $D/depth
rule=( "!" -i lo -p tcp --dport 8000 -m comment --comment tf4-depth -j REJECT )
sudo -n iptables -C INPUT "${rule[@]}" 2>/dev/null && { echo "isolation already present"; exit 1; }
touch $D/maintenance
cleanup() { sudo -n iptables -D INPUT "${rule[@]}" || true; rm -f $D/maintenance; }
sudo -n iptables -I INPUT 1 "${rule[@]}"; trap cleanup EXIT; trap "exit 130" INT TERM HUP
python3 /home/jun/tensorfold-v41-campaign-20261001/depth/depth_guard.py > $D/depth/$label-memory.jsonl 2>&1 & g=$!
python3 $D/bench-v41-depth-tf.py run --base http://127.0.0.1:8000 --fixtures $D/fixtures.json --output $D/depth/$label.jsonl --label $label --tokens 512 --reps 3 "${extra[@]}" | tee $D/depth/$label-progress.log
kill $g 2>/dev/null || true
