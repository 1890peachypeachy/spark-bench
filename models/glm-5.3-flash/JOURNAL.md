# GLM 5.3 Flash on 4× DGX Spark — journal

Every dated entry for this model, newest first: what we changed, what it measured, what failed and why. Moved here unchanged from the top-level README on 2026-10-05 (old screenshots retired; the lane chart is on the [README](../../README.md)). Raw files stay where the entries link.

---

<a id="glm-5-3-flash"></a>

## GLM 5.3 Flash — 4× DGX Spark

GLM-5.3-Flash (320B total / 18B active MoE), TP=4. Served from 2026-08-28;
**stopped for the Qwen campaign on 2026-09-05**. Archived stack:
**vLLM + EXL3 TR3 4bpw + DFlash2 speculative**, 1M configured context.
The earlier SGLang NVFP4 lane is kept as a fallback and documented at the
bottom of this section.

### 2026-09-04 · Upstream chat-template update adopted (tool-result reorder fix)

zai-org updated the GLM-5.3 / GLM-5.3-Flash chat templates (tool-result
reordering exits early instead of scanning every block — a real win for long
tool-loop contexts). Adopted for the EXL3 TP4 serve with **one deliberate
local delta**: upstream dropped the `enable_thinking` switch (the new template
always opens `<think>`); our lanes and benches depend on
`chat_template_kwargs: {"enable_thinking": false}`, so we grafted the switch
back. Deployment template: `~/glm53-exl3-recipe/overlay/chat_template.jinja`
(upstream-verbatim kept alongside as `chat_template_upstream-2026-09-04.jinja`
for diffing). Rollback: `TEMPLATE_VARIANT=legacy` uses the image-baked one.

Other upstream deltas to know: every prompt now carries a
`<|system|>Reasoning Effort: Max` line (invalidates old prefix caches —
catch-up re-prefills naturally), and multimodal content gets a polite
"cannot process" reminder instead of image tokens (irrelevant on this
text-only lane).

Verified on the live cluster before adopting: thinking off → 3-token clean
answer, zero reasoning; thinking on → real reasoning; tool-call and
out-of-order tool-result renders correct (reordered to call order); xgrammar
structured output valid. Decode bench at parity: structured 92.8/96.9,
math 67.6/72.6 (up from 55.5/60.1), code 54.2/57.4, prose 43.7/43.9.

### 2026-09-03 PM · Serving hardening: the silent OOM crash, and the fixes

**If you only copy one thing from this entry: do not run this stack at
`--gpu-memory-utilization 0.85`. Use 0.80.** After the E2 fat-expert kernels
landed, 13.5 hours into an otherwise healthy serve the engine died with
`TimeoutError: RPC call to sample_tokens timed out` → `EngineDeadError`.
The real cause was upstream of the timeout: kernel logs on ranks 2/3 show
`NVRM: Out of memory [NV_ERR_NO_MEMORY]` storms starting **30 minutes before
the crash** (hundreds/minute), and ~1,100 more overnight while `/v1/models`
looked healthy. The E2 fat-expert scratch buffers, CUDA graph pools, and NCCL
buffers were never inside the 0.85 budget — the ranks had no headroom, and a
large concurrent prefill tipped them over. At 0.80 the post-boot OOM counters
sit at zero during serving (KV cache still 4.34M tokens — the trade is free).

Dated fixes that came out of this incident:

- **`GPU_MEM_UTIL` 0.85 → 0.80** (launcher default; env-overridable for
  experiments). Ranks 2 and 3 hold the layer-split tail plus the DFlash2
  drafter — they run hottest.
- **Rolling per-request logs.** vLLM native: `--enable-log-requests
  --max-log-len 200` (request id, prompt length, sampling params, first 200
  chars of prompt) plus docker `json-file` rotation 25 MB × 4 files per
  rank (~100 MB per rank — weeks of history, never a disk problem). `LOG_REQUESTS=0` disables.
