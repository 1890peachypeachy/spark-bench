# ERNIE-5.5-Flash-Preview vLLM TP4 hill-climb — PLAN / log

Method: [inference-optimisation skill](https://github.com/sybil-solutions/inference-optimisation-skill) @ fda968e (MIT).
Ceilings and the profile: [THEORY.md](THEORY.md). Raw runs: `ledger.jsonl` (skill's `bench.py`), `spec.jsonl` (DSpark
counters per run), on spark3 under `/var/tmp/ernie55/hillclimb/` and copied here when a stage ends.

## Targets and constraints (set 2026-11-25; Victor: "focus on optimizing vLLM for ERNIE", lane free)

- Primary: **c1 decode** (agent loop). Secondary: **c4 aggregate**, cold prefill (~5K and ~20K tokens), short TTFT, startup.
- **Lossless only** (no quality trades). A change that alters numerics beyond summation order is labelled and gated by a
  greedy-equivalence check.
- Context **262,144** must stay as configured; KV pool fixed at 16 GiB/rank (not a lever in this pass).
- No regressions > ~3% on the other metrics.

## Protocol (skill, non-negotiable rules applied)

- One change per experiment, each its own `exps/NAME.env` (overrides through the recipe's `VLLM_EXTRA_ARGS` / `EXTRA_ENV`
  hooks, so the published launcher is what runs). Every candidate sits between two controls (`C`, the recipe as published).
- Bench: skill's `bench.py`, fixed 6-prompt panel, **seed 1234**, temperature 0.6, thinking on (always for ERNIE), 512-token
  replies, c1 = median of 6, c4 = wall-clock aggregate, prefill = prompt tokens / TTFT on unique cold prompts.
- Serialized by a lock; the lane is drained (0 running) before every stop; runner detached on spark3 (`scripts/hc.sh`).
- Accept only if the candidate beats **both** neighbouring controls on its target metric and regresses nothing by >3%.

## Log

### 2026-11-25 11:40 — stage 1: hardware, profile, baseline

- **probe-hw:** read 238.6 GB/s, copy 224.4 GB/s, BF16 95 TFLOPS, FP8 196 TFLOPS per GB10.
- **prof (graphs on):** 53.9 ms per decode iteration, GPU 96% busy. Not CPU-bound, so async scheduling (already on by default
  in this build: no `--async-scheduling` lever) and launch overhead are not the gap. Breakdown in THEORY.md.
- **C (baseline):** c1 **45.98** tok/s (39.2-49.7 by prompt), c4 **104.0**, prefill 1,513 (5.2K) / 1,546 (20.6K) tok/s,
  short TTFT 174 ms, startup 319 s, DSpark 2.40 tokens/step (74/44/22% by position).
- **prof-e (eager, op attribution):**
  - 186 all-reduces per iteration: 139 bf16 `[4,4096]` (~3 per layer), 46 **fp32** `[4,16,512]` (1 per attention layer).
  - The fp32 `gemmSN_TN<float>` group is the **MoE router** (`GateLinear`, fused 2x512 gates, `[4096->1024]`). The plugin
    declares fp32 params, and `GateLinear` excludes GB10 (sm_121) from its specialized tiers, so it falls to tier 7: x cast
    to fp32, plain fp32 `F.linear` over a 16 MB weight per layer per rank.
  - The bf16 `cutlass_80_wmma` group is the **HCA compressor projection** (bare `aten::mm` `[4096->1024]`, wkv+wgate).
    cuBLAS picks an SM80 WMMA kernel at M=4: ~155 us for 8 MB = 54 GB/s, 23% of bandwidth.

### 2026-11-25 12:02-13:25 — stage 2 and the GEMV lever

| Run | c1 | c4 | prefill 5K / 20K | tok/step | Verdict |
|---|---:|---:|---:|---:|---|
| C | 45.98 | 104.0 | 1513 / 1546 | 2.40 | control |
| X-tree `NCCL_ALGO=Tree` | — | — | — | — | **invalid**: AllGather has no tree algorithm (`NCCL error: invalid usage`). Not a speed result. |
| C | 45.20 | 102.5 | 1465 / 1533 | 2.41 | control |
| X-ch2 NCCL channels 4->2 | 44.86 | 104.7 | 1477 / 1510 | 2.39 | **reject**: c1 below both controls; c4 +2-4% inside drifting controls |
| C | 45.02 | 100.9 | 1532 / 1533 | 2.37 | control |
| X-ll `NCCL_PROTO=LL` | 43.02 | 103.9 | **1024** / 1018 | 2.36 | **reject**: c1 -4.5%, prefill -33%, TTFT +45% (LL halves bandwidth on 64 MB prefill reduces) |
| C | 44.32 | 104.1 | 1515 / 1539 | 2.40 | control |
| X-linb12x `--linear-backend b12x` | — | — | — | — | **invalid**: b12x has no ScaledMM kernel for 128x128 block FP8 |
| C | 45.38 | 106.1 | 1515 / 1535 | 2.43 | control |
| **X-gemv** (patch 11) | **47.17** | **110.4** | **1571 / 1606** | 2.44 | **beats both controls on every metric (+3.8% c1, +3.7-4.1% c4, +3-5% prefill)**; equivalence gate open (below) |
| C | 45.44 | 106.4 | 1526 / 1535 | 2.41 | control |

Control-to-control noise: c1 ±1.5% (slight downward drift), c4 ±2.5%, prefill ±2.5%.

**X-lt (cuBLASLt) rejected without a boot:** the cold microbench (`micro_gemv.py`, 24 rotating weight copies so every call
reads DRAM) at the router/compressor shape (N=1024, K=4096) gives, at M=4: cuBLAS bf16->fp32 40.9 us, **cuBLASLt 44.7 us
(worse)**, fp32 F.linear (router today) 81.5 us, vLLM's cuteDSL `ll_bf16_gemm` **35.8 us (= the 35.2 us DRAM floor)**. At
M=8-16 `ll_bf16_gemm` (split-K path) is slower than cuBLAS (56.7 vs 44.8 us), hence patch 11 applies only for M <= 16 and
the compressor gains least at c4. A first microbench without rotation was L2-hot and misleading (12.7 us for cuBLAS);
discarded.

**Patch 11** (`patches/patch_ernie_sm121.py` section 11, candidate kit `recipe-gemv`): on sm_12x, for M <= 16,
(a) the DeepSeek-V4 compressor's fused wkv/wgate projection and (b) the ERNIE router (now kept in the checkpoint's bf16,
GateLinear tier 1) run through `ll_bf16_gemm`. Both stay bf16 x bf16 with fp32 accumulation and fp32 output: products are
identical, only the summation order changes.

