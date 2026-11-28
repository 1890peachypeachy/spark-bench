#!/usr/bin/env bash
# Promote a validated experiment binary to the ERNIE production lane (run on spark3):
#   idle gate -> back up the production binary -> stop all ranks -> copy the candidate (already staged on every
#   node at /var/tmp/ernie55/exp/<name>/bin by build_exp.sh) into /var/tmp/ernie55/bin on all 4 Sparks -> md5 check
#   -> restart with the recipe launcher -> gate + c8-mix probe on the production lane.
# Usage: deploy_fix.sh <exp name>
set -euo pipefail
NAME=${1:?exp}
HC=/var/tmp/ernie55/hillclimb/tf
SRC=/var/tmp/ernie55/exp/$NAME/bin/tensorfold-native
DST=/var/tmp/ernie55/bin/tensorfold-native
NODES="spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4"
md=$(md5sum $SRC | cut -c1-12)
for h in $NODES; do
  m=$(ssh -o BatchMode=yes $h "md5sum $SRC | cut -c1-12"); [ "$m" = "$md" ] || { echo "candidate md5 mismatch on $h"; exit 2; }
done
echo "== $(date -Is) deploying $NAME md5=$md"
clean=0
for i in $(seq 1 720); do
  m=$(curl -s --max-time 2 http://127.0.0.1:8888/metrics || true)
  r=$(echo "$m" | awk '/^tensorfold:requests_running /{print $2}'); w=$(echo "$m" | awk '/^tensorfold:requests_waiting /{print $2}')
  if [ "${r:-0}" = 0 ] && [ "${w:-0}" = 0 ]; then clean=$((clean+1)); else clean=0; fi
  [ $clean -ge 3 ] && break; sleep 5
done
[ $clean -ge 3 ] || { echo "lane busy for 60 min, not deploying"; exit 3; }
TS=$(date +%Y%m%dT%H%M)
cp -p $DST /var/tmp/ernie55/backups/tensorfold-native-$TS-pre-$NAME
echo "backup: /var/tmp/ernie55/backups/tensorfold-native-$TS-pre-$NAME ($(md5sum $DST | cut -c1-12))"
bash /var/tmp/ernie55/stop_tensorfold.sh
for i in $(seq 1 30); do
  n=0; for h in local $NODES; do
    if [ $h = local ]; then c=$(ps -eo cmd | grep -c "^/var/tmp/ernie55/.*bi[n]/tensorfold-native" || true); else c=$(ssh $h 'ps -eo cmd | grep -c "^/var/tmp/ernie55/.*bi[n]/tensorfold-native"' || true); fi
    n=$((n + c)); done
  [ $n -eq 0 ] && break; sleep 2
done
[ $n -eq 0 ] || { echo "ranks did not stop"; exit 4; }
cp $SRC $DST
for h in $NODES; do ssh -o BatchMode=yes $h "cp $SRC $DST"; done
for h in local $NODES; do
  if [ $h = local ]; then m=$(md5sum $DST | cut -c1-12); else m=$(ssh $h "md5sum $DST | cut -c1-12"); fi
  echo "$h $m"; [ "$m" = "$md" ] || { echo "MD5 MISMATCH on $h after copy"; exit 5; }
done
bash /var/tmp/ernie55/start_tensorfold.sh | tail -3
sleep 10
python3 -I /var/tmp/ernie55/w3_bench.py --only gate 2>&1 | grep GATE
python3 -I $HC/probe_concurrency.py --modes warmup,solo-nothink,c8-mix 2>&1 | grep -E '"mode": "c8-mix"' | cut -c1-220
echo "== $(date -Is) deployed $NAME md5=$md"
