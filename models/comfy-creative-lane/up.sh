#!/usr/bin/env bash
# Spark2 creation lane - ComfyUI v0.38.1 on GB10.
# HARD RULES: no restart policy; tailnet-bound only; memory-capped (blast radius).
set -euo pipefail
TS_IP="$(tailscale ip -4)"
docker rm -f spark-comfy 2>/dev/null || true
docker run -d --name spark-comfy \
  --gpus all \
  --memory 72g \
  --shm-size 8g \
  -p "${TS_IP}:8188:8188" \
  -v /home/spark2/comfy-models:/models/comfy:ro \
  -v /home/spark2/video-models/minimax-h3:/models/h3:ro \
  -v /home/spark2/music-models/yue2-comfyui:/models/yue2:ro \
  -v /home/spark2/comfy-build/extra_model_paths.yaml:/opt/ComfyUI/extra_model_paths.yaml:ro \
  -v /home/spark2/comfy-data/output:/opt/ComfyUI/output \
  -v /home/spark2/comfy-data/input:/opt/ComfyUI/input \
  -v /home/spark2/comfy-data/user:/opt/ComfyUI/user \
  spark-comfy:v0.38.1 \
    --listen 0.0.0.0 --port 8188 \
    --disable-pinned-memory
echo "spark-comfy up -> http://${TS_IP}:8188"