- **Crash evidence preserved.** The launcher preflight used to `docker rm -f`
  dead containers on every rank before launching — which silently deletes the
  traceback you need. It now snapshots the last 4,000 lines of each dead
  container to `~/glm-crash-logs/<ts>-<host>-glm53-exl3.log` (keeps 20) first.
- **A watcher that watches the right signal.** `/v1/models` said "healthy"
  through 1,100 driver OOMs. The watcher (`glm-cluster-watch.service`, script
  in our ops repo) polls all four ranks' kernel logs every minute: ≥20
  `NV_ERR_NO_MEMORY` in 2 min on any rank = alert, ~30 min before the engine
  dies. Boot/warmup churn bursts are normal — there is a 10-min grace window
  after each boot; the kill signal is a *sustained* storm during serving.
  It also auto-relaunches once per hour if the API is down 3+ min with no
  boot in progress.

Lesson, generalized: **on a unified-memory box, "the API answers" is not
"the ranks have memory."** Watch `dmesg`/`journalctl -k` for NVRM allocation
failures on every rank, not just the head's HTTP 200.

### 2026-09-03 · Verified final config — "cycle C"

Fresh boot, JIT cache warm, staged probes passed (2k and ~110k prefill), then
the standard suite. This is the standing serving config.


| # | Config (single change per step) | Time (PDT) | 4-stream agg decode | 100k cold prefill | 300k cold prefill |
|---|---|---|---:|---:|---:|
| A | async-sched, DFlash k=5 | 09-02 18:18 | 107.9 tok/s | 80.6 s (1240 tok/s) | — |
| B | A + mixed-prefill `SMALL_OK=2048` | 09-02 18:45 | 115.7 (+7%) | 84.0 s (1190) | — |
| C | B + DFlash k=7 | 09-02 19:27 | 117.0 (+8%) | **64.0 s (1562)** (+26%) | 246.4 s (1217) |
| **C-verified** | C, fresh boot, JIT warm | **09-03 00:15** | **128.9 (+19.5%)** | 64.1 s (1560) | **230.9 s (1299)** (+7%) |

Single-stream decode on the verified boot (median of 3 × 400-token streams,
tok/s; thinking on / off): structured **88.6 / 95.8** · code 48.2 / 58.7 ·
math 55.5 / 60.1 · prose 42.2 / 44.7. Three runs is thin for single-stream
deltas — treat ±5 as noise.

Raw: [`results/verify-C-c4-2026-09-03.json`](../../results/verify-C-c4-2026-09-03.json) ·
[`results/verify-C-decode-2026-09-03.json`](../../results/verify-C-decode-2026-09-03.json) ·
[`results/verify-C-prefill-2026-09-03.json`](../../results/verify-C-prefill-2026-09-03.json) ·
cycle C originals [`results/ab-cycleC-*-2026-09-02.json`](../../results).

**Adopted config:**

```bash
ASYNC_SCHEDULING=1 DFLASH_TOKENS=7 GLM53_MIXED_PREFILL_SMALL_OK=2048
# no NCCL_ALGO / NCCL_PROTO overrides — autotune is the only stable choice on this fabric
```

**Dead ends, measured the same night (not charted):**

| Attempt | Result |
|---|---|
| `NCCL_ALGO=Tree NCCL_PROTO=LL128` | died at engine init |
| `NCCL_ALGO=Tree NCCL_PROTO=Simple` | `NCCL error: invalid usage` on the first cross-node allGather |
| `NCCL_ALGO=Ring NCCL_PROTO=LL128` | healthy in 720 s, unbenched (bench-driver bug). Only forced-NCCL variant that booted; tree is dead on this fabric |
| Cold-JIT boot, 22:24 | E2 fat-expert precompute locked **all four ranks in lockstep at layers=1806 (96.1%)** during a ~300k prefill; 30 min silence; the head's 1800 s execute-timeout fired, clean exit. Did not reproduce on the JIT-warm boot. **Always JIT-warm a fresh image boot before serving.** |

### What improved, in plain English

What the day of tuning actually bought, vs this morning's baseline:

- **Four people can use it at once, faster.** Four simultaneous streams now
  write a combined **129 tok/s** where the same test measured **108** this
  morning — like a checkout line that clears 19% quicker without adding lanes.
