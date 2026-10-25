#!/bin/bash
# Stage the studio files on spark1, spark4 (and anywhere else with no studio tree) from spark2 over the CX7 fabric.
# Per node: (1) the recipe's model set, (2) the ComfyUI image, (3) launcher + guard + extra_model_paths.
# NOTE: remote paths are literal (/home/spark2/...), never $HOME -- $HOME expands on THIS node, which made the
# first run look for /home/spark4/comfy-models on the sender side and die with a broken pipe.
set -u
HEAD=spark2@10.73.0.2
HEADDIR=/home/spark2
T=/var/tmp/comfy
IMG=spark-comfy:v0.38.1
exec >> "$HOME/comfy-stage.log" 2>&1
echo "=== stage $(hostname) $(date -u +%FT%TZ) ==="
mkdir -p $T/models/{diffusion_models,text_encoders,vae,loras} $T/h3/{diffusion_models,text_encoders,vae,loras} \
         $T/yue2/checkpoints $T/data/{output,input,user} $T/studio

fetch() {  # fetch <remote-abs-path> <local-dest>
  [ -s "$2" ] && { echo "have $2"; return 0; }
  rsync -a --info=progress2 "$HEAD:$1" "$2.part" && mv "$2.part" "$2" || { echo "FAIL $1"; return 1; }
}

# 1. the picture + video files the recipe's graphs name (67 GB total)
for f in diffusion_models/qwen_image_2.1_int8_convrot.safetensors \
         diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors \
         text_encoders/qwen3vl_8b_int8_convrot.safetensors \
         vae/qwen_image_2.1_vae_bf16.safetensors; do
  fetch "$HEADDIR/comfy-models/$f" "$T/models/$f" || exit 1
done
for f in diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
         text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
         vae/minimax_h3_video_vae_fp16.safetensors \
         vae/minimax_h3_audio_vae_fp32.safetensors; do
  fetch "$HEADDIR/video-models/minimax-h3/$f" "$T/h3/$f" || exit 1
done

# 1b. YuE2 music (5.3 GB). The container mounts /models/yue2 on every node, but the mount is
# EMPTY unless these two files are staged -- the folder alone makes CheckpointLoaderSimple show
# no yue2 checkpoint, and a song graph then fails at load instead of rendering.
for f in checkpoints/yue2_3b_int8_convrot.safetensors \
         audio_encoders/sheetsage2_bf16.safetensors; do
  fetch "$HEADDIR/music-models/yue2-comfyui/$f" "$T/yue2/$f" || exit 1
done

# 2. the image over the fabric (~27 GB)
if ! docker image inspect $IMG >/dev/null 2>&1; then
  ssh -o BatchMode=yes $HEAD "docker save $IMG" | docker load || { echo "FAIL image"; exit 1; }
fi

# 3. launcher + guard + extra_model_paths
cp $HOME/studio-tools/up.sh $HOME/studio-tools/h3_guard.sh $HOME/studio-tools/start_guard.sh $T/studio/
chmod +x $T/studio/*.sh
# extra_model_paths must come from the head node: a bare `cp /tmp/...` silently did nothing on
# nodes that never had the file, leaving ComfyUI without the yue2/h3 search paths.
if [ -s /tmp/extra_model_paths.yaml ]; then
  cp /tmp/extra_model_paths.yaml $T/
else
  scp -q -o BatchMode=yes $HEAD:$HEADDIR/comfy-build/extra_model_paths.yaml $T/ || echo "FAIL extra_model_paths"
fi
echo "=== staged $(hostname) $(date -u +%FT%TZ) ==="
du -sh $T/models $T/h3
