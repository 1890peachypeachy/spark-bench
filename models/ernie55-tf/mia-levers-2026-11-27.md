---
type: note
title: Mia's (MiaAI-Lab) TensorFold recipes — levers for our ERNIE-5.5 TensorFold TP4 lane (2026-11-27)
---
# Mia's TensorFold recipes: what transfers to ERNIE-5.5 TP4 (2026-11-27)

**Scope.** I read 21 MiaAI-Lab repos, cloned read-only on 2026-11-27. The full list with HEAD commits is in
"Repos read" at the bottom. The closest sibling to our lane is
**DeepSeek-V4.1-Flash-1017-4x-DGX-Sparks-TensorFold @ 8ffa67d**. It has the same 4×GB10 TP4 shape, the same FP8 + MXFP4
expert format, the same `dsv4_hybrid` CSA/HCA/DSA attention + mHC, and a DSpark drafter. Its engine is bertholomus'
`dsv41` family, a TensorFold-native fork, plus about 53 patches.

## Headline comparison (author's own tables vs our harness; different prompts, so the comparison is directional only)
| | Mia DSV4.1 TP4 (ring, T=0.7 prose) | Our ERNIE TP4 Wave-4 (bench.py, T=0.6) |
|---|---|---|
| c1 / c2 / c4 / c8 aggregate | 65.8 / 96.5 / 130.5 / 165.3 tok/s | 48.3 / 50.1 / 76.5 / 101.4 tok/s |
| c2 ÷ c1 | 1.47× | 1.04× |
| cold prefill 16K / 64K / 128K | 4,052 / 4,134 / 4,058 tok/s | 1,578 (9K) / 1,510 (66K) tok/s |
| 1-row decode round | 21.5 ms (their ROUND_MS) | ~37–41 ms (our price log) |

Caveat: ERNIE reads about 166 MB/layer/rank of non-expert weights, so its 1-row floor is about 28–30 ms at 250 GB/s.
Its per-token decode floor is higher than DSV4.1's, so part of the gap is the model, not the engine.

## Levers, ranked for our lane
| # | Lever (source) | Mia/author measured | Our status | Our experiment |
|---|---|---|---|---|
| 1 | **Measured round-cost table.** `TF_DS_ROUND_MS`, DSV4.1-4x `scripts/config.sh`: "the EXL3-era table priced rows at half their cost, so the lane over-drafted at 4–16 streams". The same lesson appears in GLM-1104 `0096/0097`, Inkling `0019 TF_INKLING2_REPRICE` and Qwen-RTX `0009 round-cost-model`. | DSV4.1: c2–c8 scale 1.47–2.5×. GLM TP2: allocation moved, throughput within noise (policy plateau). | **Have the bug.** `gb10_shared_costs` is 1.2× too cheap at 5–9 rows, 1.5× at 16 and 1.9× at 32 (E0 price log, 1,929 rounds). | E1b/E2b: `TF_ERNIE55_SHARED_MS` env table (new knob) |
| 2 | **CUDA-graph policy for shared rounds.** DSV4.1 `0019` graph capture agreed across ranks, `0033 graph-cap`. | — | **Found a bigger problem.** At c≥4, 51% of shared verifies run eager and 19% capture. A 64-entry cache raises captures, and c8/c16 drop 23% (captures are far costlier than eager forwards). | E2a/E2c: `TF_ERNIE55_GRAPH_MAX_PARTS`, `TF_ERNIE55_CAPTURE_AFTER` |
| 3 | **Prefill yields to decoders.** DSV4.1 `0023/0031 TF_DS_PREFILL_YIELD`. | 15 decoders stalled 7.5 s → 1 s by a 25K prompt; a late short request got its first token in 0.31 s | **Already upstream.** Native CUDA `default_decode_share=0.25` for fills >32K rows; `--decode-share`, `TENSORFOLD_PREFILL_SHARE/BUDGET/ORDER` | tune only if agent UX needs it |
| 4 | **Drafter MLP split across ranks.** GLM-1104 `0109` | **+5–7% c1**, +2–12% c4, exact | **Check.** DSpark `feature_proj`/`markov_w1` are replicated; MoE layers sharded | profile first (eprof) |
| 5 | **Row-sharded redundant prefill work.** DSV4.1 WP4 `TF_DS_QUARTER_HC`, WP5 `OWNER_GATHER`, WP6b `IDX_SHARD` | part of their ~4K tok/s prefill; exact (needle 45/45) | **Port.** Our HC-mix and indexer run on all rows on every rank | after the prefill profile |
| 6 | **Prefill comm/compute overlap.** GLM-DERISKED `0050` paired prompt steps, `0035/0063` copy-engine exchanges, `0141` chunk halves on a side stream. TensorFold `--segments` (staggered segments; not wired for ernie55) | GLM 0.2.0: prefill 497 → 966 tok/s (bundle) | **Port.** We only overlap the shared-MLP all-reduce (≥256 rows) | after the prefill profile |
| 7 | **Shared expert on a side stream in decode.** GLM-DERISKED `0006/0010`, Qwen-RTX `0016`, DSV4.1 `SIDE=1` | small, exact | prefill only today | E3 candidate |
| 8 | **GPU top-k candidate sampling.** DSV4.1 `0021 TF_DS_SAMPLE_CAND`, Qwen-RTX `0008/0011` | +1.6–2.8% c4, +1.9–8.2% c8 (with EXPERT_EXIT) | ERNIE samples on GPU (`cuda_sampler.drawBatch`) | probably have |
| 9 | **Expert early exit.** DSV4.1 `0022 TF_DS_EXPERT_EXIT` | same bits, small | **Port** (decode kernels) | E3 candidate |
| 10 | **Block-scaled FP4 MMA for routed experts.** DSV4.1 `0037 mma_fp4`; Inkling `TF_INKLING2_PREFILL_TC`, `0025` native e2m1x2 unpack | prefill +4–6%, decode +1–6%. Inkling: 96.3% teacher-forced top-1 (lossy activations) | ERNIE uses software MXFP4 unpack; no `kind::mxf*` MMA | lossy variant needs Victor's OK; exact e4m3×e2m1 (`mxf8f6f4`) is a port |
| 11 | **Mixed slot sizes / shared KV pool.** pico-dgx-ds4: 4 slots @1M + 12 @128K, smallest-fit admission. GLM `SHARED_KV` (`TF_GLM_SEQ_GROW`, `DSA_SHARED`) | pico: 16 users 376 tok/s, agents 8×80–300K 260–270 tok/s | **Gap.** Every ERNIE slot reserves 3.58 GiB at 262K → 8 streams | biggest c16 lever (engine work) |
| 12 | **Fixed-prompt greedy decode harness + interleaved ABA.** GLM-1104 `docs/speed/RESULTS.md` | random-content tok/s swings 12%; rounds/s stable to 0.5%; host drift ~1.5% > small effects | our bench.py uses random prompts at T=0.6 | adopt for sub-5% A/Bs |
| 13 | **Lower memory reserve.** GLM-DERISKED `MEMORY_RESERVE_GIB=3–4` | +context/streams; one OOM-stop at 3 GiB on 6 Sparks | our reserve is 12.2 GiB | needs Victor's OK (wedge risk) |
| 14 | **Boot-time loader read-ahead.** DSV4.1 `0046 TF_DS_LOAD_PREFETCH`, `RANK_LOCAL` | load 83 → 27 s, start 417 → 197 s | our boot is ~300 s | quality-of-life |
| 15 | **Idle RDMA proxies park on a futex.** DSV4.1 `0034` | idle CPU 300% → 0.3%/node | unknown for ernie55 | power only |
| 16 | **Pin the RDMA proxy thread to a CPU.** `TF_DS_RDMA_CPUS` (DSV4.1 / 2x `0068`) | latency jitter | n/a until profiled | — |
| 17 | **Serve ReleaseFast.** DSV4.1 0053 note: "the served build has no such checks" | host overhead | we serve ReleaseSafe | E3 candidate (host-side only) |

