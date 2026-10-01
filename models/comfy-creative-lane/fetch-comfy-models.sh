#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
DEST=/home/spark2/comfy-models
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }

log "START comfy model fetch -> $DEST"

log "=== Ming-Image (design + LAYER, int8) ==="
hf download Comfy-Org/Ming-Image --local-dir "$DEST" \
  --include "diffusion_models/ming_image_0.1_design_int8_convrot.safetensors" \
  --include "diffusion_models/ming_image_0.1_design_layer_int8_convrot.safetensors" \
  --include "text_encoders/ming_image_0.1_ling_mini_2.0_int8_convrot.safetensors" \
  --include "text_encoders/ming_image_0.1_ling_mini_2.0_layer_int8_convrot.safetensors" \
  --include "text_encoders/ming_image_0.1_ling_mini_2.0_w4a8.safetensors" \
  --include "vae/ming_image_vae_bf16.safetensors" && log "Ming OK" || log "Ming FAILED"

log "=== Qwen-Image-2.1 (int8) ==="
hf download Comfy-Org/Qwen-Image-2.1 --local-dir "$DEST" \
  --include "diffusion_models/qwen_image_2.1_int8_convrot.safetensors" \
  --include "text_encoders/qwen3vl_8b_int8_convrot.safetensors" \
  --include "text_encoders/qwen3vl_8b_w4a8.safetensors" \
  --include "vae/qwen_image_2.1_vae_bf16.safetensors" \
  --include "model_patches/qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors" && log "Qwen OK" || log "Qwen FAILED"

log "DONE"; du -sh "$DEST"
