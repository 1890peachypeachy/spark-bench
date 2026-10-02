# Spark2 Creation Lane — ComfyUI v0.38.1 on GB10

One ComfyUI instance serving **all four creative lanes** (music, image, design, video) on a
single DGX Spark (spark2), replacing the previous two-program setup
(`spark-image-lab` :7862 + `ming-design-lab` :8765).

Verified working 2026-10-01. GLM-5.3 TP4 rank r2 stayed `Up 2 days` throughout — zero disruption.

## Why one ComfyUI

ComfyUI core gained native support for every model in this lane within ~2 weeks:

| Model | ComfyUI version | Date |
|---|---|---|
| YuE2 (music) | v0.36.0 | 2026-09-15 |
| FastVideo FastH3 (distilled H3, native audio) | v0.36.0 | 2026-09-15 |
| Qwen-Image-2.1 | v0.37.0 | 2026-09-21 |
| **Ming Image 0.1 Design (+ Layer)** | **v0.38.0** | **2026-09-29** |

On unified memory this beats two containers holding hard caps (32g + 72g = 104 of 121 GB
pre-committed whether busy or not). Dynamic VRAM gives one pool with priority-based eviction.

## Build + run

```bash
docker build --build-arg COMFY_REF=v0.38.1 -t spark-comfy:v0.38.1 .
./fetch-comfy-models.sh      # ~86 GB, the four base model families
./fetch-template-gaps.sh     # ~88 GB more, what the official templates actually reference
./up.sh                      # binds to tailnet IP only
# then, to install the curated workflow folder + audit every model reference:
scp load_templates.py spark2:/home/spark2/comfy-data/user/load_templates.py
ssh spark2 'docker exec spark-comfy python3 /opt/ComfyUI/user/load_templates.py'
```

Total staged weights: **168 GB**.

## Lesson: a foreign recipe's weight list != the template's weight list

Tony's `MiniMax-H3-Local` list covers his **fl2v** lane only. The official ComfyUI templates
reference a materially broader set. Staging from the recipe alone left 14 of 15 templates
unrunnable. **Always audit template model references against the live server inventory
(`load_templates.py`) instead of trusting any upstream download list.**

Gaps the audit caught (88.4 GB), none of which Tony's recipe mentions:

| File | Size | Needed by |
|---|---|---|
| `minimax_h3_video_vae_int8_convrot` | 2.81 GB | **every** H3 template (recipe ships fp16, templates want int8) |
| `fastvideo_fasth3_8step_v2_pruned_int8_convrot` | 22.13 GB | both FastH3 turbo templates (the fast lane) |
| `minimax_h3_ref2va_pruned_int8_convrot` | 20.97 GB | r2v / multiframe / controlnet (distinct model from fl2va) |
| `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16` | 1.96 GB | same three |
| `minimax_h3_fun_controlnet_union_pruned_int8_convrot` | 2.30 GB | H3 Fun ControlNet Union |
| `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot` | 9.47 GB | Qwen-Image 2.1 t2i (prompt-enhancer encoder) |
| `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot` | 9.47 GB | Qwen-Image 2.1 image edit |
| `qwen3.8_27b_w4a8` (repo `Comfy-Org/Qwen3.8-27B`) | 17.29 GB | **Ming t2i** — uses Qwen3.8-27B, *not* ling_mini |
| `sdpose_wholebody_fp16` + `rt_detr_v4-x-hgnet_fp16` | 2.04 GB | H3 controlnet pose detection |

Note `extra_model_paths.yaml` must map `loras:` and `checkpoints:` on the `comfy_models` root
too, or the ref2v LoRA and SDPose checkpoint stay invisible.

## Curated workflow folder (15 local templates, all verified runnable)

`load_templates.py` copies them to `user/default/workflows/Creation Lane/` so they appear in the
UI's own Workflows sidebar, and audits every `.safetensors` reference against the live
`/object_info` inventory:

