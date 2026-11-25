#!/usr/bin/env bash
set -euo pipefail

# Stop vLLM and any existing tensorfold-native across all 4 Sparks
for h in local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  if [ "$h" = local ]; then
    docker rm -f ernie55-tp4 >/dev/null 2>&1 || true
    pkill -f "bin/tensorfold-native" >/dev/null 2>&1 || true
  else
    ssh -o BatchMode=yes "$h" "docker rm -f ernie55-tp4 >/dev/null 2>&1 || true; pkill -f "bin/tensorfold-native" >/dev/null 2>&1 || true" &
  fi
done
wait
sleep 1

ENV_COMMON="LD_LIBRARY_PATH=/var/tmp/ernie55/lib NCCL_SOCKET_IFNAME=enp1s0f1np1 NCCL_IB_HCA=rocep1s0f1,roceP2p1s0f1 NCCL_IB_GID_INDEX=3 NCCL_IB_TC=106 NCCL_CROSS_NIC=1 NCCL_IB_SUBNET_AWARE_ROUTING=1 NCCL_P2P_DISABLE=1 NCCL_SHM_DISABLE=1 NCCL_ALGO=Ring NCCL_PROTO=Simple NCCL_MIN_NCHANNELS=4 NCCL_MAX_NCHANNELS=4 TF_ROCE=1 TF_ROCE_HCA=rocep1s0f1,roceP2p1s0f1 TF_ROCE_GID_INDEX=3"
ARGS_COMMON="/var/tmp/models/ERNIE-5.5-Flash-Preview --backend cuda --host 0.0.0.0 --port 8888 --name GLM-5.3-Flash-EXL3 --context 262144 --thinking --tp 4 --master 10.73.0.3 --master-port 29688"

mkdir -p /var/tmp/ernie55/logs

# Launch workers (ranks 3, 2, 1) first, then rank 0 (API server)
ssh -o BatchMode=yes spark4@10.73.0.4 "nohup env $ENV_COMMON /var/tmp/ernie55/bin/tensorfold-native serve $ARGS_COMMON --rank 3 >/tmp/tf_ernie_r3.log 2>&1 </dev/null &"
echo "launched rank 3 on spark4"
ssh -o BatchMode=yes spark2@10.73.0.2 "nohup env $ENV_COMMON /var/tmp/ernie55/bin/tensorfold-native serve $ARGS_COMMON --rank 2 >/tmp/tf_ernie_r2.log 2>&1 </dev/null &"
echo "launched rank 2 on spark2"
ssh -o BatchMode=yes spark@10.73.0.1  "nohup env $ENV_COMMON /var/tmp/ernie55/bin/tensorfold-native serve $ARGS_COMMON --rank 1 >/tmp/tf_ernie_r1.log 2>&1 </dev/null &"
echo "launched rank 1 on spark1"
nohup env $ENV_COMMON /var/tmp/ernie55/bin/tensorfold-native serve $ARGS_COMMON --rank 0 >/var/tmp/ernie55/logs/tf_ernie_r0.log 2>&1 </dev/null &
echo "launched rank 0 on spark3 (log: /var/tmp/ernie55/logs/tf_ernie_r0.log)"

echo "waiting for http://127.0.0.1:8888/v1/models ..."
for i in $(seq 1 140); do
  if curl -fsS --max-time 2 http://127.0.0.1:8888/v1/models >/tmp/tf_models.json 2>/dev/null; then
    echo "READY after $((i*3))s:"
    cat /tmp/tf_models.json
    echo ""
    exit 0
  fi
  if ! pgrep -f "bin/tensorfold-native" >/dev/null 2>&1; then
    echo "ERROR: rank 0 exited early! Log:"
    cat /var/tmp/ernie55/logs/tf_ernie_r0.log
    exit 1
  fi
  sleep 3
done
echo "TIMEOUT waiting for /v1/models! Tail of r0 log:"
tail -n 30 /var/tmp/ernie55/logs/tf_ernie_r0.log
exit 1
