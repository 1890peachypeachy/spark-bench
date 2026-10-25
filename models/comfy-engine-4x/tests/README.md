# ComfyUI co-tenancy tests (4 nodes, with the TF4 lane serving)

Three scripts, run from the Mac. They answer "what can the four ComfyUI instances
actually do while the LLM lane is up", with measurements rather than assertions.

All three are read-only against the fleet: they submit prompts, poll `/history`,
and sample TP4 decode. They never restart a lane.

## `fourway_render_test.py` — same job on all four nodes

Submits the identical YuE2 song graph to all four instances at the same instant.

Measured 2026-10-25: all four reached `success` in 2:04 each, audio payloads
byte-identical (141.2 s). TP4 decode fell from 63 tok/s idle to ~21-23 tok/s
while all four rendered, recovering to 164 tok/s after. This is the throughput
case: four songs in the time one used to take, at roughly 3x cost to the lane.

## `mixed_render_test.py` — four DIFFERENT jobs at once

Sends a different model stack to each node, so a shared-resource collision has
somewhere to show up:

| node | job | model stack |
|---|---|---|
| spark1 | video | MiniMax H3 fl2va (20 GB DiT) + NVFP4 32B encoder + video/audio VAEs |
| spark2 | image | Qwen-Image-2.1 turbo |
| spark3 | song | YuE2 3B |
| spark4 | design | Ming-Image-0.1 design + 19 GB ling-mini encoder |

Measured 2026-10-25: all four succeeded. Wall clock — design 16.4 s, image
26.3 s, song 54.4 s, video 162.3 s. Outputs validated as real media (h264+aac
mp4, 1328x1328 and 1024x1024 PNG, 320 kbps MP3) and inspected visually. TP4
degraded only while the heavy jobs ran: 39 tok/s during the first sample, then
~68-76, back to 162 after.

**Caveat on that TP4 number:** the 64 tok/s "baseline" is depressed relative to
the 162 tok/s "after" figure, so this run cannot separate co-tenant load from
ordinary warm-up. The 39 tok/s dip is real; the size of the sustained penalty is
not pinned down by this script. Rerun with a settled baseline before quoting one.

## `ming_probe.py` — does Ming-Image do text-to-image?

Ming has no graph in the Studios recipe, only the vendor's edit workflow. Its
text encoder is auto-detected from the checkpoint weights, so the `clip_type`
passed to `CLIPLoader` is not what selects the encoder. `TextEncodeMingImageEdit`
allows zero reference images (`min=0`), which is what makes text-to-image work.

Run per node: `python3 ming_probe.py http://127.0.0.1:8188`

Measured on spark4 2026-10-25: 24.0 s cold, 3.0 s warm. If this fails with
"Value not in list", the Ming weights are missing from that node's
`diffusion_models`, `text_encoders` or `vae` — they are only staged on spark2
and spark4 by default.

## Staging requirement

`stage_node.sh` stages Qwen-Image and MiniMax H3. It does NOT stage Ming. A node
running the design job needs these three files copied from spark2:

    diffusion_models/ming_image_0.1_design_int8_convrot.safetensors   (5.8 GB)
    text_encoders/ming_image_0.1_ling_mini_2.0_int8_convrot.safetensors  (19 GB)
    vae/ming_image_vae_bf16.safetensors                              (243 MB)

Add them to `stage_node.sh` before treating spark1/spark3 as design-capable.