- **Reading long documents got ~2× faster.** A 100k-token prompt (≈ a 150-page
  book) is read in **64 seconds (1560 tok/s)** — the pre-E2 morning baseline
  measured 773 tok/s at 100k and 706 at 300k (see the [README](../../README.md#glm-5-3-flash) chart and the dated prefill
  timeline: pre-E2 → +E2 kernel → A → C → verified). A 300k-token read
  (≈ 450 pages) takes **~4 minutes**; before E2 it was 7 minutes.
- **Structured output (JSON, code-ish text) is the fast lane:** up to
  **~96 tok/s** on a single stream — the model drafts that kind of text almost
  perfectly, so speculative decoding keeps nearly every guess. Prose is the
  honest slow lane (~42–45) — the drafter guesses open text badly.
- **Follow-up turns are cheap now.** With thinking toggled, the prefix cache
  reuses **97%** of the read work, so a second question on the same document
  starts writing almost immediately instead of re-reading everything.
- **Nobody gets stuck behind a big read.** Two guards do this: long prefills
  are chopped into ~1.8k chunks so a short question that arrives mid-read gets
  its first word in seconds, and chat-sized messages are allowed to slip in
  while a peer is still reading — that single change was worth **+7%** on the
  4-stream number.
- **More guesses per step (k=7).** Letting the drafter try 7 tokens instead of
  5 added another **+8%** on the combined number, and the verified boot
  (JIT warm) added the rest of the gap to 129.
- **It stays up.** The night's crashes are documented above; the standing
  config has a clean boot + full bench + probe pass behind it.

One-line version: *the same four boxes now read long documents about twice as
fast as they did in the morning and serve a group about 20% faster, and the
config that does it is verified stable.*

### 2026-09-02 · E2 fat-expert prefill kernel — cold prefill ~2× at 300k

Ported MiaAI's **E2 fat-expert prefill kernel** (their PR77, 2026-09-01:
purpose-built `exl3_fat_gemm` + scatter CUDA kernels for routed "fat" experts)
into our TP4 image (`local/glm53-exl3:e2`) and benched cold prefill
before/after on the same live serve. Boot logs confirm the kernel is active:
`effective_tier=kernel`, 57 fat layers, 0 legacy fallbacks.

| prompt | before (TTFT / tok/s) | after (TTFT / tok/s) | gain |
|---|---:|---:|---:|
| ~16k | 17.1 s / 934 | 13.1 s / 1222 | +31% |
| ~100k | 129 s / 773 | 90 s / 1110 | +44% |
| ~300k | 425 s / 706 | **220 s / 1366** | **+94%** |

At long context this nearly doubles cold prefill and beats MiaAI's published
TP2 numbers (~1200 tok/s at 100–300k) — on 2× the nodes, with 1M ctx live.
The ~8k rung is JIT-warmup noise and is not compared. Harness:
[`scripts/run_cold_prefill_18888.py`](../../scripts/run_cold_prefill_18888.py).
Raw: [`results/cold-prefill-2026-09-02-post-e2.json`](../../results/cold-prefill-2026-09-02-post-e2.json).
*(Data-hygiene note: the `…-pre-e2.json` file in `results/` was overwritten by a
later run and now holds post-E2 numbers; the "before" column above is from the
2026-09-02 bench report, not a surviving raw file.)*


### 2026-08-29 · Reederey87 kit adoptions

