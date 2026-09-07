# Qwen3.8-Flash-Next NVFP4 TP4 — our-fleet deployment port (2026-09-06)

Port of the `neko-legends/spark-bench` Qwen3.8-Flash-Next NVFP4 TP4 lane to the
`1890peachypeachy` 4× DGX Spark fleet (CRS504 switched fabric). Supersedes the
GLM-5.3-Flash FP8 TP4 lane as the high-throughput option (Victor: "GLM FP8 too slow").

## Sources
- Upstream: `neko-legends/spark-bench` `0a64e52` — `artifacts/qwen38-nvfp4-20260905/launch-qwen38-tp4.sh`
- Campaign report: `results/qwen38-tuning-2026-09-06/REPORT.md` (MTP k4 + GEMV image = 91.3 tok/s C1, 600.5 C16)
- Checkpoint: `nvidia/Qwen3.8-Flash-Next-NVFP4` — 132.7 GB, 11 safetensor shards (10 main + 53.7GB `model-fp8-mtp-ple.safetensors`)
- Image: `ghcr.io/neko-legends/qwen38-flash-next-nvfp4-gb10:e1` (published base; the `-gemv-on` winner image is NOT public)

## Our-fleet deltas (in `launch-qwen38-tp4-ourfleet.sh`)
| Variable | Upstream | Ours |
|---|---|---|
| IMAGE | `local/qwen38-gb10:e1` | `ghcr.io/neko-legends/qwen38-flash-next-nvfp4-gb10:e1` |
| HEAD_IP / NODE_IPS | `192.168.10.1-4` | `10.73.0.1-4` |
| SSH_HOSTS | forge hostnames | `local spark2@10.73.0.2 spark3@10.73.0.3 spark4@10.73.0.4` (fabric, key auth from spark1) |
| IFACE / IB_HCA | `enP2p1s0f1np1` / `roceP2p1s0f1` | `enp1s0f1np1` / `rocep1s0f1` |
| NCCL_IB_ADDR_RANGE | `192.168.10.0/24` | `10.73.0.0/24` |
| MODEL_HOST | `/home/jun/models/qwen38-flash-next-nvfp4` | `$HOME/models/qwen38-flash-next-nvfp4` (per-node) |
| NCCL_SO | `libnccl.so.2.30.7` | `libnccl.so.2` (we staged the real lib, no .2.30.7 symlink) |
| CFG_STAGE_HOST | `/home/jun/qwen38-config-alias` | `/var/tmp/qwen38-config-alias` (common across different node users) |
| PORT / MASTER_PORT | 8000 / 25100 | 8000 / 25100 (GLM FP8 uses 8001 / 29521 — no collision) |
| CONTAINER | `qwen38-nvfp4` | `qwen38-nvfp4` |

## Reconstructed patch (NOT in upstream repo — reproduction boundary)
`patches/patch_checkpoint_config.py` — MTP layer-index alias fix. The nvidia
checkpoint records MTP at `mtp.layers.0` (in `config.json` text_config.mtp AND
`hf_quant_config.json` quantized_layers), but vLLM expects it at absolute index
`mtp.layers.48` (= num_hidden_layers 48). Without the remap the MTP MoE builds
unquantized and dies ~7 min into load. The script generates patched config copies
(bind-mounted over the container's config paths; NVMe copy never modified) and
streams them to every node. Verified against the real checkpoint:
`mtp.layers.0.mlp.experts` -> `mtp.layers.48.mlp.experts`.

## Staging status (2026-09-06)
- Checkpoint downloading to spark3 `~/models/qwen38-flash-next-nvfp4` (~133 GB)
- Image pulling to spark3 (9.7 GB) — to fan out to all 4
- NCCL 2.30.7 staged on all 4 nodes (243M each, `~/nccl-2.30.7/lib/libnccl.so.2`, verified `NCCL version 2.30.7`)
- spark4 NVFP4-RedHat removed (freed 185G) per Victor directive to make room

## Boot recipe (after staging complete)
```bash
# on spark1 (head), from this repo dir:
PLE_MODE=resident CUDAGRAPH_MODE=full MOE_BACKEND=stock GPU_MEM_UTIL=0.78 \
  IMAGE=ghcr.io/neko-legends/qwen38-flash-next-nvfp4-gb10:e1 MTP_TOKENS=2 \
  EXTRA_ARGS="--mamba-cache-mode all" \
  bash artifacts/qwen38-nvfp4-20260905/launch-qwen38-tp4-ourfleet.sh --wait
```
Known caveats: prose regression ~8% at k4 (start at k2 baseline), prefix-cache
align-mode gotcha (short shared prefixes get 0 hits — see upstream README),
explicit "stability testing in progress, not production-qualified". GLM FP8 stays
live as rollback until swap completes.