## Not applicable or killed upstream
- **Ring-only transport** (TF_ROCE_RING, link graphs, pair-sum gathers): we run on a switch.
- **GLM 0109 ring split of prefill reduce:** −25 to −30% prefill. Mia killed it: fewer bytes but more serial latency.
- **Engram tables, image-keyed prompt cache, DSML tool parsing:** model-specific to DSV4.1.
- **CHUNK_SOLO:** fails as an improvement (+13–29% long-prompt TTFT). Opt-in for agent UX only.

## Repos read (HEAD when cloned)
GLM-5.3-Flash-DGX-Sparks-1104 6c55c20 · GLM-5.3-DERISKED-Cyber-DGX-Sparks-TensorFold 85f9d43 ·
GLM-5.3-Flash-EXL3-2x-DGX-Sparks-TensorFold 3906ac6 · GLM-5.3-EXL3-3x-DGX-Sparks-TensorFold eb6414b ·
GLM-5.3-Flash-2x-RTX-PRO-6000-TensorFold 61ef814 · DeepSeek-V4.1-Flash-1017-4x-DGX-Sparks-TensorFold 8ffa67d ·
DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks c7f2b85 · DeepSeek-v4.1-Flash-DGX-Sparks 64b02de · DeepSeek-v4-Flash-DSpark-2x-DGX-Spark a8b4636 ·
Inkling-2-Mini-DGX-Spark-TensorFold 3b210d1 · Inkling-2-Mini-RTX-PRO-6000-TensorFold db14f2c · Inkling-2-Mini-RTX-5090-TensorFold 86f1d69 ·
Nemotron-3.5-Bolt-TensorFold-DGX-Spark 6b064a3 · Ornith-1.5-122B-TensorFold 0c8fd6a · Qwen3.8-Flash-Next-Single-DGX-Spark-TensorFold b956dba ·
Qwen3.8-Flash-Dual-DGX-Sparks-TensorFold dc05c91 · Qwen3.8-27B-DGX-Spark-TensorFold c11ff13 · Qwen3.8-Flash-Next-RTX-PRO-6000-TernsorFold 57d815c ·
pico-dgx-ds4 eb307eb · sparkring b9cd552 · sparkLimiter 1b7a890.
