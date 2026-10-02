#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
DEST=/home/spark2/comfy-models
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }
log "START template-gap fetch -> $DEST"

log "=== MiniMax-H3 (int8 VAE + ref2v + controlnet) ==="
hf download Comfy-Org/MiniMax-H3 --local-dir "$DEST" \
  --include "vae/minimax_h3_video_vae_int8_convrot.safetensors" \
  --include "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors" \
  --include "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors" \
  --include "model_patches/minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors" && log "H3 extras OK" || log "H3 extras FAILED"

log "=== FastVideo FastH3 8-step (the fast lane) ==="
hf download FastVideo/FastVideo-FastH3-Comfy --local-dir "$DEST" \
  --include "diffusion_models/fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors" && log "FastH3 OK" || log "FastH3 FAILED"

log "=== Qwen-Image 2.1 prompt-enhancer encoders ==="
hf download Comfy-Org/Qwen-Image-2.1 --local-dir "$DEST" \
  --include "text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors" \
  --include "text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors" && log "Qwen PE OK" || log "Qwen PE FAILED"

log "=== Qwen3.8-27B (Ming t2i text encoder) ==="
hf download Comfy-Org/Qwen3.8-27B --local-dir "$DEST" \
  --include "text_encoders/qwen3.8_27b_w4a8.safetensors" && log "Qwen3.8-27B OK" || log "Qwen3.8-27B FAILED"

log "=== SDPose (H3 controlnet pose) ==="
hf download Comfy-Org/SDPose --local-dir "$DEST" \
  --include "checkpoints/sdpose_wholebody_fp16.safetensors" \
  --include "diffusion_models/rt_detr_v4-x-hgnet_fp16.safetensors" && log "SDPose OK" || log "SDPose FAILED"

log "DONE"; du -sh "$DEST"