**Equivalence gate:** greedy (temperature 0, thinking on) X-gemv vs the next control: 0/8 outputs identical, one diverging
at the first token. Not yet a verdict: the control's own boot-to-boot determinism is unknown (b12x and split-K reductions
may not be deterministic), and a top-1/top-2 near-tie flips at any summation-order change. Next: repeat X-gemv with top-5
logprobs captured, plus two controls with logprobs, then compare the divergence-point logit gaps C-vs-C and C-vs-X.

**Profiling correction:** per-kernel durations overstate cost when graph branches overlap. Attribution in THEORY.md is
now credited by wall time (overlapped intervals shared): fp8 linears 12.2 ms, MoE 10.0, bf16 all-reduce 8.6, compressor
GEMM 7.0, router GEMM 3.9, fp32 all-reduce 3.2 per 54.9 ms iteration. The compressor kernel is the same cuBLAS kernel
and grid in the model as in isolation (split-K 8) but takes 155 us there vs 40 us alone: an in-model effect the
microbench cannot reproduce, which is why only a boot could decide patch 11.

Remaining levers found: the DSpark Markov head (`[1,256] x [256,201216]` bf16, 103 MB, replicated on every rank, 3 calls
per step at 464 us = bandwidth) could be vocab-sharded across TP (~1 ms/step, ~2%).

### 2026-11-25 13:25-14:33 — determinism, repeat, linear backends, qualification

