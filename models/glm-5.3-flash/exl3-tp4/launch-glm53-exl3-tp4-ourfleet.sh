#!/bin/bash
# GLM-5.3-Flash EXL3 TR3 4bpw + DFlash2 k=7 — TP4 on 4x DGX Spark (VICTOR FLEET)
# Adapted from MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks (TP2 recipe) + neko TP4 fork
# for THIS cluster: rail fabric 10.73.0.0/24, HCA rocep1s0f1, if enp1s0f1np1.
# Image glm53-exl3:e2 already ships NCCL 2.30.7 + all /opt/glm53 overlay patches.
set -uo pipefail

IMAGE=${IMAGE:-glm53-exl3:e2}
CONTAINER=glm53-exl3
# per-node user differs (spark1=spark, spark2/3/4=sparkN) — pass MODEL_BASE=/home/spark2 by rank
MODEL_HOST_BASE=${MODEL_HOST_BASE:-/home/spark2}
EXL3_REL=GLM-5.3-Flash-EXL3-TR3-4bpw
DFLASH_REL=GLM-5.3-Flash-DFlash2
VLLM_CACHE_HOST=/var/tmp/glm53-exl3-vllm-cache

PORT=8001
MASTER_PORT=25000
SERVED_MODEL_NAME=glm-5.3-flash
HEAD_IP=10.73.0.1
TP=4
NNODES=4
QUANTIZATION=exl3
MAX_MODEL_LEN=1000000
GPU_MEM_UTIL=0.82
MAX_NUM_SEQS=4
MAX_NUM_BATCHED_TOKENS=7168
KV_CACHE_DTYPE=fp8
SPEC_METHOD=dflash
DFLASH_TOKENS=${DFLASH_TOKENS:-7}
# TP4 recipe (start-tp4.sh L204): drafter sharded across TP=4. TP=1 (TP2 default)
# triggers a broken DP-inner-world MQ broadcaster crash on multinode. Match recipe.
DFLASH_DRAFT_TP=${DFLASH_DRAFT_TP:-4}
DFLASH_MODEL_DIR=/models/dflash2
MODEL_DIR=/models/exl3
ENFORCE_EAGER=0
EXL3_FUSED_MOE=1
ASYNC_SCHEDULING=${ASYNC_SCHEDULING:-0}
EXL3_FAT_KERNEL=1
EXL3_FAT_BATCHED=1
EXL3_FAT_SORTED=1
EXL3_MOE_ROW_TILE=0
EXL3_TEMP_ROWS_FUSED=128
LANGUAGE_MODEL_ONLY=0
SKIP_MM_PROFILING=1
LIMIT_MM='{"image":4,"video":1}'
CHAT_TEMPLATE=/opt/glm53/chat_template.jinja
ABLIT=0
READY_TIMEOUT=3600
GLM53_SUPPRESS_STOPS_IN_REASONING=1
GLM53_MIXED_PREFILL_CHUNK=${GLM53_MIXED_PREFILL_CHUNK:-skip}
GLM53_MIXED_PREFILL_SMALL_OK=${GLM53_MIXED_PREFILL_SMALL_OK:-0}
VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=1800
GLM53_INDEXER_WORKSPACE=stock
GLM53_SPINWAIT_MS=16
VLLM_PREFIX_CACHE_RETENTION_INTERVAL=0
LONG_PREFILL_TOKEN_THRESHOLD=1792
NEED_GB=95

# rank order: SSH_HOSTS[i] runs rank i (local = forge head rank 0).
# Workers reached over FABRIC IPs (RoCE), NOT Tailscale hostnames.
SSH_HOSTS=(local 10.73.0.2 10.73.0.3 10.73.0.4)
NODE_IPS=(10.73.0.1 10.73.0.2 10.73.0.3 10.73.0.4)
# per-node home base for model mounts (rank order) — includes /models/
HOME_BASES=(/home/spark/models /home/spark2/models /home/spark3/models /home/spark4/models)
# ssh user per fabric host (rank 1-3). Head is local.
SSH_USERS=(spark spark2 spark3 spark4)

say() { echo "[glm53-exl3-tp4] $*"; }

remote() {
  local h="$1"; shift
  if [ "$h" = local ]; then bash -c "$*"; else ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" "$*"; fi
}

# remote over fabric: resolve user@host for worker ranks
fabric_target() {
  local rank="$1"
  # rank 0 = local; ranks 1-3 -> SSH_USERS[rank]@SSH_HOSTS[rank]
  if [ "${SSH_HOSTS[$rank]}" = local ]; then echo local; else echo "${SSH_USERS[$rank]}@${SSH_HOSTS[$rank]}"; fi
}

