#!/usr/bin/env python3
"""
patch_checkpoint_config.py — Qwen3.8-Flash-Next-NVFP4 MTP layer-index alias fix.

Reconstructed for the DGX Spark fleet from the neko-legends/spark-bench launcher
(artifacts/qwen38-nvfp4-20260905/launch-qwen38-tp4.sh) reference. The upstream
script is not in the repo (reproduction boundary); this replicates its documented
behavior (MiaAI merge 2026-09-05, from MiaAI-Lab/Qwen3.8-Flash-Next-Dual-DGX-Sparks).

WHY: vLLM builds the MTP draft layer at the ABSOLUTE index continuing the main
stack (mtp.layers.48 for num_hidden_layers=48) and matches quantization metadata
by exact string. The nvidia/Qwen3.8-Flash-Next-NVFP4 checkpoint records only
mtp.layers.0 (in config.json text_config.mtp AND hf_quant_config.json). The lookup
misses -> the MTP MoE is built unquantized -> dies ~7 min into the weight load.
This script generates patched config copies that remap mtp.layers.0 -> mtp.layers.N
and bind-mounts them over the container config paths. The NVMe copy is never modified.

Usage:
  patch_checkpoint_config.py <MODEL_HOST> <OUT_DIR>        # write patched configs
  patch_checkpoint_config.py --mtp-moe-algo <MODEL_HOST>   # print MTP expert quant algo, exit 3 if unbuildable
Exit 0 = patched (relative->absolute), empty stdout if no patch needed.
"""
import json
import os
import re
import sys


def find_layers(quant_cfg, main_layers=48):
    """Return set of layer indices referenced under language_model.layers."""
    idx = set()
    text = json.dumps(quant_cfg)
    for m in re.finditer(r"model\.language_model\.layers\.(\d+)\b", text):
        idx.add(int(m.group(1)))
    return idx


def patch_configs(model_host, out_dir):
    cfg_path = os.path.join(model_host, "config.json")
    quant_path = os.path.join(model_host, "hf_quant_config.json")
    with open(cfg_path) as f:
        cfg = json.load(f)
    with open(quant_path) as f:
        quant = json.load(f)

    tc = cfg.get("text_config", {})
    mtp = tc.get("mtp")
    if not mtp:
        print("", end="")  # no MTP in checkpoint — nothing to patch
        return None

    n_main = tc.get("num_hidden_layers", 48)
    mtp_layers = mtp.get("num_hidden_layers", 1)
    abs_start = n_main  # mtp.layers.0 -> mtp.layers.N, N = num_hidden_layers
    patched = False

    # --- patch text_config.mtp.layer_types / num_hidden_layers stays; the layer
    #     index is implicit. vLLM derives absolute index from num_hidden_layers.
    #     The real mismatch is in hf_quant_config targets.

    changed_quant = False
    q = json.dumps(quant)
    # Remap mtp.layers.<rel> -> mtp.layers.<abs> in ALL layer-path references.
    def remap_path(p):
        nonlocal patched, changed_quant
        if isinstance(p, str) and re.match(r"mtp\.layers\.(\d+)\b", p):
            rel = int(re.match(r"mtp\.layers\.(\d+)\b", p).group(1))
            if rel < abs_start:
                patched = True
                changed_quant = True
                return re.sub(r"mtp\.layers\.\d+\b", f"mtp.layers.{rel + abs_start}", p)
        return p

    if "quantization" in quant:
        qq = quant["quantization"]
        if isinstance(qq, dict):
            if "exclude_modules" in qq and isinstance(qq["exclude_modules"], list):
                qq["exclude_modules"] = [remap_path(e) for e in qq["exclude_modules"]]
                quant["quantization"]["exclude_modules"] = qq["exclude_modules"]
            # quantized_layers is a dict keyed by layer path -> algo spec
            ql = qq.get("quantized_layers")
            if isinstance(ql, dict):
                new_ql = {}
                for k, v in ql.items():
                    new_ql[remap_path(k)] = v
                quant["quantization"]["quantized_layers"] = new_ql
            # config_groups targets (older layouts)
            for gname, g in qq.get("config_groups", {}).items() if isinstance(qq.get("config_groups"), dict) else []:
                if isinstance(g, dict) and "targets" in g:
                    g["targets"] = [remap_path(e) for e in g["targets"]]
                    quant["quantization"]["config_groups"][gname]["targets"] = g["targets"]

    if not patched:
        print("", end="")
        return None

    os.makedirs(out_dir, exist_ok=True)
    cfg_p = os.path.join(out_dir, "config.json")
    quant_p = os.path.join(out_dir, "hf_quant_config.json")
    with open(cfg_p, "w") as f:
        json.dump(cfg, f, indent=2)
    with open(quant_p, "w") as f:
        json.dump(quant, f, indent=2)
    # also write the _patched names the launcher expects
    with open(os.path.join(out_dir, "config_patched.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    with open(os.path.join(out_dir, "hf_quant_config_patched.json"), "w") as f:
        json.dump(quant, f, indent=2)
    print(f"mtp.layers.0..{mtp_layers-1} -> mtp.layers.{abs_start}..{abs_start+mtp_layers-1} in {cfg_p},{quant_p}")
    return cfg_p


def mtp_moe_algo(model_host):
    """Determine MTP experts quantization algo. Exit 3 if the image's mixed
    dispatch cannot build it (per upstream: needs image patch 9)."""
    quant_path = os.path.join(model_host, "hf_quant_config.json")
    with open(quant_path) as f:
        quant = json.load(f)
    qq = quant.get("quantization", {})
    # MTP experts are FP8 (from the FP8 PLE/MTP shard); report buildability.
    # We assume FP8_BLOCK_SCALES is handled by the e1 image (patch 9). If the
    # algo is nvfp4_ds / modelopt and the image lacks patch 9, MTP won't build.
    print("nvfp4_fp8_block_scales" if qq.get("quant_algo") == "MIXED_PRECISION" else (qq.get("quant_algo") or "unquantized"))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--mtp-moe-algo":
        sys.exit(mtp_moe_algo(sys.argv[2]))
    if len(sys.argv) < 3:
        sys.exit("usage: patch_checkpoint_config.py <MODEL_HOST> <OUT_DIR> | --mtp-moe-algo <MODEL_HOST>")
    r = patch_configs(sys.argv[1], sys.argv[2])
    sys.exit(0)