- **X-tree2** (`NCCL_ALGO=allreduce:tree;allgather:ring;...`): c1 42.56, c4 93.0, prefill 1006 — **reject** (-6% / -13% / -34%).
  NCCL avenue closed: ring/4 channels/default protocol (the operator's pins) beat every alternative tried.
- **Greedy determinism:** two boots of the unchanged control: **0/8 identical** at temperature 0, divergence at positions with
  top-1/top-2 gaps of 0.005-0.82 nats. C-vs-X-gemv divergences are the same size (0.016-0.72). Exact-output gates are not
  available on this stack for any change. Correctness spot-checks (planets, French) fine in every finished capture.
- **X-gemv repeat:** c1 46.42, c4 104.5, prefill 1593/1613 (vs neighbours 44.81 / 42.99). c1 and prefill wins repeat.
- **--linear-backend cutlass / flashinfer_cutlass / triton:** all **invalid** (cutlass: deep_gemm scale-layout assertion
  `t.dim() == N` at load; flashinfer_cutlass: no ScaledMM kernel; triton: start-up failure). With b12x: 4/4 invalid.
- **Q (qualification):** clean checkout of the recipe branch with patch 11 (`9b118cc`), dry-run image hash = tested
  `17721a5a950a`, cold boot through `start.sh`: c1 **47.67**, c4 106.45, prefill 1580/1613. Gates (`scripts/qual.py`): chat,
  reasoning, tool-call round trip, needles 3/3 at 35,815 and 71,530 prompt tokens: **all pass**. Published to the recipe's
  `main` as `f8388f4`; lane left serving it.

## STATUS (plateau for config levers, 2026-11-25 14:35)

| Metric | Baseline (9 controls, mean +- sd) | Now (patch 11, 3 runs) | Ceiling | Harness |
|---|---:|---:|---:|---|
| c1 decode tok/s | 45.01 +- 0.87 | **47.09 (+4.6%)** | 100 at a=2.45 | skill bench, 6-prompt panel, median of 6, seed 1234, T=0.6, thinking on |
| c4 aggregate tok/s | 104.51 +- 1.84 | 107.11 (+2.5%, in noise) | — | same |
| prefill ~5K / ~20K tok/s | 1,511 / 1,537 | **1,581 / 1,611 (+4.6% / +4.8%)** | ~6,800 (50% MFU) | unique cold prompts |
| step (c1, profile) | 53.9 ms | not re-profiled | 24.4 ms | torch profiler |

Plateau reason: three consecutive config levers inside noise or worse (NCCL x3), the linear-backend family cannot run the
block-FP8 linears (4/4 invalid), cuBLASLt slower. What limits further gains (evidence in THEORY.md): FP8 block linears at
~53% of bandwidth (12.2 ms/step, deep_gemm only), 186 latency-bound all-reduces per step (~11.8 ms), the replicated DSpark
Markov head (1.4 ms). Ranked remaining levers with cost: recipe `docs/hillclimb.md`.

State changed: the lane serves the patched recipe (`ernie55-vllm:17721a5a950a`) on all four nodes; candidate kits
`/var/tmp/ernie55/recipe-gemv{,4}` and the extra images (`3f0400d1bc4d` = previous recipe, `17721a5a950a`) remain on the
nodes; `spark-lane up/down ernie55-tp4` targets the recipe kit on `main`. Not verified: task-level quality, c8+/c16, context
beyond 72K in this pass, `spark-lane down` and a harness-driven cold `up`.

### Queue (stage 2, 3): config levers first

| Exp | One change | Why (from the profile) |
|---|---|---|
| X-tree | `NCCL_ALGO=Tree` | 186 latency-bound all-reduces, ~11.5 ms/iter; ring = 6 hops at 4 ranks |
| X-ch2 | NCCL channels 4 -> 2 | less per-call work for 32-128 KB messages |
| X-ll | `NCCL_PROTO=LL` | force the low-latency protocol |
| X-linb12x | `--linear-backend b12x` | FP8 block linears at ~53% of bandwidth (16.7 ms/iter) |
| X-lt | `TORCH_BLAS_PREFER_CUBLASLT=1` | compressor bf16 GEMM at 23%, router fp32 GEMV at ~62% |

Next (code, after the config pass): router weights bf16 + cuBLAS fp32-out epilogue (`GateLinear` tier 6, products identical,
fp32 accumulation; worth it only if bf16 M=4 GEMMs get a good kernel, which X-lt tests), and a GEMV-class kernel for the
compressor projection if cuBLASLt does not fix it.


### 2026-11-25 23:04 → 11-26 05:20 — stage 3: public-recipe levers, FlashIndexer on GB10, concurrency (hc3.sh, 33 boots)

Trigger: Baidu's vLLM recipe (k=7, FlashIndexer) and SGLang's low-latency blog; Victor: "faster prefill, decode and
concurrency across the board". Same bench (6-prompt panel, seed 1234, T=0.6, thinking on), plus `conc.py` (c8/c16, and
c32/c64 where MAX_SEQS allows) and `longpf.py` (cold 156K/231K-token prefill + 3 needles). Raw: `results/2026-11-26/`.

