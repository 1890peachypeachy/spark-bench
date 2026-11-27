#!/usr/bin/env bash
# ERNIE-5.5 TensorFold TP4 experiment launcher (spark3 = rank 0).
# Mirrors /var/tmp/ernie55/start_tensorfold.sh (the recipe launcher) exactly, plus one experiment's delta:
#   exps/<name>.env may set  BIN=<path to tensorfold-native on every node>  (default: production bin)
#                            PCG=<prompt cache GiB> (default 6, the recipe's value)
#                            EXTRA_ENV="K=V ..."  EXTRA_ARGS="--flag v ..."
# Usage: launch_exp.sh <name>     (idle-gated: waits until :8888 has no running/waiting requests)
set -euo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
NAME=${1:?exp name}
EXP=$HC/exps/$NAME.env
[ -f "$EXP" ] || { echo "no $EXP" >&2; exit 2; }
BIN=/var/tmp/ernie55/bin/tensorfold-native
PCG=6
EXTRA_ENV=""
EXTRA_ARGS=""
# shellcheck disable=SC1090
source "$EXP"
mkdir -p $HC/logs
LOG=$HC/logs/${NAME}_r0.log

# --- idle gate: three clean reads 5 s apart (skip when the server is already down)
if curl -fsS --max-time 2 http://127.0.0.1:8888/v1/models >/dev/null 2>&1; then
  clean=0
  for i in $(seq 1 720); do
    m=$(curl -s --max-time 2 http://127.0.0.1:8888/metrics || true)
    r=$(echo "$m" | awk '/^tensorfold:requests_running /{print $2}')
    w=$(echo "$m" | awk '/^tensorfold:requests_waiting /{print $2}')
    if [ "${r:-0}" = 0 ] && [ "${w:-0}" = 0 ]; then clean=$((clean+1)); else clean=0; fi
    [ $clean -ge 3 ] && break
    sleep 5
  done
  [ $clean -ge 3 ] || { echo "IDLE GATE: lane busy for 60 min, not restarting" >&2; exit 3; }
fi

# --- binary present and identical on all 4 nodes
md0=$(md5sum "$BIN" | cut -c1-12)
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  m=$(ssh -o BatchMode=yes $h "md5sum $BIN 2>/dev/null | cut -c1-12" || true)
  [ "$m" = "$md0" ] || { echo "binary mismatch on $h ($m vs $md0)" >&2; exit 4; }
done

bash /var/tmp/ernie55/stop_tensorfold.sh
for i in $(seq 1 30); do
  n=0; for h in local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
    if [ $h = local ]; then c=$(ps -eo cmd | grep -c "^/var/tmp/ernie55/.*bin/tensorfold-native" || true); else c=$(ssh $h 'ps -eo cmd | grep -c "^/var/tmp/ernie55/.*bin/tensorfold-native"' || true); fi
    n=$((n + c)); done
  [ $n -eq 0 ] && break; sleep 2
done
echo "ranks left: $n"
[ $n -eq 0 ] || { echo "ranks did not stop" >&2; exit 5; }

ENV_COMMON="LD_LIBRARY_PATH=/var/tmp/ernie55/lib NCCL_SOCKET_IFNAME=enp1s0f1np1 NCCL_IB_HCA=rocep1s0f1,roceP2p1s0f1 NCCL_IB_GID_INDEX=3 NCCL_IB_TC=106 NCCL_CROSS_NIC=1 NCCL_IB_MERGE_NICS=0 NCCL_IB_SUBNET_AWARE_ROUTING=1 NCCL_IB_SUBNET_PREFIX_LEN=24 NCCL_CUMEM_ENABLE=1 NCCL_IGNORE_CPU_AFFINITY=1 NCCL_IB_DISABLE=0 NCCL_RUNTIME_CONNECT=1 NCCL_P2P_DISABLE=1 NCCL_SHM_DISABLE=1 NCCL_ALGO=Ring NCCL_MIN_NCHANNELS=4 NCCL_MAX_NCHANNELS=4 TF_ROCE=1 TF_ROCE_HCA=rocep1s0f1,roceP2p1s0f1 TF_ROCE_GID_INDEX=3 $EXTRA_ENV"
ARGS_COMMON="/var/tmp/models/ERNIE-5.5-Flash-Preview --backend cuda --host 0.0.0.0 --port 8888 --name GLM-5.3-Flash-EXL3 --context 262144 --thinking --prompt-cache-gib $PCG --tp 4 --master 10.73.0.3 --master-port 29688 $EXTRA_ARGS"
echo "$(date -Is) exp=$NAME bin=$BIN md5=$md0" > $HC/logs/${NAME}.launch
echo "ENV: $ENV_COMMON" >> $HC/logs/${NAME}.launch
echo "ARGS: $ARGS_COMMON" >> $HC/logs/${NAME}.launch

ssh -o BatchMode=yes spark4@10.73.0.4 "nohup env $ENV_COMMON $BIN serve $ARGS_COMMON --rank 3 >/tmp/tf_ernie_r3.log 2>&1 </dev/null &"
ssh -o BatchMode=yes spark2@10.73.0.2 "nohup env $ENV_COMMON $BIN serve $ARGS_COMMON --rank 2 >/tmp/tf_ernie_r2.log 2>&1 </dev/null &"
ssh -o BatchMode=yes spark@10.73.0.1  "nohup env $ENV_COMMON $BIN serve $ARGS_COMMON --rank 1 >/tmp/tf_ernie_r1.log 2>&1 </dev/null &"
# PROFILE=1 (exp env): rank 0 under an nsys session "tfprof" that collects nothing until `nsys start --session=tfprof`
R0_PREFIX=""
if [ "${PROFILE:-0}" = 1 ]; then
  /usr/local/bin/nsys shutdown --session=tfprof >/dev/null 2>&1 || true
  R0_PREFIX="/usr/local/bin/nsys launch --session-new=tfprof --trace=cuda,nvtx,osrt --cuda-graph-trace=node --sample=none --cpuctxsw=none"
fi
nohup env $ENV_COMMON $R0_PREFIX $BIN serve $ARGS_COMMON --rank 0 >$LOG 2>&1 </dev/null &
echo "launched $NAME (rank-0 log $LOG)"
for i in $(seq 1 240); do
  if curl -fsS --max-time 2 http://127.0.0.1:8888/v1/models >/dev/null 2>&1; then
    echo "READY after $((i*3))s"
    exit 0
  fi
  if ! pgrep -f "tensorfold-native serve" >/dev/null 2>&1; then
    echo "ERROR: rank 0 exited early"; tail -n 30 $LOG; exit 1
  fi
  sleep 3
done
echo "TIMEOUT"; tail -n 30 $LOG; exit 1
