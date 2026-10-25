#!/bin/bash
# ablit_all.sh for OUR lane: ship each rank's blobs to its node and build cache-ablit on all four in parallel.
# Adapted from tonyd2wild runs/2026-10-18-1017-tensorfold-uncensored/tools/ablit_all.sh:
#   host map = our fabric (rank 0 spark3, 1 spark4, 2 spark1, 3 spark2); W = /var/tmp/tf1017-ablit.
# Runs ON spark3 (rank 0). Reads the live cache with direct IO only; writes cache-ablit/.
set -uo pipefail
W=/var/tmp/tf1017-ablit
R=(
  ""
  "spark4@10.73.0.4"
  "spark@10.73.0.1"
  "spark2@10.73.0.2"
)
for g in 1 2 3; do
  h=${R[$g]}
  ssh -n -o BatchMode=yes -o ConnectTimeout=10 "$h" "mkdir -p $W/overlay $W/blobs" &&
  scp -q $W/ablit_node.sh "$h":$W/ && scp -q $W/overlay/apply_rank_blobs.py "$h":$W/overlay/ &&
  scp -q -r $W/blobs/r$g "$h":$W/blobs/ || { echo "ship to rank $g failed"; exit 1; }
done
echo "shipped $(date -u +%T)"

bash $W/ablit_node.sh 0 > $W/node0.log 2>&1 &
for g in 1 2 3; do ssh -n -o BatchMode=yes "${R[$g]}" "bash $W/ablit_node.sh $g" > $W/node$g.log 2>&1 & done
wait
tail -n 3 $W/node*.log