Ported from the [Reederey87 production kit](https://github.com/Reederey87/glm53-flash-exl3-2x-dgx-spark)
(same pinned image digest; A/B-gated fixes) plus MiaAI upstream PR #21:

* **XGrammar termination backport** (vLLM #52805/#53046,
  `patch_xgrammar_termination.py`): fixes the `Failed to advance FSM` engine
  error that wedged structured traffic twice. Their gate: structured
  acceptance 0.98 → 1.0000, +4% structured, +9% prose tok/s.
* **`VLLM_PREFIX_CACHE_RETENTION_INTERVAL=0`**: sparse KDA retention —
  cross-session agent replays went 0% → 97.8% cache hit on their rig.
* **`LONG_PREFILL_TOKEN_THRESHOLD=1792`**: long cold prefills chunk-capped so
  a short request behind a 240k prefill gets first token in 7.9 s instead of
  256 s. Complements `GLM53_MIXED_PREFILL_CHUNK` (decode-vs-prefill guard).
* `python3 -S` for the speculative-config JSON: warm-restart stdout fix.
* Their k=8 was tested and reverted on a prose gate — independent validation
  of our k=7.

Verified on our TP4 1M rig: all patches applied at boot, KV pool byte-identical
(6,039,334 tokens), single-stream ~93 tok/s usage-counted, structured JSON
probe clean, 0 FSM errors.

### 2026-08-29 · Uncensored EXL3 — our own quant

We quantized [orcarouter/GLM-5.3-Flash-Uncensored-FP8](https://huggingface.co/orcarouter/GLM-5.3-Flash-Uncensored-FP8)
to EXL3 TR3 4bpw ourselves on the same 4-Spark kit and published it:
**[neko-legends/GLM-5.3-Flash-Uncensored-EXL3](https://huggingface.co/neko-legends/GLM-5.3-Flash-Uncensored-EXL3)**.

Recipe: brandonmusic's published R10 encoder closure drives the trellis
encode; `suh`/`svh`/`mcg` scale tensors are inherited per-tensor from the
Mia-AiLab base EXL3 checkpoint (the uncensored weights are a small
perturbation of base); non-routed tensors are FP8→BF16 dequantized. Identity
covariance this run; calibrated hessians are the v2 quality lever. Encode ran
split across all 4 Sparks: 37,152 expert tensors in 4 h 22 m. Verification:
150,226/150,226 tensors, zero mismatches, boots TP4 with KV pool 6.13M tokens
@ 1M ctx.

| | Uncensored EXL3 | Base EXL3 |
|---|---|---|
| C1 code / structured / math / prose | 86 / 113 / 69 / 37 tok/s | 83 / 113 / 71 / 33 tok/s |
| Single-stream ground truth (450 tok) | 4.64 s | 4.59 s |
| DFlash2 acceptance (k=7) | ~48% | ~84% |
| Wall-clock speed | parity | parity |

DFlash2 acceptance dips (drafter trained on base hidden states) but wall-clock
is unchanged. The abliteration survives quantization: on a dual-use refusal
probe, base refuses; the uncensored quant complies. Serving: one-line swap,
`/home/jun/launch-glm53-uncens-exl3-tp4.sh` (served name
`GLM-5.3-Flash-UNCENSORED-EXL3`).


### 2026-08-28 → 29 · EXL3 TP4 becomes primary; 1M context live

EXL3 4bpw measures **KLD 0.0246 vs the BF16 teacher — statistically equal to
official FP8** (NVFP4 is 0.0605), at the same ~176 GB footprint. It runs on
vLLM, so the SGLang >2^18 prefill wall does not apply: **1M context is live**
(KV pool 6.04M tokens) and a real 382,512-token cold prefill passed cleanly —
the exact workload class that node-wedged the SGLang stack twice.

Day-of runtime fixes from [MiaAI's recipe repo](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks)
(runtime-mounted patches, no rebuild):

- **Prefix caching actually works** (hybrid APC fix): hit rate 8.5% → **84%**.
  The single biggest interactive-speed win.
- **KV pool doubled** (padded slot-share): the DFlash2 drafter's KV pages
  co-own the MLA tensors. This is what made 1M allocate — 900k was the ceiling.
- **Decode floor during big prefills** (`GLM53_MIXED_PREFILL_CHUNK=skip`): a
  100k cold prefill used to drag a decoding peer from ~55 tok/s to ~5.
- **Thinking mode no longer self-terminates** (suppress-stops patch).
- **Triton/TileLang caches persist** across container recreates.

Note: vLLM reports ~977k as the observed max model length for the 1M config
(engine slack); the dash shows 977k observed / 1M desired — both real.

**Head-to-head, 2026-08-28 (warm, client wall, same rulers):**

| Config | code | structured | math | prose | C4 steady agg | ctx |
|---|---:|---:|---:|---:|---:|---:|
| SGLang NVFP4+DFlash2 (think on) | 53.5 | 88.3 | 82.7 | 34.1 | 90 | 262k |
| EXL3 TP4 (think on) | 38.6 | 91.3 | 75.2 | 30.3 | — | 900k |
| EXL3 TP4 (think off, Aug 28 config) | 64.5 | 100.9 | 77.8 | 23.1 | 253† (4×63.3) | 1M |

Math is within noise of SGLang; prose reflects DFlash2's accept rate on open
text (~0.33), not a stack defect. At 420k with thinking on the same day:
structured 93.7 / code 37.8 / math 74.5 / prose 36.2 — no regression vs the
900k boot.

† **C4 note (2026-09-03):** the Aug 28 serve measured 253 tok/s aggregate on
4× code streams; the current full-patch serve measures 128.9 with the same
harness. Single-stream C1 is at parity across both — the gap is specific to
4-way concurrent decode, it appeared with the 09-02 full-patch serve (flagged
in commit `f413842`), and the culprit among that day's changes (drafter-group,
spinwait, decode-floor, MNBT 7168, async-scheduling, E2) has not been
isolated. In exchange the current serve roughly **2×'d cold prefill** and
gained the scheduler/robustness fixes; treated as an accepted trade for now.
If 4-stream aggregate matters more one day, the isolation sweep is
one-toggle-per-boot against the same C4 ruler. At 420k with thinking on the same day:
structured 93.7 / code 37.8 / math 74.5 / prose 36.2 — no regression vs the
900k boot.


**Dashboard records.** The dash (eva:5555) tracks decode high-water marks
*per model*, so a model switch no longer buries the new model under the old
one's peaks. EXL3's first record landed 08-28 at **119 gen tok/s**; by 08-29,
after the xgrammar + sparse-retention fixes, **256.0** with prefix cache at
89.4% under live load. These are in-service aggregates (overlapping live
requests) and read differently from the client-wall C1/C4 rows above — both
true, different rulers.


### 2026-08-27 → 28 · SGLang NVFP4 + DFlash2 lane (fallback)

The first GLM lane on this cluster; superseded by EXL3 on 08-28 but kept as a
dash world (`glm53-sglang` in `config/tp4-world.json`). It still wins
single-stream prose and is the only stack with server-default `clear_thinking`
hygiene. Hard cap **262144 context** — see the stability boundary below.

**Final numbers (2026-08-28, RoCE fabric, warm, client wall):**

| Ruler | tok/s (2 runs) |
|---|---:|
| C1 code | **53.5 / 51.9** |
| C1 structured | **88.3 / 85.3** |
| C1 math | **72.1 / 82.7** |
| C1 prose | **33.0 / 34.1** |
| C4 aggregate | **90.0** |
| TTFT (short prompt) | 0.20–0.50 s |

How the levers stacked (same cluster, same night):

| Config | code | structured | C4 agg |
|---|---:|---:|---:|
| SGLang FP8 + DFlash2, Socket NCCL | 16.4 | 33.5 | 35.4 |
| vLLM NVFP4 + MTP, Socket NCCL | 18.7 | 24.7 | 29.8 |
| SGLang NVFP4 + DFlash2, Socket NCCL | 21.3 | 38.1 | 51.7 |
| **SGLang NVFP4 + DFlash2, RoCE** | **53.5** | **88.3** | **90.0** |

DFlash2 acceptance and NVFP4's halved weight-read bytes stack
multiplicatively; the RoCE fix was worth another ~2.5× on top. Cold-vs-warm is
real on spec-decode: acceptance was 2.6 at first boot and 7.95+ an hour in —
never bench a cold spec server. The 2.8× DFlash2 headline is vs plain
autoregressive; vs MTP the honest gain is 1.3–1.4×.


<details>
<summary><b>SGLang lane: config, provenance, thinking hygiene, the 262144 cap, gotchas</b></summary>

**Config**

- Image: `lmsysorg/sglang:glm-5.3-flash` + patch layer (0xSero sm121 stack +
  GLM DFlash capture PRs #36708/#36755) — built locally as
  `glm53-sglang-sm121:dflash`.
- Weights: NVFP4 (`modelopt_fp4`, 182 GiB total, ~45 GiB/rank), DFlash2
  drafter (2.2 GiB BF16) mounted on every node.
- Serve flags: `--tp-size 4 --nnodes 4 --quantization modelopt_fp4
  --moe-runner-backend flashinfer_cutlass --ep-size 4 --kv-cache-dtype
  fp8_e4m3 --dsa-prefill-backend flashinfer_sparse_mla
  --dsa-decode-backend flashinfer_sparse_mla --speculative-algorithm DFLASH
  --speculative-draft-model-path <dflash2> --speculative-num-draft-tokens 8
  --chunked-prefill-size 2048 --context-length 262144
  --max-running-requests 4 --mem-fraction-static 0.80
  --cuda-graph-max-bs-decode 8 --reasoning-parser glm45
  --tool-call-parser glm47`
- Boot ~7 min (NVFP4 loads 2× faster than FP8). Workers first, head last.
- Launch: `bash /home/jun/launch-glm53-nvfp4-dflash.sh` on forge (port 18888,
  served id `glm-5.3-flash`).

**Provenance**

- [joesinvestments/GLM-5.3-Flash-FP8-4x-DGX-Spark](https://github.com/joesinvestments/GLM-5.3-Flash-FP8-4x-DGX-Spark) — the 4× FP8 SGLang formula this builds on
- [0xSero/glm-5.3-flash-sglang-sm120](https://github.com/0xSero/glm-5.3-flash-sglang-sm120) — the six-patch sm12x stack (unlocks `flashinfer_sparse_mla` DSA on GB10)
- [tonyd2wild/GLM-5.3-Flash-NVFP4-2x-DGX-Spark](https://github.com/tonyd2wild/GLM-5.3-Flash-NVFP4-2x-DGX-Spark) — the parallel vLLM lane, KV sizing doctrine
- [incoai/GLM-5.3-Flash-DFlash2](https://huggingface.co/incoai/GLM-5.3-Flash-DFlash2) — the drafter (CC BY-NC-ND 4.0)

**Thinking hygiene: `clear_thinking=true` is the server default.** GLM-5.3
always thinks; `chat_template_kwargs.clear_thinking` controls whether prior
turns' `reasoning_content` is re-read or stripped. Measured (2-turn
conversation, ~1000 tokens of prior thinking):

| `clear_thinking` | prompt tokens for the next turn |
|---|---:|
| `false` | 1,029 |
| `true` | 28 |

The launcher sets `--default-chat-template-kwargs '{"clear_thinking": true}'`.
Coding agents that want reasoning carried across turns can pass
`clear_thinking: false` per request.

**Stability boundary: 262144 is a hard cap.** Upstream bug
[sglang #36550](https://github.com/sgl-project/sglang/issues/36550) — worker
abort at first decode token after cold prefill > 262144 tokens. On
unified-memory GB10 the blast radius is the **node**, not the process:
staged-prefill tests passed ~87k and ~174k, the node died at ~300k, a second
cold ~420k wedged it again; `journalctl -k` shows the driver itself OOM-ing
(`NVRM: … NV_ERR_NO_MEMORY … _memdescAllocInternal`). KV pool at this cap:
3,466,048 tokens. Decode at any depth, C4 load, and short prefills are stable
for hours; only >2^18-token cold prefills are radioactive.

**Gotchas**

1. **Uniform image on every rank, byte for byte.** A workers-vs-head base
   digest mismatch killed one rank (`DSATopKBackend.resolve` AttributeError).
   `docker save | ssh docker load` the exact stack everywhere.
2. **RoCE on this fabric = NCCL version + GID auto-detect.** Stock image NCCL
   2.29.7 fails `ibv_modify_qp` RTR on our CX-7. Fix: `LD_PRELOAD` the pip
   NCCL 2.30.7 plus `NCCL_IB_GID_INDEX=-1` — RoCEv2 GID indices differ per
   host (forge: 3, flame: 5). Full IB channels, 2.5× decode uplift over
   `NCCL_NET=Socket`.
3. **Bench with `stream_options: {"include_usage": true}`.** SGLang bundles
   ~accept-len tokens per SSE delta under spec-decode — counting chunks
   undercounts by ~8×.

</details>

### How to run GLM 5.3 Flash today (for humans and AI agents)

Current primary: **EXL3 TP4 + DFlash2 k=7 on vLLM**, image `local/glm53-exl3:e2`.

- **Launch:** `bash /home/jun/launch-glm53-exl3-tp4.sh` on forge. Preflights
  all four nodes (stops any other stack, gates at 95 GB avail RAM), stages
  NCCL 2.30.7, launches workers rank 3→2→1 then head rank 0. API on
  `forge:18888`, served id `GLM-5.3-Flash-EXL3`. Boot ~10–15 min. Runs
  MiaAI's boot-shape warmup after `/health` goes green (pass `--no-warmup` to
  skip). **On a fresh image boot, also let the fat-expert JIT warm before
  serving real traffic** (see the 2026-09-03 dead-ends table).
- **Standing env (cycle C):** `ASYNC_SCHEDULING=1 DFLASH_TOKENS=7
  GLM53_MIXED_PREFILL_SMALL_OK=2048`. Launcher defaults: `MAX_MODEL_LEN=1000000`,
  `GPU_MEM_UTIL=0.80` (was 0.85 — see the 2026-09-03 PM crash note below),
  `MAX_NUM_SEQS=4`, `MAX_NUM_BATCHED_TOKENS=7168`
  (never 8192 — indexer smem), `KV_CACHE_DTYPE=fp8`, `EXL3_FAT_KERNEL=1`,
  `GLM53_MIXED_PREFILL_CHUNK=skip`, `LONG_PREFILL_TOKEN_THRESHOLD=1792`,
  `VLLM_PREFIX_CACHE_RETENTION_INTERVAL=0`, `VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=1800`.
- **Weights:** `Mia-AiLab/GLM-5.3-Flash-EXL3-TR3-4bpw` (~164 GiB) at
  `/home/jun/models/glm-5.3-flash-exl3` on all four nodes. Drafter:
  `incoai/GLM-5.3-Flash-DFlash2` at `/home/jun/models/glm-5.3-flash-dflash2`
  (k=7, draft TP=1). Uncensored variant: swap to
  `/home/jun/launch-glm53-uncens-exl3-tp4.sh`.
- **Recipe provenance:** [MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks)
  (TP2 original; the overlay solves NoPE sparse-MLA on SM121 and adds the
  DFlash2 hooks). E2 recipe checkout at `/home/jun/glm53-exl3-e2` on forge;
  runtime patches bind-mounted from `/tmp/patch_*.py`.
- **Fabric landmines:** NCCL needs the pip 2.30.7 preload from
  `~/nccl-2.30.7` (image torch NCCL 2.29.7 breaks RoCE here) plus
  `NCCL_IB_GID_INDEX=-1` (GID index differs per node). Fabric is rail B — HCA
  `roceP2p1s0f1`, if `enP2p1s0f1np1`, `192.168.10.0/24`. **Do not force
  `NCCL_ALGO`/`NCCL_PROTO`** — tree variants die at init on this fabric.
- **Thinking** is a real switch: top-level
  `"chat_template_kwargs": {"enable_thinking": false}`. Prose decode is
  inherently slower (DFlash2 prose accept ≈ 0.33).
- **Bench:** `scripts/run_cold_prefill_18888.py` (prefill ladder); decode and
  C4 harnesses live in `/home/jun/glm-bench-results/` on forge
  (`bench_decode_full.py`, `bench_c4_steady.py`). This vLLM build streams
  reasoning as `delta.reasoning` (not `reasoning_content`) — token counters
  must sum all three delta keys.
