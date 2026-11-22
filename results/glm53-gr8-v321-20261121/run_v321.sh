#!/bin/bash
# v3.2.1 own-harness bench: same scripts/args as the v3 (2026-11-21) run, plus a free-memory sample during x8.
cd "$(dirname "$0")" || exit 1
B=http://100.99.120.29:8888/v1; M=glm-5.3
N=$(ssh -o BatchMode=yes spark3 'docker logs --since 60s glm53-4x-spark 2>&1 | grep -ciE "request [0-9]+ prompt"')
echo "idle check: $N requests in last 60s"
[ "$N" = "0" ] || { echo "LANE BUSY - abort"; exit 1; }
echo "=== c1 screen ==="
python3 ~/recipe-db/spark-bench/bench/c1_decode_screen.py --base http://100.99.120.29:8888 --model $M --max-tokens 400 --repeat 3 --effort low --allow-busy --out c1_v321.json 2>&1 | sed -n '/median/,$p' | head -6
for n in 1 4 6; do echo "=== concurrent x$n ==="; python3 conc.py $B $M $n 600 2>&1 | tail -1 | tee conc${n}_v321.json; done
echo "=== concurrent x8 (+ MemAvailable sampling on all 4 nodes) ==="
for h in spark1 spark2 spark3 spark4; do
  ssh -o BatchMode=yes $h 'for i in $(seq 1 45); do awk "/MemAvailable/{print \$2}" /proc/meminfo; sleep 1.5; done' > mem_$h.txt &
done
python3 conc.py $B $M 8 600 2>&1 | tail -1 | tee conc8_v321.json
wait
for h in spark1 spark2 spark3 spark4; do echo -n "$h min MemAvailable during sampling: "; sort -n mem_$h.txt | head -1 | awk '{printf "%.1f GiB\n", $1/1048576}'; done
echo "=== DONE ==="
