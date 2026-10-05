# DeepSeek V4.1 Flash on 4× DGX Spark — journal

Every dated entry for this model, newest first: what we changed, what it measured, what failed and why. Moved here unchanged from the top-level README on 2026-10-05 (old screenshots retired; the lane chart is on the [README](../../README.md)). Raw files stay where the entries link.

---

**2026-10-05 (11:30) — four-Spark recipe forked off; the bugs Jay's review found are fixed and live.** Our four-Spark support now lives in **[neko-legends/deepseek-v41-tensorfold-spark](https://github.com/neko-legends/deepseek-v41-tensorfold-spark)** (Jay's repository plus three engine patches). Patch `0005` fixes the uneven-slice bugs from his review; the worst bit our own server: a sampled request with more candidates than the narrow vocabulary slices hold (`top_k` above 32,256, or a JSON request with nucleus sampling) crashed ranks 2 and 3. Now the same replies byte for byte, the same speed, and every wide request answers. [Report](../../artifacts/tensorfold-v41-fixes-20261005/REPORT.md) · [what changed](tensorfold-4x/README.md#fixed-2026-10-05-the-bugs-jays-review-found).

**2026-10-05 — prompt reading 2.5× faster: the four Sparks read long prompts as an assembly line.** Each Spark now also holds a quarter of the model's prompt-reading layers at full width (~27 GB more memory a node) and a prompt's 2,048-token chunks flow Spark 1 → 4, instead of every Spark computing a quarter of every layer. Decode speed is unchanged; the reading arithmetic rounds like one Spark instead of four (as different as the engine's own fast vs exact kernels), and the replies pass the same checks. Cold time to first token, each build with an empty cache:

| Prompt | 2026-10-04 (as published) | 2026-10-05 split + overlap | **2026-10-05 pipelined** | SGLang TP4/EP2 |
| --- | ---: | ---: | ---: | ---: |
| 20k | 12.9–14.2 s | 9.4–9.5 s | **5.8–6.8 s** | 5.3–5.5 s |
| 160k | 97.4–99.8 s | 74.6–75.2 s | **38.8–39.6 s** | 48.1–52.1 s |

Checks on the pipelined server: a code word hidden at 30 / 60 / 85% of 20k / 80k / 158k-token prompts found 3/3; the short gates 7/7. Method, the two smaller changes and what did not work: [report](../../artifacts/tensorfold-v41-prefill-20261005/REPORT.md) · [setup](tensorfold-4x/README.md#faster-prompt-reading-2026-10-05).


**2026-10-04 — TensorFold on four Sparks replaces SGLang.** Same four nodes, same prompts and clients, isolated runs: prose decode **63.4 vs 37.8 tok/s** (1.68×), code **100.2 vs 57.4** (1.75×) as geometric means over 1k–160k prompts; four users at once **119.2 vs 75.7 tok/s**; every gate passes, including the forced tool call SGLang failed. The weak spot is reading a long new prompt: **99.8 s vs 52.1 s at 160k** (the exchanges between the four Sparks are not yet overlapped with compute). The weights differ: 2.9-bit EXL3 against SGLang's FP8/FP4, and fewer bytes per token is most of the gain. One boot; expert pruning on (lossy, ~5%). [Full report and raw files](../../artifacts/tensorfold-v41-4x-20261004/REPORT.md).


> **Four-Spark recipe: [neko-legends/deepseek-v41-tensorfold-spark](https://github.com/neko-legends/deepseek-v41-tensorfold-spark)** (2026-10-05). Jay reviewed our [pull request](https://github.com/jayleaton/deepseek-v41-tensorfold-spark/pull/6): his engine has moved on (G14–G19, built around two ranks) and he preferred four-Spark support outside his default image, so it lives in our fork, his repository plus three engine patches (four Sparks, pipelined prompt reading, and fixes for the uneven-slice bugs his review found). Two Sparks: use [his repository](https://github.com/jayleaton/deepseek-v41-tensorfold-spark).

---

*Previous profile, served 2026-10-02 → 2026-10-04 and kept as the rollback:* the abliterated FP8 checkpoint on SGLang **TP4 / EP2**, with bounded rank-sliced loading

**2026-10-02 — TP4/EP2 selected after a 1k–160k depth sweep and an EP4 reboot control.** Same checkpoint, image, precision, DSPARK k=3 and SSD-backed Engram. Prose generation improved **5–12%**; code was mixed (**−2% at 20k**, near parity at 40k, **+15–19% at 80k–160k**). Cold time to first token was largely unchanged (~49s at 160k). Median of three 512-token completions per cell; 72 measured requests including the restored-control checks. This is a **SGLang configuration improvement, not TensorFold inference**. [Full results and raw trials](../../artifacts/tensorfold-v41-depth-20261001/REPORT.md) · [Current settings and rollback](README.md).

| Prompt depth | Prose tok/s: EP4 → EP2 | Code tok/s: EP4 → EP2 |
| ---: | ---: | ---: |
| 1k | 35.9 → **37.7** | 55.7 → **62.2** |
| 20k | 35.5 → **38.0** | **58.1** → 56.9 |
| 40k | 34.5 → **38.1** | 52.9 → **53.8** |
| 80k | 34.6 → **37.1** | 50.3 → **59.9** |
| 160k | 34.1 → **38.3** | 47.5 → **54.6** |

EP2 needs the loader changes documented in the guide: full-expert staging nearly exhausted unified memory before rank-sliced reads were enabled. Final boot: **7/7 smoke gates**, external completion verified, 7,179,008 effective cache tokens. The 1M window remains configured; this EP2 campaign tested through 160k, not a new 1M needle run. Forced `tool_choice=required` returned unparsed DSML on both EP4 and EP2; automatic tool calls and continuations passed. This is not an across-the-board or multi-boot qualification of every workload.

**2026-09-25 — Mia kit `cad252b` production-line update adopted (weights unchanged: abliterated checkpoint, k=3).** Pinned base image by digest; fast loader — weight load 285s → 73s+8s, full boot ~10min → **3.5min**; indexer-chunked prefill unlocks CHUNKED_PREFILL_SIZE 4096. Measured: cold prefill **3664 tok/s @32k** (was ~2200) and **2638 tok/s @400k, TTFT 151s** (was 1534 tok/s / 259s — +72%); decode unchanged (35.1 single / 68.6 agg@4). Adapters adopted: fast_load, engram_prefetch, wo_a_w8(+mid/drop), draft_head_fp8(tp4), block_verify, folded_fence, autotune_keep, replicated_split, draft_main_proj_split, shared_pad_k, sleep-on-idle, MoE fused finalize OFF (determinism). Not adopted (canary-roce images only): RoCEnante, prefill-SP, EP1+routed-MoE, draft_tau. Two k=5-only adapters dropped after real boot failures: router_live (engine source drift), verify_cap (confidence tensor expects k=5 layout — our k=3). All gates green post-swap: G0, G1 30/30, G2 3/3, G3, G4 needle 32k+400k; abliteration probe intact. Kit artifacts: `artifacts/dsv41-sglang-20260914/kit/start.sh.cad252b-local.patch` (our env-forwarding re-patch), `kit/env.tp4.cad252b.redacted`.

**k=5 vs k=3 re-benched on the new line (2026-09-25, Jun's call, winner serves):** k=5 → 32.7 single / 62.1 agg@4; k=3 → **35.1 / 68.6**. k=3 kept (+7%/+10%) — consistent with the pre-cad252b result, so the ordering survives the recipe change. k=5's code-category runs spiked to ~70 tok/s but prose and aggregate sagged. This also means verify_cap/router_live (k=5-only adapters) stay dropped.
> [`dealignai/DeepSeek-V4.1-Flash-UNCENSORED-FP8`](https://huggingface.co/dealignai/DeepSeek-V4.1-Flash-UNCENSORED-FP8)
> under [Mia's SGLang kit](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks) — **1M configured context** (earlier EP4 needle validation; EP2 depth sweep through 160k),
> DSpark **k=3** (+14% over k=5, stream-measured), ~33–43 tok/s single stream depending on workload, prefill ~1.5× our vLLM champion, tools + thinking on,
> Earlier EP4 gates: 30/30 structured, tool round-trip 3/3, reasoning engaged. Current EP2 smoke checks: 7/7; see the forced-tool limitation above.
> The checkpoint remains the same uncensored variant.
> **Skip the Engram pack:** our pre-packed shards are on Hugging Face —
> [neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark](https://huggingface.co/neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark) (192 GB, TP=4).
> **Want the standard (censored) checkpoint?** Use [Mia's recipe](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks) as-is — it is the same world; only the checkpoint and the Engram pack differ.
> **→ [How we run it, and the fixes it took](#dsv41-sglang-2026-09-14)** · [vLLM champion archive](#deepseek-v4-1-flash) · [Qwen](../qwen-3.8-flash-next/JOURNAL.md) · [GLM archive](../glm-5.3-flash/JOURNAL.md) · [DeepSeek V4 archive](../deepseek-v4-flash/JOURNAL.md)


---

<a id="deepseek-v4-1-flash"></a>

## DeepSeek V4.1 Flash — 4× DGX Spark

**In plain English:** a 510 GB frontier MoE serving on four Sparks, at **51 tok/s for one
person** on mixed tasks (**61–73 tok/s when the task is code, math or tables**), **~105 tok/s
aggregate across four concurrent streams**, with **420k context**, tools and vision on. Written
answers are fast; the *waiting* is the weak spot — cold prefill runs ~1.0–1.5k tok/s, so a
100k-token prompt costs ~70 s before the first token.

> **Final tables (2026-09-10 PDT).** Campaign closed with a six-boot A/B/A verification:
> baseline (probabilistic draft, batch 8192) → champion (greedy, batch 16384) → baseline again.
> Verdict: **the two configs are indistinguishable** — decode 66.1 / 74.6 / 74.1 tok/s across
> A1/B/A2, accept length 4.34/4.29/4.31 — while identical configs differ by +11% across boots.
> The rig boots bimodally (~65 vs ~74 tok/s decode) and that boot-lottery, not any knob, was
> behind the day's apparent gains. Numbers below are the verified final boot. Warm the world
> after any relaunch before trusting a measurement.
>
> **Update 2026-09-13:** the bimodality now has a prime suspect. With
> `vm.compaction_proactiveness=0` on all four nodes, **every measured boot landed in fast mode**
> (73.1 / 73.7 / 73.3 / 77.9 tok/s) — zero slow boots across a night of relaunches. See
> [host tuning, bimodality and the abliterated A/B](#dsv41-2026-09-13) below.


### Current champion numbers

All rows: temperature 0, thinking off, after warmup, batch 1, on `DRAFT_METHOD=greedy` +
DSpark k=5, `MAXLEN=430080` (420k). Method and raw files:
[`artifacts/dsv41-vllm-20260910/`](../../artifacts/dsv41-vllm-20260910) ·
[full section](../../docs/dsv41-vllm-tp4.md).

| metric | value | conditions |
|---|---:|---|
| C1 per-stream decode — **8-category mean** | **50.5 tok/s** | verified final boot; short prompts, Tony prompt set v1 |
| C1 per-stream — **math / coding / format** | **70.0 / 71.4 / 71.2 tok/s** | the strong categories; counting ceiling reads 83.2 |
| C1 per-stream — **reasoning / json** | 58.6 / 45.3 tok/s | |
| C1 per-stream — **prose / summary / narrative** | 31.7 / 27.9 / 27.7 tok/s | the weak categories: DSpark accepts only ~2 tok/step there |
| C4 per-stream / aggregate | 31.6 / **109.4 tok/s** | four concurrent streams, same prompt set |
| C6 aggregate | **136.7 tok/s** | six streams; above tonyd2wild's boot-10 (131.86) on identical hardware |
| C1 record protocol (`bench-decode`, 2048-token completions) | 74.6 tok/s median (72.7–76.4) | fast-boot mode; slow boots read ~65 — boot bimodality, config-independent |
| decode at depth 5k / 10k | 44.2 / 44.3 tok/s | mild depth cost, no collapse |
| cold prefill (unique prefix) | 1,659 / 1,477 / 1,495 / 1,431 / 1,416 tok/s | 2k / 8k / 32k / 64k / 100k prompts |
| DSpark acceptance | 4.3–4.8 mean tok/step · 66–75% rate | workload-dependent; ~6 on counting/tables, ~2 on prose |
| KV pool | 1,530,285 tokens in the 430,080 window (3.56×) | GMU 0.80, block 128 |
| advertised sequence cap | **4** | C4 = 56% of C1 per-stream; C6 43%; C8 27% — aggregate peaks around C6 |
| weights per rank | 81.58 GiB | incl. DSpark draft layers; model load 273 s |

**Honest comparisons.** Our own **V4 Flash** on the same fabric did **136 tok/s C1 best-case**,
66–93 at real chat depth and 182 at C4 — so **V4.1 Flash is slower than V4 Flash on this
hardware**. It is a bigger MoE with heavier routing and two
Engram lookups per step that V4 Flash does not have. Quote the model, not just the cluster.

### How it fits on four Sparks at all

The checkpoint is 510 GB: 296 GB FP4 routed experts, ~203 GB of **FP8 Engram n-gram tables**
(2 layers × ~384M rows × 256 B), ~10 GB attention/dense. With 128 GB unified memory per node,
the experts split fine — the Engram tables do not. They stay in the safetensors files on each
node's NVMe and each TP rank reads **its own quarter** of the rows on demand, dequantising on
the CPU and staging into the forward pass before it runs. That trick is
[tonyd2wild's + Kai's](https://github.com/tonyd2wild/DeepSeek-V4.1-Flash-vLLM-DGX-Spark), and
it's what makes the difference between "does not fit" and 51 tok/s.

<a id="dsv41-2026-09-13"></a>
### 2026-09-13: host tuning, the boot lottery, and an abliterated A/B

A day of operations findings, all measured on this world. Raw files:
[`artifacts/dsv41-vllm-20260910/ab-unc-20260913/`](../../artifacts/dsv41-vllm-20260910/ab-unc-20260913)
and the `unc-*` arms under `artifacts/dsv41-vllm-20260910/phase4/`.

**Host tuning that mattered — `vm.compaction_proactiveness=0`.** On a Spark the GPU's memory
*is* ordinary system pages, so the kernel's background compactor unmaps pages from the GPU as
it migrates them; a serving box allocates once and gains nothing from the upkeep. We took the
setting (and its reasoning) from
[bilikaz's Qwen3.8 GB10 recipe](https://github.com/bilikaz/qwen38-flash-next-cluster-recipe)
and persisted it with `vm.swappiness=10` in
[`scripts/99-dsv41-serving.conf`](../../scripts/99-dsv41-serving.conf). Result: **four measured boots,
four fast-mode boots** (73.1 / 73.7 / 73.3 / 77.9 tok/s) where the previous week ran ~50/50
against a ~65 tok/s slow mode. Not yet proof (≈6% by luck), but the first lever that has moved
the lottery at all.

**Two settings from the same recipe that did *not* transfer**, each tested as a one-variable arm
with a same-night champion boot as control:

| arm | C1 coding / math / prose | C4 coding | accept len | verdict |
|---|---|---:|---:|---|
| champion (control) | 71.9 / 68.9 / 30.9 | **50.9** | 4.29 | — |
| `--async-scheduling` | 72.8 / 69.9 / 30.7 | 47.0 | **3.44** | rejected — lower at C4, and it disturbs the speculative path |
| cpuset `5-9,15-19` (the 3.9 GHz cores) | 72.9 / 67.1 / 31.3 | 43.8 | 4.38 | rejected — no gain |

**Abliterated checkpoint A/B.**
[`dealignai/DeepSeek-V4.1-Flash-UNCENSORED-FP8`](https://huggingface.co/dealignai/DeepSeek-V4.1-Flash-UNCENSORED-FP8)
is a byte-identical drop-in on paper (same architecture, 96,085 tensors, same quantization block,
zero config diffs, matching chat template) and boots on this recipe with three env-line changes.
It **failed two of our gates**: 4 of 30 structured outputs came back **empty** at temperature
0.7–1.0 (clean at temperature 0), and thinking mode never engaged (no reasoning content with
thinking on). Tool round-trip 3/3, refusals gone. Fine for direct greedy chat; not a serving
brain for agents. Gate scripts: [`scripts/ab-uncensored.sh`](../../scripts/ab-uncensored.sh).

**A wedge class, and the fixes it forced.** Twice in one afternoon the engine stopped generating
while `/health` and `/v1/models` kept answering — one rank stalled in the decode loop and the TP4
collective blocked behind it. Candidate triggers: heavy NVMe writes on a serving node (the Engram
tables are ~51 GiB per rank and cannot be page-cached with ~22 GB free, so every decode step
reads from disk — a 510 GB download on the same drive is poison), and DSpark Triton kernels
JIT-compiling mid-inference. Fixes shipped: the launcher now runs a
[prewarm pass](../../scripts/dsv41-prewarm.py) before declaring the world up;
[`dsv41-recover.sh`](../../scripts/dsv41-recover.sh) requires a real 1-token completion before its
"API is up" fast path (an API-up check is not a liveness check); the
[catch-up sidecar](../../docs/CATCHUP.md) gained backpressure (max 2 warms in flight,
latest snapshot wins, interactive turns first); and the operating rule is now **no bulk writes on
a serving node**.

**Where this points next: SGLang.** [MiaAI-Lab's
DeepSeek-v4.1-Flash-DGX-Sparks](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks)
runs the same model on the same hardware on SGLang and publishes **3,350–3,780 tok/s prefill**
(ours: 1,400–1,660), **45.4 tok/s single-stream prose** (ours ~31), parity at four streams, and a
**needle-verified 1M context** with an 8M-token KV pin. Their speculative decoding works on
SGLang; the SGLang Blackwell verify fix (#38879) merged after the image our abandoned SGLang lane
was built from. A gated re-trial — our corruption repro first, then head-to-head on this harness —
is the next thing we run. Credit to Mia for the reference numbers and for stating the memory-stall
mechanism plainly: *host RAM is GPU memory on a Spark; anything that stalls one rank stalls them
all, because TP is synchronous.*

Run it yourself: [recipe and findings](../../docs/dsv41-vllm-tp4.md) — image chain, the eight
bind-mounted patches, launcher env, fabric + clock-lock requirements, and
[`scripts/dsv41-recover.sh`](../../scripts/dsv41-recover.sh) for the node-reboot case.

<a id="dsv41-sglang-2026-09-14"></a>
### 2026-09-14 → 15: the re-trial passed — SGLang is the serving world now

**If you only read one list — the things that were not in any recipe:**

1. **The corruption gate.** Our first SGLang lane (pre-#38879 image) garbled the DSML tool-call
   markup on the second turn of a tool exchange. `gates/rawgen3.py` (in the kit trial dir) renders
   a tool round-trip prompt with the server's own encoder and checks the raw generation. Run it
   3× on any new image before anything else — it's the difference between "works" and "works
   until an agent uses a tool."
2. **Busy is not wedged.** A 200k+-token prefill will not answer a 1-token probe inside any short
   budget. Our recovery wrapper read that as engine death and killed a healthy world (35 min
   outage). Read `/v1/loads` first; restart only when nothing is running *and* nothing is
   waiting *and* the probe fails.
3. **The NFS exporter is unkillable.** `dsv41-nfs` holds kernel nfsd state; `docker rm -f`
   returns "did not receive an exit event" while any worker has the export mounted. You cannot
   re-point it live. For a second checkpoint, **bind-mount the local copy on each worker as a
   docker volume** (`--driver local --opt type=none --opt o=bind`) and set `NFS_SHARE=0` — faster
   boot, exporter untouched.
4. **`start.sh serve` can hang after Ready.** The engine prints `Ready: API on port 8000`, serves
   fine, and the kit's readiness loop never exits. Wrap it in a timeout; judge health by a real
   1-token completion, never by the script returning.
5. **A separate Engram pack per checkpoint.** The tables are derived from the weights, so the
   abliterated checkpoint needs its own pack (`ENGRAM_DIR` / `WORKER_ENGRAM_DIR` pointed at a
   sibling dir). Keep both packs; a checkpoint swap is then a profile flip. Ours are published
   (TP=4) so you can skip the ~10 min/node pack:
   [neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark](https://huggingface.co/neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark).
6. **Never bulk-write NVMe on a serving node.** Engram reads disk every decode step; a pack or a
   large copy on a live node stalls one rank and the TP collective behind it. Pack with the
   world stopped.
7. **Don't measure decode with wall-clock.** Non-streaming wall time includes prefill; it cost us
   a false-alarm bisection. Stream, count usage tokens between first and last delta.
8. **`DSPARK_BLOCK_SIZE` 5→3: yes, once measured properly.** Our first rejection (2026-09-15)
   was based on the polluted wall-clock bench. Stream-measured on the uncensored world, same
   boot class, one variable (2026-09-16): **k=5 30.2 tok/s single / 58.6 agg@4 → k=3 34.4 / 67.8**
   (+14% / +16%); a second k=3 boot read 32.8 / 68.6. The `DSpark gamma mismatch` line is a
   warning, not an error — Mia's EXL3 kit runs k=3 against the same block-5 draft on purpose.
   **Serving at k=3 now.**
   Note the workload bimodality, visible in the raw runs: prose prompts decode ~31–34 (DSpark
   accepts ~0.3 on prose) while code/math land ~52–60. k=5 read `[29.2, 59.7, 54.5, 30.1, 30.2]`;
   k=3 read `[34.4, 55.0, 51.9, 31.6, 33.6]` — same four prompt classes, one variable. Prose +3–4,
   code even, aggregate +16%. Compare medians to medians; 34.4 (prose median) vs 57 (a code run)
   is not a regression, it's a different prompt.
10. **XGrammar structural tags for DeepSeek tool calls — ON (`SGLANG_TOOL_STRICT_LEVEL=1`), measured.**
   The `dev-dsv41` image already ships the V4.1 structural tag (`deepseekv41_detector.get_structural_tag`,
   xgrammar 0.2.1) but it is OFF by default: it only engages on `tool_choice=required`, `tool.strict=true`,
   or `SGLANG_TOOL_STRICT_LEVEL>=1`. With the env unset every agent tool call is generated unconstrained
   and parsed after the fact. Level 1 (FUNCTION) constrains the DSML payload after the trigger token;
   level 2 (PARAMETER) also forces strict JSON schemas — start with 1. The kit's env allowlist has to
   forward it (`start.sh`, head + worker). Measured 2026-09-21, uncensored world, k=3, stream protocol,
   `scripts/toolbench.py` (tools attached, temp 0):

   | | strict OFF | strict 1 |
   |---|---|---|
   | tool-call decode, single | 60.0 tok/s | 51.3 (−15%) |
   | prose with tools attached | 36.1 | 33.2 (−8%, per-step mask cost even on free text) |
   | no tools (dsbench) | 32.8–34.4 / 67.8–68.6 agg | 33.4 / 66.9 (unchanged) |
   | 4 tool requests, wall | 4.7 s / 437 tok | **3.6 s** / 272 tok (tighter outputs, no preamble) |
   | schema-valid tool calls | 16/16 | 16/16 |
   | gates G0/G1/G2 | pass | pass (clean / 30/30 / 3/3) |
   | grammar compile, first use of a toolset | — | 3 tools 0.1 s · 40 tools 1.5 s · 60 nested 6 s, cached after; **~50 s** first-ever compile after boot (JIT) |

   Verdict: kept. The per-token premium is real (8–15% on tool-bearing traffic, which for pi lanes is
   all traffic) but small in absolute terms, wall time on tool-heavy batches got *faster* because the
   constrained outputs drop the prose preamble, and malformed DSML becomes structurally impossible
   rather than trained-away — insurance for exactly the stressed-context conditions the gates don't
   cover. The one operational trap is the cold JIT: `recover-sglang.sh` now fires a throwaway
   tool-bearing warmup before declaring RECOVERED so the first agent message never eats the 50 s.

9. **The DSpark SPS cost table does not work with Engram (yet).** Profiling it takes a dedicated
   boot (`SGLANG_DSPARK_ENABLE_SPS_RECORD=1 SGLANG_SIMULATE_ACC_LEN=1.0 SGLANG_RAGGED_VERIFY_MODE=static`,
   `SKIP_SMOKE=1` because simulated acceptance breaks the smoke's exact-answer check), and the
   kit's env allowlist has to be patched to forward those three. The fit succeeds — and then the
   world **fails to boot** with the table loaded: compact ragged verify hands the Engram layer a
   ragged batch (`engram target-verify expects one equal block per request, got 28 tokens for 8
   requests of 4`). The Engram forward assumes a fixed verify block; ragged verify violates it.
   Table parked as `dspark_sps.json.ENGRAM-INCOMPATIBLE-20260916`; nothing to gain here until
   upstream teaches `layers/engram.py` ragged blocks. Two restarts to learn it; written down so
   nobody pays a third.

Runbooks: [`artifacts/dsv41-sglang-20260914/`](../../artifacts/dsv41-sglang-20260914) (profile,
local patch, restart/update procedure) and the checkpoint-swap trial script `unc-trial.sh`
(gates, auto-revert) described below.

The gated re-trial ran on Mia's kit at
[`MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks`](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks)
(image `lmsysorg/sglang:dev-dsv41`, post-#38879) with our `.env.tp4` fabric profile.
**Every gate passed**: corruption repro 3/3 clean (the bug that killed our first SGLang lane is
gone), structured outputs 30/30, tool round-trip 3/3, reasoning content present, needle at
32k / 400k / 1M. Head-to-head on this harness against the vLLM champion, same night, same prompts:

| | SGLang TP4 | vLLM TP4 champion |
|---|---:|---:|
| prefill tok/s (5 shapes) | 2243 / 2356 / 2357 / 2166 / 1950 | 1659 / 1477 / 1495 / 1431 / 1416 |
| C1 coding / prose | 75.95 / 35.7 | 71.9 / 30.9 |
| C4 coding aggregate | 51.25 | 50.9 |
| context | **1,048,576** (needle-verified) | 430k (governed) |

Prefill ~1.5×, decode a nose ahead, 1M context for real. Jun: *"sglang is faster, let's stick
with that."* vLLM stays staged as the fallback. Ops cutover: watchdog and
[`scripts/dsv41-recover.sh`](../../scripts/dsv41-recover.sh)-style wrapper retargeted to the SGLang
world, with one lesson written in blood the same morning — **busy is not wedged**. A world
mid-prefill of a 215k-token prompt will not answer a 1-token probe inside any short budget; the
recovery wrapper read that as engine death and killed a healthy world (35 min self-inflicted
outage). The wrapper now reads SGLang's `/v1/loads` first and only restarts when nothing is
running *and* nothing is waiting *and* the probe fails.

**Session-pinned KV (2026-09-14).** The serving world runs `--enable-session-radix-cache`:
requests carrying a top-level `session_id` hold references on their radix KV and eviction
consumes unreferenced entries first. Measured: a pinned 14k-token prefix stayed warm (0.3–0.4 s
TTFT) through three ~130k-token unrelated prefills that would have flushed it under global LRU.
We pin exactly one lane (Eva's), rotating the session id and calling `/close_session` when a
compaction collapses her prompt — everyone else takes the occasional cold minute by design. The
corollary that surprised us: on a shared radix tree, *catchup replays and context governance
are cache policy*. Advertising 1M let lane contexts balloon until one morning queued 460k
uncached prefill tokens; lanes are now governed at 430k while the world still serves 1M to
direct callers.

**Mia's 2026-09-15 hardening, adopted with one exception.** Upstream commit `93d9e6b` added an
output cap for requests that omit `max_tokens` (`DSV41_MAX_NEW_TOKENS=32768` — their incident
was a frozen harness running a 714k-token vision loop to remaining context), a decode-side
**loop abort** (n-gram / identical-token / repeated-line, finishes with `finish_reason=stop`;
the GPU watchdog never fires while tokens keep arriving), the `enable_thinking` alias, and
publisher-table reasoning budgets (`SGLANG_DSV41_REASONING_EFFORT=75`). All adopted; loop
abort measured at zero decode cost. **Not adopted: `DSPARK_BLOCK_SIZE` 5→3.** Booted it
live: the shipped draft config is block 5, the boot logged `DSpark gamma mismatch`, and their
k=3 evidence is TP3 prose only. We keep k=5.

**A number we had wrong.** Our night table's "decode median 77.2" was measured by
`bench_decode_full.py`, which needs `/metrics` — which the *serving* world has never exposed.
It came from a separate metrics-enabled bench boot. Measured on the serving world with the C1
stream protocol (2048-token completions, temp 0, thinking on *or* off): **43.3–43.6 tok/s
single stream**, accept len ~2.5 at k=5 — right on Mia's published TP4 figure of 45.4. Four
restarts and one false-alarm bisection to learn that non-streaming wall time includes prefill.
Write the protocol down before you compare numbers.

**The abliterated checkpoint re-passed on SGLang (2026-09-15) and is now the serving brain.**
[`dealignai/DeepSeek-V4.1-Flash-UNCENSORED-FP8`](https://huggingface.co/dealignai/DeepSeek-V4.1-Flash-UNCENSORED-FP8)
under Mia's SGLang TP4 world: G0 corruption 3/3, G1 structured **30/30 across temp 0/0.7/1.0**
(the vLLM-era empties at temp>0 did not reproduce — runtime, not weights), tools 3/3,
**reasoning mode engages** (the other vLLM failure, also gone), needle 32k/400k. Both original
failures were vLLM-side. Swapping is a profile flip: `mia/.env.tp4.uncensored` mounts the
checkpoint on workers as **local bind volumes** (no NFS — the exporter can't be re-pointed
live; kernel nfsd state makes the container unkillable) and reads Engram from its own
`dsv41-engram-unc/` pack. Runbook: `forge:~/dsv41-sglang-trial-20260914/unc-trial.sh`
(auto-reverts to the censored checkpoint on any gate failure). The Engram packs are published:
[neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark](https://huggingface.co/neko-legends/DeepSeek-V4.1-Flash-uncensored-engram-4x-spark)
— 192 GB, TP=4 only, skips the ~10-min-per-node pack step.
