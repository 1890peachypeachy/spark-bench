#!/bin/bash
# Launch AEON-7 Qwen3.8-27B MIXED TP1 on a single DGX Spark (brain lane).
# VERIFIED 2026-09-07 on spark2. Requires: weights, DFlash2 drafter, #54367 patch staged.
# Edit MODEL/DRAFT/PATCH/IMG for your node.
set -euo pipefail
MODEL=/home/spark2/models/qwen38-27b-aeon-nvfp4-mixed
DRAFT=/home/spark2/models/qwen38-27b-dflash2
PATCH=/home/spark2/patches/modelopt-54367.py
IMG=ghcr.io/aeon-7/aeon-vllm-ultimate:latest
NAME=aeon-mixed-spark

# preflight
for d in "$MODEL" "$DRAFT"; do
  [ -d "$d" ] || { echo "MISSING $d"; exit 1; }
done
[ -f "$PATCH" ] || { echo "MISSING $PATCH (build per models/aeon-qwen27-mixed/README.md)"; exit 1; }

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --gpus all --ipc=host --shm-size=16g --net=host \
  -e VLLM_USE_V2_MODEL_RUNNER=0 -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -v "$MODEL":/model:ro -v "$DRAFT":/draft:ro \
  -v "$PATCH":/usr/local/lib/python3.12/site-packages/vllm/model_executor/layers/quantization/modelopt.py:ro \
  --entrypoint vllm "$IMG" serve /model \
    --served-model-name aeon --host 0.0.0.0 --port 8000 \
    --gpu-memory-utilization 0.70 --max-model-len 131072 --max-num-seqs 8 \
    --max-num-batched-tokens 8192 --kv-cache-dtype fp8 --enable-chunked-prefill \
    --no-enable-prefix-caching --tool-call-parser qwen3_coder --enable-auto-tool-choice \
    --reasoning-parser qwen3 --limit-mm-per-prompt '{"image":4,"video":2}' \
    --attention-backend TRITON_ATTN --trust-remote-code \
    --speculative-config '{"method":"dflash","model":"/draft","num_speculative_tokens":7}' \
    --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,"repetition_penalty":1.05}'
echo "[aeon] started $NAME: $(docker ps --filter name=$NAME --format '{{.Status}}')"
echo "[aeon] ready when: curl localhost:8000/v1/models lists 'aeon'"
