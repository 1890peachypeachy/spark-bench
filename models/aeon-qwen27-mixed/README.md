# AEON-7 Qwen3.8-27B MIXED — spark2 TP1 brain lane (VERIFIED 2026-09-07)

Verified single-Spark (spark2, 10.73.0.2:8000) serving of the AEON MIXED body with the
#54367 modelopt patch + DFlash2 drafter. This is the brain lane for the multi-model fleet.

## Checkpoints (on spark2)
- Body: `/home/spark2/models/qwen38-27b-aeon-nvfp4-mixed` (23GB, 4/4 shards + hf_quant_config.json)
- Drafter: `/home/spark2/models/qwen38-27b-dflash2` (z-lab/Qwen3.8-27B-DFlash2, ~3.85GB)
- Patch: `/home/spark2/patches/modelopt-54367.py`
- Image: `ghcr.io/aeon-7/aeon-vllm-ultimate:latest` (vLLM 0.27.1+aeon.sm121a.dspark, tag 73d790a870bd)

## CRITICAL — the #54367 patch
The image does NOT fold in vLLM PR #54367. Without the bind-mount, boot dies at weight-load:
`AttributeError: 'MergedColumnParallelLinear' object has no attribute 'data'`
because FP8_PER_CHANNEL_PER_TOKEN layers (GDN writers + last-8 MLP FP8 in the MIXED lattice)
fall through get_quant_method to UnquantizedLinearMethod and never register weight_scale.

Patch = insert one dispatch branch into a copy of the container's own modelopt.py, then
bind-mount over the site-packages file:
```python
if quant_algo == "FP8_PER_CHANNEL_PER_TOKEN":
    return ModelOptFp8PcPtLinearMethod(self.fp8_config)
```
Extract the container's modelopt.py via `docker create` + `docker cp` (do NOT reconstruct
from memory), patch, `python3 -c "import ast; ast.parse(...)"` to validate, mount :ro.

## Launch (container aeon-mixed-spark, TP1)
MIXED-tree hard rules: NO --quantization (hf_quant_config auto-selects modelopt_mixed);
VLLM_USE_V2_MODEL_RUNNER=0; TRITON_ATTN; no prefix cache; DFlash2 n=7; quality seat 131k/8/0.70.

```bash
docker run -d --name aeon-mixed-spark --gpus all --ipc=host --shm-size=16g --net=host \
  -e VLLM_USE_V2_MODEL_RUNNER=0 -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -v /home/spark2/models/qwen38-27b-aeon-nvfp4-mixed:/model:ro \
  -v /home/spark2/models/qwen38-27b-dflash2:/draft:ro \
  -v /home/spark2/patches/modelopt-54367.py:/usr/local/lib/python3.12/site-packages/vllm/model_executor/layers/quantization/modelopt.py:ro \
  --entrypoint vllm ghcr.io/aeon-7/aeon-vllm-ultimate:latest \
  serve /model --served-model-name aeon --host 0.0.0.0 --port 8000 \
    --gpu-memory-utilization 0.70 --max-model-len 131072 --max-num-seqs 8 \
    --max-num-batched-tokens 8192 --kv-cache-dtype fp8 --enable-chunked-prefill \
    --no-enable-prefix-caching --tool-call-parser qwen3_coder --enable-auto-tool-choice \
    --reasoning-parser qwen3 --limit-mm-per-prompt '{"image":4,"video":2}' \
    --attention-backend TRITON_ATTN --trust-remote-code \
    --speculative-config '{"method":"dflash","model":"/draft","num_speculative_tokens":7}' \
    --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,"repetition_penalty":1.05}'
```

## Boot timeline (cold, ~7 min)
~2 min weight load (4 shards), ~85s inductor compile, fp4_gemm autotune (FlashInfer), cudagraph
capture. Engine init 236s. Ready when /v1/models lists `aeon`.

## Verified
- chat smoke: content "PONG", populated `reasoning` field, finish stop, GPU 94%.
- speculative_config method=dflash n=7 active; drafter loaded.

## Results
See results/aeon27-vs-38flash-20260907/ for the Phase A/B benchmark harness.
