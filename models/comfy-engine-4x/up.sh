#!/usr/bin/env bash
# comfy-studio co-tenant launcher (ComfyUI v0.38.1 image + existing model dirs; same file on all four Sparks).
# Source of truth for the flags: ~/recipe-db/DeepSeek-V4.1-Flash-x-MiniMax-H3-x-Qwen-Image-2.1-Studios-4x-DGX-Spark
#   scripts/run_comfy_studio.sh + docs/MEMORY.md. Differences from that recipe, both deliberate:
#   - image: ours is spark-comfy:v0.38.1 (recipe's is comfy-h3:gb10 with /opt/env); entrypoint is python3.
#   - model dirs: ours are mounted at /models/comfy, /models/h3, /models/yue2 (read-only, matching
#     extra_model_paths.yaml). The recipe's ~/h3 + ~/studio tree is not used -- the same files are already here.
# The four co-tenancy flags are the recipe's and are NOT optional:
#   --disable-pinned-memory  ComfyUI page-locks ~90% of system RAM by default; on GB10 that RAM is the rank's
#   --reserve-vram 48        plan as if 48 GB of the pool were absent (it is the TensorFold rank's)
#   --fp16-intermediates     smaller activations for the H3 decode
#   --oom-score-adj 800      the kernel picks ComfyUI, never the rank
#   --restart no             never come back on its own before the rank after a reboot
# usage: up.sh [--dry-run]
#   COMFY_MODELS_DIR, H3_MODELS_DIR, YUE2_MODELS_DIR, COMFY_DATA_DIR, EXTRA_PATHS_YAML override the defaults.
set -eu
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
TS_IP="$(tailscale ip -4 | head -1)"
IMG=${STUDIO_IMAGE:-spark-comfy:v0.38.1}
PORT=${STUDIO_PORT:-8188}
NAME=${STUDIO_NAME:-comfy-studio}
MODELS=${COMFY_MODELS_DIR:-$HOME/comfy-models}
H3=${H3_MODELS_DIR:-$HOME/video-models/minimax-h3}
YUE2=${YUE2_MODELS_DIR:-$HOME/music-models/yue2-comfyui}
DATA=${COMFY_DATA_DIR:-$HOME/comfy-data}
EXTRA=${EXTRA_PATHS_YAML:-$HOME/comfy-build/extra_model_paths.yaml}

# floor check: refuse to start if the node has no room for a picture (26 GB cold) + the 4 GB guard
AVAIL_GB=$(awk '/MemAvailable/{printf "%.1f", $2/1048576}' /proc/meminfo)
if [ "$DRY" = 0 ]; then
  awk -v a="$AVAIL_GB" 'BEGIN{ if (a < 30) { printf "REFUSING: MemAvailable %.1f GB < 30 GB (26 GB picture + 4 GB guard)\n", a; exit 1 } }' || exit 1
fi

mkdir -p "$MODELS" "$H3" "$YUE2" "$DATA"/{output,input,user}
CMD=(docker run -d --name "$NAME" --network host --gpus all --oom-score-adj 800 --restart no
  --shm-size 8g
  -v "$MODELS:/models/comfy:ro" -v "$H3:/models/h3:ro" -v "$YUE2:/models/yue2:ro"
  -v "$EXTRA:/opt/ComfyUI/extra_model_paths.yaml:ro"
  -v "$DATA/output:/opt/ComfyUI/output" -v "$DATA/input:/opt/ComfyUI/input" -v "$DATA/user:/opt/ComfyUI/user"
  -p "${TS_IP}:${PORT}:${PORT}"
  --entrypoint python3 "$IMG"
  /opt/ComfyUI/main.py --listen 0.0.0.0 --port "$PORT"
  --disable-pinned-memory --reserve-vram 48 --fp16-intermediates)

echo "$(hostname): MemAvailable=${AVAIL_GB} GB image=$IMG bind=${TS_IP}:${PORT}"
if [ "$DRY" = 1 ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "container $NAME already exists: docker rm -f $NAME first (or 'docker start $NAME')" >&2; exit 1
fi
"${CMD[@]}"
for i in $(seq 1 180); do
  if curl -s -m 3 -o /dev/null "http://127.0.0.1:$PORT/system_stats"; then echo "comfy-studio up on :$PORT after ${i}s"; exit 0; fi
  sleep 1
done
echo "comfy-studio did not answer on :$PORT; see docker logs $NAME" >&2; exit 1
