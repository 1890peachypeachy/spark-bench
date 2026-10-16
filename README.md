<h1 align="center">⚡ spark-bench</h1>

<p align="center">
  <b>Four DGX Sparks · one TP=4 world · every lesson, dated.</b><br>
  Recipes, configs and benchmarks for running frontier MoE models on <b>4× NVIDIA DGX Spark</b> (GB10).
</p>

<p align="center">
  <img alt="cluster: 4× DGX Spark" src="https://img.shields.io/badge/cluster-4%C3%97%20DGX%20Spark-76b900">
  <img alt="serving: DeepSeek V4.1 Flash on TensorFold" src="https://img.shields.io/badge/serving-DeepSeek%20V4.1%20Flash%20%C2%B7%20TensorFold-2a78d6">
  <img alt="updated 2026-10-16" src="https://img.shields.io/badge/updated-2026--10--16-8a8984">
</p>

<a id="now-serving"></a>

## 📌 Now serving: DeepSeek V4.1 Flash, not Nemotron (2026-10-16)

The Sparks are back on **DeepSeek V4.1 Flash** (TensorFold Zig engine, TP=4) as of 2026-10-16. We moved off
**Nemotron 3.5 Super VL** after two real-world agent tests, despite Nemotron's promising speed numbers. Its speed
and serving figures below stay published and are accurate. The decision came down to the quality of the result.

**The deciding test.** Each model ran as a coding agent on our four Sparks, with the same prompt (byte-identical),
the same reference image, the same tools, and the same 2 h cap. The task: look at the reference and build the same
voxel-style 3D garage as a live three.js scene in code — no 3D editor, no modelling tools. Each builder checked its
own work by screenshotting its page and reading the screenshots through the vision harness of its own model.

| | DeepSeek V4.1 Flash | Nemotron 3.5 Super VL |
| --- | ---: | ---: |
| Referee total (6 zoomed regions × 30) | **87 / 180** | 60 / 180 |
| Regions won | **6 of 6** | 0 of 6 |
| Wall time | **16 m 39 s** | 23 m 31 s |
| Tool calls (errors) | 87 (1) | 60 (5) |

A neutral third model refereed: it compared six zoomed regions of each build with the reference, judged every pair
in both orders (blinded), and kept the lower score on disagreement. A model-free pixel check agrees with the referee
(histogram overlap with the reference 0.77 vs 0.56; empty-background share 23% vs 50%). DeepSeek's build matches the
reference's palette, layout and props: brick walls, the tool pegboard, red drawers, the cabinet with its plant, warm
lamps, the striped parking pad, barrels and the crate. Nemotron got the room layout but its scene carries a long
black bar across the view — a bug in its own code, four window-pane calls missing an argument, which turned a colour
value into a depth of roughly ten million units. It also went 23 minutes with five malformed edits and checked its
own work half as often (25 harness runs vs 51).

| Reference image (the task) | DeepSeek V4.1 Flash | Nemotron 3.5 Super VL |
| :-: | :-: | :-: |
| <img alt="Reference: voxel-style garage with a white car on a striped pad, tool pegboard, red drawers, cabinet with plant, two lamps, window, roll-up door, barrels and a crate" src="docs/images/garage-test-reference-20261016.webp" width="340"> | <img alt="DeepSeek's voxel garage built in three.js: brick walls, pegboard with tools, red drawers, cabinet with plant, lamps, striped parking pad with a white car, barrels and crate" src="docs/images/voxel-test-deepseek-20261016.webp" width="340"> | <img alt="Nemotron's voxel garage built in three.js: correct room layout but a long black bar crossing the scene, pale walls, blocky car" src="docs/images/voxel-test-nemotron-20261016.webp" width="340"> |

**Second test: driving a 3D editor through tool calls.** Same reference, same kind of agent, but this time each model
built the garage by controlling Blender over MCP, writing editor code through tool calls and checking renders with its
vision harness. Same referee setup: six zoomed regions, blinded, both orders, lower score kept.

| | DeepSeek V4.1 Flash | Nemotron 3.5 Super VL |
| --- | ---: | ---: |
| Referee total (6 zoomed regions × 30) | **79 / 180** | 44 / 180 |
| Regions won | **5 of 6** | 1 of 6 |

