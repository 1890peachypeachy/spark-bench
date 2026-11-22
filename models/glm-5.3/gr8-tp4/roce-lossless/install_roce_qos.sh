#!/bin/bash
# Install + start the lossless-RoCE NIC service on all four Sparks (root via the vault helper). Idempotent.
H=~/recipe-db/spark-bench/models/glm-5.3/gr8-tp4/attic
U=~/.hermes/profiles/spark/cache/scratch/gr8-roce-qos.service
for n in spark1 spark2 spark3 spark4; do
  echo "################ $n"
  scp -q -o BatchMode=yes "$U" $n:/tmp/gr8-roce-qos.service || { echo "scp failed"; continue; }
  python3 $H/sudo_run.py $n 'install -m 0644 /tmp/gr8-roce-qos.service /etc/systemd/system/gr8-roce-qos.service && rm -f /tmp/gr8-roce-qos.service && systemctl daemon-reload && systemctl enable --now gr8-roce-qos.service 2>&1 | tail -2; echo "active=$(systemctl is-active gr8-roce-qos.service) enabled=$(systemctl is-enabled gr8-roce-qos.service)"; for i in enp1s0f1np1 enP2p1s0f1np1; do echo "$i: $(mlnx_qos -i $i 2>&1 | grep -E "trust state" | tr -s " \t" " ") | pfc: $(mlnx_qos -i $i 2>&1 | awk "/^\s+enabled/{printf \"%s \", \$0}" | tr -s " \t" " ")"; done'
done