| Exp | One change | c1 | c4 | c16 | c32 / c64 | prefill 82K / 156K / 231K | Verdict |
|---|---|---:|---:|---:|---:|---:|---|
| C (x13) | recipe f8388f4 | 44.5-49.7 | 99-108 | 222-233 (one 134, one 193 outlier) | — | ~1,515 / 1,424 / 1,302-1,331 | control |
| X-k5 | SPEC_TOKENS 3->5 | 43.66 | 93.6 | 175.0 | | flat | **reject** (tok/step 2.59 vs 2.33: not enough to pay for the wider verify) |
| X-k7 | SPEC_TOKENS 3->7 (Baidu default) | 39.92 | 84.1 | 160.8 | | flat | **reject** (wins only on the bash prompt, 55 vs 47) |
| X-kadapt | k by batch 7/5/3/2 | 39.00 | 99.1 | 221.0 | | flat | **reject** |
| X-kbs2 | k 3 @bs1-4, 2 @5-16 | 33.52 | 95.1 | 236.5 | | flat | **reject** (c16 inside noise; c1 anomaly) |
| X-kbs1 | k 3/2/1 by batch | 47.08 | 108.6 | 220.3 | | flat | **reject** (neutral) |
| X-mnbt16k (x2) | max-num-batched-tokens 16384 | 45.66 / 47.72 | 110.4 / 101.4 | 224 / 226 | | flat | **reject** (first c4 win did not repeat) |
| X-lg1g | VLLM_SPARSE_INDEXER_MAX_LOGITS_MB 256->1024 | 46.52 | 103.2 | 230.8 | | flat | **reject** (neutral) |
| X-fi | `--hf-overrides {"enable_flashindexer": true}` | — | — | — | | — | **invalid**: `fp8_fp4_mqa_logits() got an unexpected keyword argument 'clean_logits'` |
| X-fi2 (+9b) | same, patch 9b | — | — | — | | — | **invalid**: DeepGEMM `num_heads == 16 or 32 or 64` (FlashIndexer keeps 8) |
| X-fi2off | 9b+9c image, flag off | 46.70 | 104.0 | 230.6 | | 1,507 | patch inert when off |
| **X-fi2 / X-fi2L x2** (+9c) | FlashIndexer on | 45.8 / 47.4 / 46.2 | 104-107 | 224-228 | | **1,560 / 1,487-1,492 / 1,392-1,428** | **keep: prefill +3% @82K, +4.5-4.8% @156K, +6.9-7.3% @231K**; needles 3/3 everywhere, qual all_ok |
| **X-seq32 x2** | MAX_SEQS 32, graphs to 128 | 45.9 / 47.9 | 109 / 105 | 229 / 228 | **329 / 324** | flat | **keep** (c32 +42% over the c16 ceiling; c1-c16 unchanged) |
| **X-seq64** | MAX_SEQS 64, graphs to 256 | 45.39 | 105.1 | 227.8 | 328.5 / **439.3** | flat | **keep** (still rising at 64) |
| **Q2** | FlashIndexer + MAX_SEQS 64 together | 46.17 | 102.5 | 225.3 | 329.5 / **438.6** | 1,554 / 1,474 / 1,382 | **qualified**: chat, reasoning, tool round trip, needles 36K/72K/156K/231K all 3/3 |

Patch 9b (`scripts/patch9b.py`): vLLM 0.34 made the 6th positional arg of `fp8_fp4_mqa_logits` `max_seqlen_k` (int) and
dropped `clean_logits`; the plugin wrapper forwarded it as `clean_logits=`. Forward `*args` instead.
Patch 9c (`scripts/patch9c.py`): GB10's DeepGEMM MQA-logits kernel takes 16/32/64 heads only; FlashIndexer selects 8.
Pad to 16 by repeating the selected heads with weight exactly 0 (relu(q.k) x 0 = 0): same logits as the 8-head
selection, computed by a 16-head kernel (4x fewer heads than 64, not 8x). FlashIndexer itself is Baidu's learned
approximation of the full-head selection (not bit-lossless); gated by needles to 231K, all 3/3.

Why k>3 loses here when Baidu's default is 7: with sampling (T=0.6) and thinking on, per-position acceptance falls
70/41/21% and positions 4-7 add ~0.25 tokens/step while every verify row costs bandwidth (THEORY.md: step = 24.4 ms floor
at k=3). Baidu's ~5.1 accept length is measured on coding/agent traffic at 1M context on GB200; not our panel.

State: lane serves Q2 from candidate kit `/var/tmp/ernie55/recipe-fi` (image `ernie55-vllm:0d89801c0b01`). Recipe branch
`hillclimb-2026-11-26` (FLASHINDEXER=1 default, MAX_SEQS 64, graphs to 256, patches 9b/9c, preflight checks the
flashindexer file) generates byte-identical argv for all four ranks and the same image hash (DRY_RUN compared on spark3).
Not pushed; `spark-lane up ernie55-tp4` still starts `main` (the old config) until the branch is merged and the node kit
updated. Not verified: c64 per-stream TTFT under load, c128, KV-pool pressure at 64 long-context streams (pool 572K tokens).