| Both Blender builds side by side, labelled with model, time and tokens |
| :-: |
| <img alt="Labelled combined scene from the Blender test: both garages side by side, each labelled with the model that built it, its wall time and its token count" src="docs/images/garage-test-labelled-20261016.webp" width="720"> |

Both tests point the same way: DeepSeek V4.1 Flash turns a reference image into a faithful scene more reliably, whether
it writes the scene itself or drives an editor to build it.

---

## 🧭 Lanes

One cluster, one model at a time. Click a lane for its recipe.

| | Lane | Status | Best numbers |
| :-: | --- | --- | --- |
| 🐋 | **[DeepSeek V4.1 Flash · TensorFold (Zig engine)](#dsv41-tensorfold)** | 🟢 **live** again since 2026-10-16 (also 2026-10-11 → 2026-10-15) · [why](#now-serving) | 129 code tok/s (218 for 4) · 66 prose (138 for 4) · cold 154K prompt 30 s |
| 🟩 | [Nemotron 3.5 Super VL · TensorFold (Zig engine)](#nemotron-tensorfold) | 🟡 previous (live 2026-10-15 → 2026-10-16) · [why not now](#now-serving) | 185 code tok/s · 95 prose · 16 conversations × 307K tokens · 214–230 tok/s for 16 |
| 🐋 | [DeepSeek V4.1 Flash · SGLang](models/deepseek-v4.1-flash/README.md) | 🟡 rollback | 38 prose / 54–62 code tok/s · 1M context |
| 🐋 | [DeepSeek V4.1 Flash · vLLM](docs/dsv41-vllm-tp4.md) | 🟡 fallback | 71 code tok/s · 109 tok/s for 4 users |
| 🦄 | [Qwen 3.8 Flash Next](models/qwen-3.8-flash-next/README.md) | ⚪ archived | 91 code tok/s · 600 tok/s for 16 users |
| 🐉 | [GLM 5.3 Flash](models/glm-5.3-flash/README.md) | ⚪ archived | 129 tok/s for 4 users · 1M context |
| 🐳 | [DeepSeek V4 Flash](models/deepseek-v4-flash/README.md) | ⚪ archived | 136 tok/s, one user (record) · 182 for 4 |

<sub>tok/s = writing speed. Rulers differ between lanes; each lane page says how its numbers were measured.</sub>

## 🧠 Why this repo exists

This repo is about **four Sparks working as one machine**, and it keeps **every optimization we tried**: what we changed, what it measured, what failed and why, all dated.

That history is the point. When a new model comes out, the next engineer (or the next **AI agent**) should start from the best known config and the known traps, not find them again. Old lanes stay here on purpose: their lessons carry over to new models.

## 🤖 For AI agents

1. **Pick a lane** above. Its page is the recipe: image, flags, setup, rollback.
2. **Read the lane's journal** (`models/<model>/JOURNAL.md`) for every dated change, A/B result and dead end.
3. **Check the evidence.** Raw runs are in `artifacts/` and `results/`, linked from each entry.
4. **Wire the fabric first** ([docs/FABRIC.md](docs/FABRIC.md)), then follow the operator rules in [models/README.md](models/README.md).
5. **Write down what you learn**: a dated journal entry with its numbers, how they were measured, and its config. Never overwrite old evidence.

### Lessons that carry over

- 🔌 **Fix the network first.** One IPv4 address per NCCL port. A leftover address alone cost 30% ([V4](models/deepseek-v4-flash/JOURNAL.md)). Getting RoCE right was worth 2.5× ([GLM](models/glm-5.3-flash/JOURNAL.md)).
- 📏 **Measure decode from the stream:** count usage tokens from the first delta to the last. Wall time includes prompt reading, and chunk counts undercount speculative decoding.
- 🎲 **Boots vary.** Compare A/B/A with a same-night control. `vm.compaction_proactiveness=0` ended a 50/50 slow-boot lottery ([V4.1](models/deepseek-v4.1-flash/JOURNAL.md#dsv41-2026-09-13)).
- 🔥 **Warm up before you trust a number.** JIT kernels and draft acceptance start cold (acceptance went from 2.6 at first boot to 7.95 an hour later). Warm the kernels at boot.
- 🧮 **Unified memory is GPU memory.** Leave headroom (GLM crashed at 0.85 and is stable at 0.80) and drop the page cache before a start.
- 💾 **No bulk disk writes on a serving node.** Engram reads NVMe on every step, so one slow rank stalls all four.
- 🕵️ **Fallbacks are silent.** Check the boot log for the transport you expect (`over RoCE`, not NCCL) after every start. A leftover failure file cost TensorFold 12–19% for two days ([report](artifacts/tensorfold-v41-roce-20261007/REPORT.md)).
- ⏳ **Busy is not wedged.** Check the queue before restarting. A server is alive only if it answers a real 1-token completion.
- ✍️ **Speculative decoding depends on the text.** Code and math run about 2× faster than prose. Always quote task, prompt length and thinking mode.
- 🪶 **Fewer bytes per token, faster decode.** 2.9-bit EXL3 gave 1.7× over FP8 on the same four Sparks.
- 🧩 **Uneven splits hide bugs.** Test the request shapes that stress them, like `top_k` above one rank's vocabulary slice.

---

<a id="nemotron-tensorfold"></a>

## 🟩 Nemotron 3.5 Super VL · TensorFold (Zig engine) · 🟡 previous (live 2026-10-15 → 2026-10-16)

> 📌 **Not serving since 2026-10-16.** We went back to DeepSeek V4.1 Flash after a real-world agent test: building a
> 3D garage from one reference image, a blinded referee scored DeepSeek 79/180 and Nemotron 44/180
> ([details and images](#now-serving)). The numbers below are still accurate. The reason is result quality, not speed.

NVIDIA's [Nemotron 3.5 Super VL 120B-A12B](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4)
(NVFP4 as shipped: 40 Mamba-2, 40 latent-MoE and 8 attention blocks, 12B active, MTP draft head, vision encoder) on
TensorFold's Zig engine, our TP-4 port over RoCE. Same suites as the DeepSeek lane below, side by side.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-vs-deepseek-speed-dark.svg">
  <img alt="Writing speed, one stream: code 185 tok/s Nemotron vs 155 DeepSeek, prose 95 vs 72; four streams 207 vs 172 tok/s aggregate; first token 43 ms vs 167 ms" src="docs/images/nemotron-vs-deepseek-speed-light.svg">
</picture>

**Serving capacity (measured on the live server, 2026-10-15/16):**

- 🧵 **16 conversations at once**, each with a **307,200-token** window.
- 🚀 **214–230 tok/s** total with all 16 streams busy; first token with 16 arriving together **0.8 s median, 1.9 s worst**.
- ✍️ One stream: **185 tok/s** code, **95** prose, first token **43 ms** (MTP drafts sized by confidence: code 165 → 183, same text).
- 🧠 **40 GiB prompt cache in memory on every rank + a disk tier:** 200 agents returning to a 10K-token history wait
  **0.09 s** (200/200 hits); after a restart 8 × 30K-token conversations resume in **0.33 s** instead of 6.0 s.
- 🖼️ Images: **~70 a minute** for images the server has seen (1.3 s first token at 16 at once), **~23 a minute** for
  new ones (each new image is prepared one at a time, so 16 new images at once wait 25 s median). Accuracy is the
  same under load: 98.9 % of text strings with 16 tiled reads at once vs 98.6 % on one stream.

| Area | Result | DeepSeek V4.1 Flash, same suite |
| --- | ---: | ---: |
| Knowledge, MMLU-200 | **85.0 %** (170/200) | 88.5 % |
| Math, GSM8K 0–29 | **96.7 %** (29/30) | 100 % |
| Coding, 5 tasks | **80 %** (4/5) | 80 % |
| Instruction following | **95 %** (19/20) | 90 % |
| JSON schema · tools · long context to 299K · summary facts | **100 %** · **100 %** · **100 %** · **100 %** | 100 % · 100 % · 100 % · 100 % |
| Vision: text read exactly (166 strings) | **100 %** | 100 % |
| Vision: shapes (30) · objects counted (23) | **87 %** · **4 %** | 87 % · 96 % |
| Cold 200K-token prompt | **48.3 s** | 36.8 s |

Nemotron writes faster and holds 16 long conversations; DeepSeek is ahead on MMLU and math, reads a cold long prompt
faster and counts objects in images far better. The shapes figure is with the served `NCCL_MAX_NCHANNELS=2` (faster
long prompts): the shapes scene read 17/20 with it and 19/20 without.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-memory-dark.svg">
  <img alt="Memory per Spark, 122 GiB: idle 25.7 GiB weights + 11.0 other, 85.0 GiB free; prompt cache full 25.7 + 39.8 + 9.4, 46.7 GiB free; with 16 full-window sequences (21.9 GiB) 24.8 GiB free" src="docs/images/nemotron-memory-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-vision-serving-dark.svg">
  <img alt="Images under load: new images 18-24 a minute at 1-16 at once, first-token median 1.9 to 25.3 s; seen images 45-70 a minute, 0.1-1.3 s; one stream writes 140 tok/s on image prompts, 95 on prose, 185 on code" src="docs/images/nemotron-vision-serving-light.svg">
</picture>

<details>
<summary>More charts: quality, cold prompts, vision accuracy, serving under load, drafting</summary>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-vs-deepseek-quality-dark.svg">
  <img alt="Quality: MMLU 85.0% Nemotron vs 88.5% DeepSeek, math 96.7% vs 100%, coding 80% both, instruction following 95% vs 90%, JSON, tools, long context and summaries 100% both" src="docs/images/nemotron-vs-deepseek-quality-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-vs-deepseek-prefill-dark.svg">
  <img alt="Cold prompt reading: Nemotron 32K 6.5 s, 131K 29.0 s, 200K 48.3 s (from 11.4, 49.6 and 79.9 s before staggered segments); DeepSeek 200K 36.8 s" src="docs/images/nemotron-vs-deepseek-prefill-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-vs-deepseek-vision-dark.svg">
  <img alt="Vision: text read exactly 166/166 both; shapes 26/30 both; objects counted 22/23 DeepSeek vs 1/23 Nemotron; text position error 9.9 px Nemotron vs 16.3 px DeepSeek" src="docs/images/nemotron-vs-deepseek-vision-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-serving-dark.svg">
  <img alt="16 conversations at once: first-token wait 0.8-0.9 s median with 16 slots vs 5.0-9.4 s with 4 slots; coming back to a long conversation 0.09 s with the 40 GiB cache vs 2.1 s, and 0.33 s after a restart with the disk tier vs 6.0 s" src="docs/images/nemotron-serving-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/nemotron-drafting-dark.svg">
  <img alt="Drafts sized by confidence vs by running hit rate: code 165 to 183 tok/s with the same text, explain 117 to 127, prose 95 to 94, story 99 to 98, essay 112 to 111" src="docs/images/nemotron-drafting-light.svg">
</picture>

</details>

📦 [Recipe, engine and how to run: tensorfold-4x-sparks](https://github.com/neko-legends/tensorfold-4x-sparks#nemotron-35-super-vl-120b-a12b-nvfp4) · 🗂️ [Result files](results/nemotron-supervl-tensorfold-20261016/README.md) · 🖼️ [Vision under load](results/nemotron-supervl-tensorfold-20261016/vision-serving/README.md) · 🧾 [Port log](https://github.com/neko-legends/tensorfold-4x-sparks/blob/main/engine/zig-nemotron/NEMOTRON-PORT-LOG.md)

---

<a id="dsv41-tensorfold"></a>

## 🐋 DeepSeek V4.1 Flash · TensorFold (Zig engine) · 🟢 live again since 2026-10-16 (also 2026-10-11 → 2026-10-15)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/lane-dsv41-tensorfold-dark.svg">
  <img alt="DeepSeek V4.1 Flash on TensorFold's Zig engine, four Sparks, live since 2026-10-11 on RoCE: writing speed code 129 tok/s one stream and 218 for four vs 113 and 205 for the previous Python engine, cold against cold, prose 66 and 138 vs 65 and 128; cold 154K-token prompt 60.5 s with the pipeline off, 30.0 s with it on, 35.4 s for Python" src="docs/images/lane-dsv41-tensorfold-light.svg">
</picture>

<a id="dsv41-baseline"></a>

### 📊 Quality + speed baseline (2026-10-15)

One frozen suite (`bench/qbench.py`) against the TensorFold Zig engine while it was live (TP=4 over RoCE), thinking off, greedy decoding, 283 requests, 0 transport errors. Scores are plain percentages on fixed inputs.

| Area | What was asked | Result |
| --- | --- | ---: |
| Knowledge | MMLU-200, 0-shot, single A–D letter | **88.5 %** (177/200) |
| Math | GSM8K test items 0–29, exact final number | **100 %** (30/30) |
| Coding | 5 tasks, hidden stdlib-unittest tests | **80 %** (4/5) |
| Instruction following | 20 items, programmatic checkers | **90 %** (18/20) |
| Structured output | 6 JSON-Schema tasks, validated client-side | **100 %** (6/6) |
| Tool use | 8 single calls + 2 dependent chains | **100 %** (10/10) |
| Long context | passkey at 32K / 131K / 299K tokens | **100 %** (3/3) |
| Summarization | 20-fact log → summary: facts kept / stale returned / invented numbers | **100 %** / **0 %** / **0 %** |
| Vision: text | code-rendered images read in tiles, strings matched exactly | **98.5 %** (259/263; 7 of 8 text images at 100 %) |
| Vision: counts, shapes, colour | region counts · shape matching · measured hex | counts **100 %** exact (39/39, 23/23, 11/11) · shapes **100 %** (20/20) · flat-fill colour ΔE 0.0 |

| Speed (320-token outputs) | Decode tok/s | First token |
| --- | ---: | ---: |
| Code, 1 stream | **153.8** | 0.17 s |
| Prose, 1 stream | **70.2** | 0.15 s |
| 4 streams, aggregate | **170.2** | 0.17–0.50 s |

📈 [Chart](results/qbench-dsv41-only-20261015.png) · 🔁 To reproduce, see [RERUN.md](RERUN.md) and [results/](results/) (raw per-item records: [`qbench-dsv41-zig-20261015.json`](results/qbench-dsv41-zig-20261015.json)). The vision rows come from a separate image harness, not `qbench.py`.

---


- 🟢 **The serving engine is Zig** (live 2026-10-11 → 2026-10-15 and again since 2026-10-16, TP=4 over RoCE with pipelined prompt reading): code **129** tok/s for one stream, **218** for four; prose **66** / **138**. [Report](artifacts/tensorfold-v41-zig-20261011/REPORT.md).
- 🏭 **Pipelined prompt reading is the big lever:** +75 % at 32K and **+102 % at 131K** prompt tok/s against the same build with it off (one window, controlled); the cold 154K-token prompt's first token halves, 60.5 → **30.0 s**. Decode unchanged (±1 %).
- 🧪 **Long context, cold, measured 2026-10-14** — past the 131K the pipeline figure above tops out at: a **199,713-token** prompt returned its first token at **36.8 s** (~5,400 prompt tok/s), and a **332,847-token** prompt (79 % of the 420,096-token request slot) at **66.6 s** (~5,100 prompt tok/s). Both requests report `cached_tokens: 0`, so both reads are genuinely cold rather than prefix-cache hits. Thinking off for the clean timing run.

![Cold 200K-token prompt on the live four-Spark Zig engine: 199,713 tokens, first token 36.8 s](docs/images/dsv41-zig-context-200k-20261014.webp)

- ⚖️ **Against the previous Python engine** (cross-session, RoCE, cold against cold): code +14 % (×1) / +7 % (×4), prose +2 % (×1) / +8 % (×4), first token −15 %.
- 📜 The Python engine's numbers stay in the [lane page](models/deepseek-v4.1-flash/tensorfold-4x/README.md) and [journal](models/deepseek-v4.1-flash/JOURNAL.md) (G19 on RoCE, live 2026-10-07 → 2026-10-11: 420K context, image input, prose 66.5 / code 104.1 tok/s over 1k–160k, cold 160k prompt 36 s); the 1k–160k depth sweep and `m2bench` steady runs have no Zig equivalent yet, so those rows end with the Python engine.
- 🛠️ History: the bugs from Jay's review are fixed; a stale failure file once silently forced NCCL for two days (12–19 %). [Reports](artifacts/).

📦 [Recipe: tensorfold-4x-sparks](https://github.com/neko-legends/tensorfold-4x-sparks#deepseek-v41-flash) · 📘 [Setup & limits](models/deepseek-v4.1-flash/tensorfold-4x/README.md) · 📓 [Journal](models/deepseek-v4.1-flash/JOURNAL.md) · 🧾 Reports: [Zig benchmark](artifacts/tensorfold-v41-zig-20261011/REPORT.md), [decode](artifacts/tensorfold-v41-roce-20261007/REPORT.md), [prompt reading](artifacts/tensorfold-v41-prefill-20261005/REPORT.md), [fixes](artifacts/tensorfold-v41-fixes-20261005/REPORT.md)

<a id="dsv41-sglang"></a>

## 🐋 DeepSeek V4.1 Flash · SGLang · 🟡 rollback

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/lane-dsv41-sglang-dark.svg">
  <img alt="DeepSeek V4.1 Flash on SGLang TP4: EP2 vs EP4 across 1k-160k prompts; prose 37.7-38.3 vs 34.1-35.9 tok/s, code 53.8-62.2 vs 47.5-58.1" src="docs/images/lane-dsv41-sglang-light.svg">
</picture>

- 🧪 **Uncensored FP8** on [Mia's kit](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks), DSpark k=3, **1M context** (needle-checked).
- 🔀 **EP2 beat EP4**: prose +5–12%; code mixed, up to +19% at 80k–160k.
- 📦 **Engram pack published**, so you can skip the slow per-node pack step: [Hugging Face](https://huggingface.co/neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark).

📘 [Profile & rollback](models/deepseek-v4.1-flash/README.md) · 📓 [Journal: the fixes it took](models/deepseek-v4.1-flash/JOURNAL.md#dsv41-sglang-2026-09-14) · 🧾 [Depth sweep](artifacts/tensorfold-v41-depth-20261001/REPORT.md)

<a id="deepseek-v4-1-flash"></a>

## 🐋 DeepSeek V4.1 Flash · vLLM · 🟡 fallback

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/lane-dsv41-vllm-dark.svg">
  <img alt="DeepSeek V4.1 Flash vLLM TP4 champion, one user by task (tok/s): coding 71.4, format 71.2, math 70.0, reasoning 58.6, JSON 45.3, prose 31.7, summary 27.9, narrative 27.7; 4 users 109 total, 6 users 137" src="docs/images/lane-dsv41-vllm-light.svg">
</picture>

- 💾 **A 510 GB model on four Sparks:** each rank reads its quarter of the Engram tables from NVMe.
- 🎲 **The "gains" were the boot lottery:** A/B/A showed the champion settings matched the baseline.
- 🧯 **Tool calls came back clean here** where our first SGLang lane corrupted them. That is why this lane shipped.

📘 [Recipe & findings](docs/dsv41-vllm-tp4.md) · 📓 [Journal](models/deepseek-v4.1-flash/JOURNAL.md#deepseek-v4-1-flash) · 🧾 [Raw runs](artifacts/dsv41-vllm-20260910/)

<a id="qwen-3-8-flash"></a>

## 🦄 Qwen 3.8 Flash Next · ⚪ archived

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/lane-qwen38-dark.svg">
  <img alt="Qwen 3.8 Flash Next on four Sparks, MTP k=4 + GEMV vs k=2 baseline: one user code 91.3 vs 70.7, prose 49.2 vs 53.4 tok/s; total for 4/8/16 users 247.9/404.3/600.5 vs 198.6/344.4/526.8" src="docs/images/lane-qwen38-light.svg">
</picture>

- 🚀 **MTP k=4 + a GEMV kernel:** +29% code for one user, +14% total at 16 users. Prose −8%, the trade-off.
- 🤝 **Real agent tasks:** quality matched or beat the cloud on all five; up to 29× faster on four of them.
- 📦 Official NVIDIA NVFP4, TP4+EP, 262k context.

📘 [Recipe](models/qwen-3.8-flash-next/README.md) · 📓 [Journal](models/qwen-3.8-flash-next/JOURNAL.md) · 🧾 [Campaign report](results/qwen38-tuning-2026-09-06/REPORT.md)

<a id="glm-5-3-flash"></a>

## 🐉 GLM 5.3 Flash · ⚪ archived

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/lane-glm53-dark.svg">
  <img alt="GLM 5.3 Flash EXL3 TP4: cold 100k prompt read at 773 tok/s before the E2 kernel, 1110 with it, 1240 at step A, 1562 at C, 1560 verified; 4-user total writing 107.9 (A), 115.7 (B), 117.0 (C), 128.9 (C verified)" src="docs/images/lane-glm53-light.svg">
</picture>

- 📚 **Long prompts read 2× faster** with MiaAI's E2 fat-expert kernel (300k-token prompt in ~4 min).
- 🔓 **Our own uncensored EXL3 quant**, published: [Hugging Face](https://huggingface.co/neko-legends/GLM-5.3-Flash-Uncensored-EXL3).
- 🧯 **The 0.85 memory setting crashed it after 13 hours;** use 0.80.

📘 [Recipe](models/glm-5.3-flash/README.md) · 📓 [Journal](models/glm-5.3-flash/JOURNAL.md) · 🧾 [Verified runs](results/)

<a id="deepseek-v4-flash"></a>

## 🐳 DeepSeek V4 Flash · ⚪ archived

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/lane-dsv4-dark.svg">
  <img alt="DeepSeek V4 Flash vLLM TP4, one user: best case 136 median / 145.5 peak tok/s, 5-10k prompt code 79-93, 5-10k chat 72-89, ~50k deep session 66-74; 4 users 182 total" src="docs/images/lane-dsv4-light.svg">
</picture>

- 🏆 **The fastest single-user decode we have measured here:** 136 tok/s median, 145.5 peak.
- 🗺️ **Real chat speed is lower** (66–93 tok/s), depending on prompt length and how predictable the text is.
- 🔌 **This lane taught us the one-IPv4 rule:** removing a leftover address took decode from 103 to 136 tok/s.

📘 [Recipe](models/deepseek-v4-flash/README.md) · 📓 [Journal](models/deepseek-v4-flash/JOURNAL.md) · 🧾 [Raw runs](results/)

---

## 🧰 Also here

- 📏 **[RERUN.md](RERUN.md)**: one model-agnostic runner (`bench/qbench.py`, endpoint + model id as args), the frozen inputs behind it, what is already benched, and the exact command to point the whole suite at a new engine/model for a like-for-like chart. DeepSeek baseline per area: [results/BASELINE-dsv41-sparks-20261015.md](results/BASELINE-dsv41-sparks-20261015.md).
- 🔌 **[Fabric runbook](docs/FABRIC.md)**: CX-7, RoCE, the switch. Most "TP4 is slow" reports are network problems, not the model.
- 🔥 **[Catch-up sidecar](docs/CATCHUP.md)**: keeps a long chat warm in the local model's cache while you talk to another model.

<details>
<summary><b>📖 Glossary</b></summary>

| Term | Plain meaning |
|---|---|
| token | A chunk of a word (~¾ of one). The unit models read and write. |
| prefill ("reading") | The model reading your whole message before it can answer. |
| decode ("writing") | The model writing its answer. The speed you feel. |
| TP=4 | Four machines each hold ¼ of the model and confer on every token. |
| EP | Expert parallel: the MoE experts are spread across ranks. |
| KV / prefix cache | The model's short-term memory of your conversation. |
| speculative decoding (MTP / DFlash2 / DSpark) | Draft several tokens ahead, keep the good ones. Fast on code, slower on prose. |
| C1 / C4 | One stream / four at once. C4 is total throughput, not per-user speed. |
| RoCE / fabric | The 200G cables and switch between the Sparks. |

</details>

<details>
<summary><b>🗂️ Layout</b></summary>

```text
models/<model>/              recipe (README.md) + dated history (JOURNAL.md) per model
models/README.md             lane index + rules for operators and agents
artifacts/  results/         raw, dated evidence behind every number
docs/FABRIC.md               CX-7 / RoCE / switch runbook (read before benching)
docs/CATCHUP.md              catch-up sidecar · docs/PROTOCOL.md · docs/BRIDGES.md
docs/images/                 one chart per lane (light + dark SVG)
scripts/                     launchers, bench harnesses, recovery, charts/
catchup/                     the sidecar (stdlib only)
docker-compose.dspark-tp4.yml, patches/, vllm_patch_gb10/   DeepSeek V4 serving stack
```

</details>

<p align="center"><sub>A <b>Neko Legends</b> project 🐾 · formerly <code>dspark-kv-prefill-catchup</code></sub></p>
