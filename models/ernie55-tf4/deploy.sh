set -e
bash /var/tmp/ernie55/stop_tensorfold.sh
cd /var/tmp/ernie55
for i in $(seq 1 30); do
  n=0; for h in local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
    if [ $h = local ]; then c=$(ps -eo cmd | grep -c "^/var/tmp/ernie55/bin/tensorfold-native" || true); else c=$(ssh $h 'ps -eo cmd | grep -c "^/var/tmp/ernie55/bin/tensorfold-native"' || true); fi
    n=$((n + c)); done
  [ $n -eq 0 ] && break; sleep 2
done
echo "ranks left: $n"
TS=$(date +%Y%m%dT%H%M)
cp bin/tensorfold-native backups/tensorfold-native-$TS
cp tensorfold-ernie/zig-out/native/bin/tensorfold-native bin/tensorfold-native
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do scp -q bin/tensorfold-native $h:/var/tmp/ernie55/bin/tensorfold-native & done; wait
md5sum bin/tensorfold-native | cut -c1-12
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do ssh $h md5sum /var/tmp/ernie55/bin/tensorfold-native | cut -c1-12; done
(nohup bash start_tensorfold.sh > logs/start_$(date +%H%M).out 2>&1 </dev/null &)
echo launched