```
Creation Lane/1 - Music (YuE2)/            YuE2 - Text to Music | Music Cover
Creation Lane/2 - Image (Qwen-Image 2.1)/  Text to Image | Image Edit | Background Removal
Creation Lane/3 - Design (Ming)/           Ming Design - Text to Image | Image Edit
Creation Lane/4 - Video (MiniMax H3)/      FastH3 Turbo t2v/i2v | H3 t2v/i2v/r2v |
                                           I2V Continuation | Multiframe Reference |
                                           Fun ControlNet Union
```

**Audit gotcha:** ComfyUI now returns two COMBO shapes from `/object_info` —
classic `[[opt, ...], {...}]` and new `["COMBO", {"options": [...]}]`. Parsing only the first
yields false "missing model" reports (it wrongly flagged `sheetsage2_bf16`). `load_templates.py`
handles both.

Reachable at `http://<tailscale-ip>:8188` (spark2 = `100.71.248.116`).

## Hard rules baked in

1. **No `--restart` policy.** GB10 rule: never auto-restart an unverified config.
2. **`--disable-pinned-memory`.** ComfyUI page-locks up to 90% of system RAM; pinned pages
   can't swap so the kernel can only SIGKILL. Tony's measured 3090 fix: host RAM
   29,866 MB -> 7,508 MB from this flag alone.
3. **No container memory cap** (removed 2026-10-01 at Victor's direction -- he runs one model at
   a time). Earlier builds used `--memory 72g` as a blast-radius limit. Context: the two legacy
   labs still carry caps that Victor explicitly asked for on 2026-09-27 after a co-tenancy OOM
   wedged the node (`notes/spark2-lab-memory-caps-2026-09-27`, "do not remove the caps") -- those
   are a *different* decision about two programs sharing the GPU and still stand.
   The residual risk while spark2 also hosts a GLM/TP rank: an oversized job can starve the node
   and take down the whole multi-node lane, not just this container. Verified uncapped:
   `docker inspect` -> `Memory=0`, and `ram_total` now reports the full 121.7 GiB.
4. **Published to the tailnet IP only** (`-p ${TS_IP}:8188:8188`), never `0.0.0.0`.
5. **Weights mounted read-only** from their staging dirs via `extra_model_paths.yaml` — no
   duplicate copies of 86 GB.

## Verified facts (2026-10-01, spark2)

- `cuda:0 NVIDIA GB10 : native`, **vram_total 121.7 GiB** — the forum's
  "DGX Spark limited to 64GB in ComfyUI" does **NOT** reproduce on this build.
- torch `2.14.0a0+4fdf77b940.nv26.08` from the NGC base. Do not let pip replace it; the
  Dockerfile strips torch/vision/audio/numpy from `requirements.txt` and installs `--no-deps`.
- 974 node classes, 601 workflow templates.
- `[ERROR] [ComfyUI-Manager] PyTorch is not installed` at startup is **spurious** — NGC
  installs torch without pip metadata. Verify with `python3 -c "import torch"`, ignore the warning.
- `ram_total` reports the 72 GiB cgroup cap, but `vram_total` reports the full 121.7 GiB
  unified pool. The cgroup cap does **not** appear to bound GPU-side allocation — treat the cap
  as blast-radius only, not as an inference budget.

## Model inventory (86 GB, all Comfy-Org repacks, int8_convrot preferred)

```
diffusion_models/  ming_image_0.1_design_int8_convrot          6.18 GB
                   ming_image_0.1_design_layer_int8_convrot    6.18 GB   <- layer decomposition
                   qwen_image_2.1_int8_convrot                 7.26 GB
                   minimax_h3_fl2va_pruned_int8_convrot       20.97 GB
text_encoders/     ming_image_0.1_ling_mini_2.0_int8_convrot  19.51 GB
                   ming_..._layer_int8_convrot                19.51 GB
                   ming_..._w4a8                              12.81 GB   <- low-memory option
                   qwen3vl_8b_int8_convrot                     9.35 GB
                   qwen3vl_8b_w4a8                             6.31 GB
                   qwen3vl_32b_minimax_h3_nvfp4_awq           15.69 GB
vae/               ming_image_vae_bf16 / qwen_image_2.1_vae_bf16 /
                   minimax_h3_video_vae_fp16 / minimax_h3_audio_vae_fp32
checkpoints/       yue2_3b_int8_convrot                        3.96 GB
audio_encoders/    sheetsage2_bf16                             1.39 GB   <- enables covers
loras/             minimax_h3_fl2v_turbo_4step_768p / _8step    1.9 GB ea
embeddings/        10 H3 effect embeddings (bullet_time, fire_breath, truman_show, ...)
```