# ---------------- preflight ----------------
for i in "${!SSH_HOSTS[@]}"; do
  h="$(fabric_target "$i")"
  base="${HOME_BASES[$i]}"
  say "preflight rank$i ($h, base=$base)"
  remote "$h" "
    docker rm -f $CONTAINER >/dev/null 2>&1 || true
    nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | while read -r p; do [ -n \"\$p\" ] && kill -9 \"\$p\" 2>/dev/null; done || true
    sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    avail=\$(grep MemAvailable /proc/meminfo | tr -dc 0-9)
    echo \"  avail mem: \$((avail/1024/1024))GB (need ${NEED_GB}GB)\"
    [ \"\$avail\" -ge $((NEED_GB*1024*1024)) ] || { echo \"  PREFLIGHT FAIL rank$i: mem\"; exit 1; }
    mkdir -p $VLLM_CACHE_HOST
    [ -f $base/$EXL3_REL/config.json ] || { echo \"  PREFLIGHT FAIL rank$i: weights missing at $base/$EXL3_REL\"; ls $base/models 2>/dev/null | head; exit 1; }
    [ -f $base/$DFLASH_REL/config.json ] || { echo \"  PREFLIGHT FAIL rank$i: drafter missing at $base/$DFLASH_REL\"; exit 1; }
    docker images ${IMAGE} >/dev/null 2>&1 || { echo \"  PREFLIGHT FAIL rank$i: image ${IMAGE} missing\"; exit 1; }
  " || { say "preflight FAILED on rank$i ($h)"; exit 1; }
done

# ---------------- inner serve script ----------------
INNER=$(cat << 'INNER_EOF'
#!/bin/bash
set -euo pipefail
say() { echo "[glm53-exl3-r${NODE_RANK}] $*"; }
ARGS=(
    --served-model-name "${SERVED_MODEL_NAME}"
    --host 0.0.0.0
    --port "${PORT}"
    --tensor-parallel-size "${TP}"
    --nnodes "${NNODES}"
    --node-rank "${NODE_RANK}"
    --master-addr "${HEAD_IP}"
    --master-port "${MASTER_PORT}"
    --distributed-executor-backend mp
    --tool-call-parser glm47
    --enable-auto-tool-choice
    --reasoning-parser glm45
    --enable-prefix-caching
    --no-enable-flashinfer-autotune
)
[ "${NODE_RANK}" != "0" ] && ARGS+=(--headless)
[ "${ASYNC_SCHEDULING:-0}" = "1" ] && ARGS+=(--async-scheduling)
[ "${ENFORCE_EAGER:-1}" = "1" ] && ARGS+=(--enforce-eager)
[ -n "${QUANTIZATION:-}" ] && [ "${QUANTIZATION}" != "none" ] && ARGS+=(--quantization "${QUANTIZATION}")
[ -n "${MAX_MODEL_LEN:-}" ] && ARGS+=(--max-model-len "${MAX_MODEL_LEN}")
[ -n "${GPU_MEM_UTIL:-}" ] && ARGS+=(--gpu-memory-utilization "${GPU_MEM_UTIL}")
[ -n "${MAX_NUM_SEQS:-}" ] && ARGS+=(--max-num-seqs "${MAX_NUM_SEQS}")
[ -n "${MAX_NUM_BATCHED_TOKENS:-}" ] && ARGS+=(--max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS}")
[ -n "${LONG_PREFILL_TOKEN_THRESHOLD:-}" ] && ARGS+=(--long-prefill-token-threshold "${LONG_PREFILL_TOKEN_THRESHOLD}")
[ -n "${KV_CACHE_DTYPE:-}" ] && ARGS+=(--kv-cache-dtype "${KV_CACHE_DTYPE}")
if [ "${SPEC_METHOD:-mtp}" = "dflash" ]; then
    ARGS+=(--speculative-config "$(python3 -S -c "import json,os
spec={\"method\":\"dflash\",\"model\":os.environ[\"DFLASH_MODEL_DIR\"],\"num_speculative_tokens\":int(os.environ.get(\"DFLASH_TOKENS\",\"7\")),\"kv_cache_dtype\":\"auto\",\"draft_sample_method\":\"probabilistic\",\"rejection_sample_method\":\"standard\"}
tp=os.environ.get(\"DFLASH_DRAFT_TP\",\"\").strip()
if tp:
    spec[\"draft_tensor_parallel_size\"]=int(tp)
print(json.dumps(spec,separators=(\",\",\":\")))")")
elif [ "${SPEC_METHOD:-}" = "none" ]; then
    :
fi
if [ -n "${CHAT_TEMPLATE:-}" ] && [ -f "${CHAT_TEMPLATE}" ]; then
    ARGS+=(--chat-template "${CHAT_TEMPLATE}")
fi
if [ "${LANGUAGE_MODEL_ONLY:-0}" = "1" ]; then
    ARGS+=(--language-model-only)
else
    [ -n "${LIMIT_MM:-}" ] && ARGS+=(--limit-mm-per-prompt "${LIMIT_MM}")
    [ "${SKIP_MM_PROFILING:-1}" = "1" ] && ARGS+=(--skip-mm-profiling)
fi
if [ -n "${EXTRA_ARGS:-}" ]; then
    EXTRA=(${EXTRA_ARGS}); ARGS+=("${EXTRA[@]}")
fi
[ -f "${MODEL_DIR}/config.json" ] || { say "FATAL: ${MODEL_DIR}/config.json missing"; ls -la "${MODEL_DIR}" | head; exit 1; }
# Apply EXACTLY the runtime patches the upstream recipe applies at boot
# (repo start.sh ~L987-1012). All others (build-time installers already baked
# into the image: ext_aarch64, fat_kernel, eagle3, model_overrides, dflash2)
# are SKIPPED — re-running them at boot is wrong and can fail (e.g.
# patch_exl3_ext_aarch64 writes to a non-existent /tmp/exllamav3 source tree).
for p in patch_glm_video_placeholders patch_suppress_stops_in_reasoning \
         patch_scheduler_decode_floor patch_glm5_drafter_group \
         patch_hybrid_prefix_hit patch_xgrammar_termination \
         patch_kpool_tail_slotmap patch_spinwait patch_indexer_workspace \
         patch_ablit; do
  f="/opt/glm53/$p.py"
  [ -f "$f" ] && { say "applying $p.py"; python3 "$f" || true; }
done
say "launching: vllm serve ${MODEL_DIR} ${ARGS[*]}"
exec vllm serve "${MODEL_DIR}" "${ARGS[@]}"
INNER_EOF
)

write_inner() {
  local h="$1"
  if [ "$h" = local ]; then
    printf "%s" "$INNER" > /tmp/glm53-exl3-start.sh
  else
    printf "%s" "$INNER" | ssh -o BatchMode=yes "$h" "cat > /tmp/glm53-exl3-start.sh"
  fi
}

launch_rank() {
  local rank="$1" h="$2" ip="$3" base
  if [ "$rank" = "0" ]; then
    base="/home/spark/models"   # head (spark1) model base — hardcoded deterministic
  else
    base="${HOME_BASES[$rank]}"
  fi
  write_inner "$h"
  local exl3_host="$base/$EXL3_REL"
  local dflash_host="$base/$DFLASH_REL"
  cat > /tmp/glm53-exl3-docker-r$rank.sh << DR_EOF
#!/bin/bash
set -e
docker rm -f $CONTAINER >/dev/null 2>&1 || true
docker run -d --name $CONTAINER \\
  --gpus all --network host --ipc=host --shm-size 32g --stop-timeout 60 \\
  --device /dev/infiniband --cap-add IPC_LOCK \\
  --ulimit memlock=-1 --ulimit stack=67108864 \\
  -v ${exl3_host}:/models/exl3:ro \\
  -v ${dflash_host}:/models/dflash2:ro \\
  -v $VLLM_CACHE_HOST:/root/.cache/vllm \\
  -v /tmp/glm53-exl3-start.sh:/start.sh:ro \\
  -v $VLLM_CACHE_HOST/triton:/root/.triton/cache \\
  -v $VLLM_CACHE_HOST/tilelang:/root/.tilelang/cache \\
  -e NODE_RANK=$rank \\
  -e SERVED_MODEL_NAME="$SERVED_MODEL_NAME" \\
  -e PORT=$PORT -e TP=$TP -e NNODES=$NNODES -e HEAD_IP=$HEAD_IP -e MASTER_PORT=$MASTER_PORT \\
  -e QUANTIZATION=$QUANTIZATION -e MAX_MODEL_LEN=$MAX_MODEL_LEN -e GPU_MEM_UTIL=$GPU_MEM_UTIL \\
  -e MAX_NUM_SEQS=$MAX_NUM_SEQS -e MAX_NUM_BATCHED_TOKENS=$MAX_NUM_BATCHED_TOKENS \\
  -e KV_CACHE_DTYPE=$KV_CACHE_DTYPE -e SPEC_METHOD=$SPEC_METHOD \\
  -e DFLASH_TOKENS=$DFLASH_TOKENS -e DFLASH_MODEL_DIR=$DFLASH_MODEL_DIR \\
  -e DFLASH_DRAFT_TP=$DFLASH_DRAFT_TP \\
  -e LANGUAGE_MODEL_ONLY=$LANGUAGE_MODEL_ONLY -e SKIP_MM_PROFILING=$SKIP_MM_PROFILING \\
  -e LIMIT_MM= \\
  -e CHAT_TEMPLATE=$CHAT_TEMPLATE -e ENFORCE_EAGER=$ENFORCE_EAGER \\
  -e EXL3_FUSED_MOE=$EXL3_FUSED_MOE -e EXL3_FAT_KERNEL=$EXL3_FAT_KERNEL \\
  -e EXL3_FAT_BATCHED=$EXL3_FAT_BATCHED -e EXL3_FAT_SORTED=$EXL3_FAT_SORTED \\
  -e EXL3_MOE_ROW_TILE=$EXL3_MOE_ROW_TILE -e EXL3_TEMP_ROWS_FUSED=$EXL3_TEMP_ROWS_FUSED \\
  -e MODEL_DIR=$MODEL_DIR \\
  -e ABLIT=$ABLIT -e EXTRA_ARGS="${EXTRA_ARGS:-}" \\
  -e VLLM_HOST_IP=$ip \\
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \\
  -e VLLM_CACHE_ROOT=/root/.cache/vllm \\
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \\
  -e VLLM_ENGINE_READY_TIMEOUT_S=$READY_TIMEOUT \\
  -e VLLM_NO_USAGE_STATS=1 -e DO_NOT_TRACK=1 \\
  -e GLM53_SUPPRESS_STOPS_IN_REASONING=$GLM53_SUPPRESS_STOPS_IN_REASONING \\
  -e GLM53_MIXED_PREFILL_CHUNK=$GLM53_MIXED_PREFILL_CHUNK \\
  -e GLM53_MIXED_PREFILL_SMALL_OK=$GLM53_MIXED_PREFILL_SMALL_OK \\
  -e ASYNC_SCHEDULING=$ASYNC_SCHEDULING \\
  -e GLM53_INDEXER_WORKSPACE=$GLM53_INDEXER_WORKSPACE \\
  -e GLM53_SPINWAIT_MS=$GLM53_SPINWAIT_MS \\
  -e VLLM_PREFIX_CACHE_RETENTION_INTERVAL=$VLLM_PREFIX_CACHE_RETENTION_INTERVAL \\
  -e VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=$VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS \\
  -e NCCL_NET=IB -e NCCL_IB_DISABLE=0 \\
  -e NCCL_IB_HCA=rocep1s0f1 -e NCCL_IB_GID_INDEX=3 \\
  -e NCCL_IB_ROCE_VERSION_NUM=2 -e NCCL_IB_ADDR_FAMILY=AF_INET \\
  -e NCCL_IB_ADDR_RANGE=10.73.0.0/24 \\
  -e NCCL_SOCKET_IFNAME=enp1s0f1np1 -e GLOO_SOCKET_IFNAME=enp1s0f1np1 \\
  -e TP_SOCKET_IFNAME=enp1s0f1np1 -e MN_IF_NAME=enp1s0f1np1 \\
  -e NCCL_NVLS_ENABLE=0 -e NCCL_CROSS_NIC=0 -e NCCL_IB_MERGE_NICS=0 \\
  -e NCCL_CUMEM_ENABLE=0 -e NCCL_IGNORE_CPU_AFFINITY=1 -e NCCL_DEBUG=WARN \\
  -e TORCH_NCCL_ASYNC_ERROR_HANDLING=1 \\
  ${NCCL_ALGO:+-e NCCL_ALGO=$NCCL_ALGO} ${NCCL_PROTO:+-e NCCL_PROTO=$NCCL_PROTO} \\
  --entrypoint bash $IMAGE /start.sh
DR_EOF
  if [ "$h" = local ]; then
    bash /tmp/glm53-exl3-docker-r$rank.sh >/dev/null
  else
    cat /tmp/glm53-exl3-docker-r$rank.sh | ssh -o BatchMode=yes "$h" "cat > /tmp/glm53-exl3-docker.sh && bash /tmp/glm53-exl3-docker.sh" >/dev/null
  fi
}

# ---------------- launch: workers (rank 3,2,1) then head (rank 0) ----------------
for rank in 3 2 1; do launch_rank "$rank" "$(fabric_target "$rank")" "${NODE_IPS[$rank]}"; sleep 8; done
launch_rank 0 local "${NODE_IPS[0]}"

say "launched; ready when: curl -s http://${HEAD_IP}:${PORT}/v1/models"
say "containers: glm53-exl3 on each node"