## Template naming rule — READ THIS

601 templates ship; **293 are `api_*` and bill a paid external service.**

- `image_*`, `video_*`, `audio_*` -> **local**, runs on our GPU
- `api_*` -> **paid partner API**, needs a key and credits

Local templates for this lane:

```
audio_yue2_text2music          audio_yue2_music_cover
image_ming_image_01_design_t2i image_ming_image_01_design_image_edit
image_qwen_image_2_1_t2i       image_qwen_image_2_1_image_edit
image_qwen_image_2_1_background_removal
video_minimax_h3_t2v           video_minimax_h3_i2v
video_minimax_h3_r2v           video_minimax_h3_i2v_continuation
video_minimax_h3_multiframe_reference
video_minimax_h3_fun_controlnet_union
video_fastvideo_fasth3_t2v     video_fastvideo_fasth3_i2v
```

`MinimaxHailuo03ContextIRNode` and `MinimaxHailuo03RegenerateNode` exist **only** as cloud
nodes — confirms H3's Context-IR and 2K-Regenerate passes were never open-released.

## Custom nodes

- `1038lab/Comfyui-Minimax-H3-Promptor` (GPL-3.0) -> `H3_Promptor`, `H3_PromptComposer`,
  `H3_PromptEditor`, `H3_Vision`. v1.5.1+ auto-unloads VRAM for local LLMs to avoid OOM during
  H3 generation. House style is editable in `vision_prompts.json` + `templates/*.txt`.
- `NidAll/comfyui-ming-image-prompt-builder` -> `MingImagePromptBuilder` (visual structured-prompt
  editor; replaces hand-written Figma-style JSON).
- `ComfyUI-Manager` (adds ~46 s prestartup).

## Open / unverified

- **Ming layer decomposition has weights + a loader but no sanctioned template.** The
  `image_ming_image_01_design_t2i` template plus the `_layer_` diffusion model via `UNETLoader`
  is the likely path. **Keep `ming-design-lab` (AntLing, :8765) alive until proven.**
- No render has been timed on GB10 yet. Tony's 3090 reference: 5 s @ 832x480 = ~4.5 min at
  20 steps; 15 s = ~23 min (2.9x frames -> 5.6x time, attention is quadratic). Turbo LoRAs
  should cut sampling (~95% of wall clock) substantially.
- GB10/UMA caveat: Dynamic VRAM assumes VRAM and RAM are distinct pools; here they are one.
  See `stardust7700/ComfyUI` (`--cuda-uma`, fixes LoRA weight-backup memory doubling) and the
  `spark-comfyui` self-healing project before tuning.

## Operational notes

- Drop page cache before big runs on unified memory: `sync; echo 3 > /proc/sys/vm/drop_caches`.
  Right after a large download, cached pages starve the CUDA allocator and OOM for no visible reason.
- `docker inspect` lies about OOM-kills (reports `ExitCode=0, OOMKilled=false` then silently
  restarts). Truth is only in `dmesg | grep oom-kill`.
- `nvidia-smi --query-gpu=memory.used` returns `[N/A]` on GB10 — unified memory. `free` is the
  only memory truth.
- Press `R` in the UI to refresh model dropdowns after adding weights; beats a restart.
- Any 4-Spark TP lane still parks this engine first. `spark-lane` needs a `comfy-engine` target.
- Frames must sit on the **17n+5** grid, trained range **124-362** (≈5 s to 15 s at ~24 fps).
  124 is the floor — shorter clips are outside training. Cut tighter in post.
