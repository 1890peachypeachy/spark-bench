# Qwen3.8-Flash-Next TP4 tuning campaign — 2026-09-06/07

Campaign worker: Depths-owned execution worker (handoff `depths-qwen38-tuning-20260906`,
authorized by Jun 2026-09-06 16:40 PDT). Exclusive Sparks use; restarts allowed.
All measurements on the 4× DGX Spark TP4+EP deployment, `http://forge:8000/v1`,
model `qwen3.8-flash-next`, NVFP4 mixed checkpoint (nvidia/Qwen3.8-Flash-Next-NVFP4,
image `local/qwen38-gb10:e1`, sha256:6fc66a65…0407).

## Executive summary

**Winner (qualified for this campaign, not production-qualified): MTP k=4 with the
opt-in GEMV candidate image `local/qwen38-gb10:e1-gemv-on`.** Launch command:

```bash
PLE_MODE=resident CUDAGRAPH_MODE=full MOE_BACKEND=stock GPU_MEM_UTIL=0.78 \
  IMAGE=local/qwen38-gb10:e1-gemv-on MTP_TOKENS=4 \
  EXTRA_ARGS="--mamba-cache-mode all" \
  bash /home/jun/launch-qwen38-tp4.sh --wait
```

Everything else is unchanged from the campaign baseline (stock template, thinking off by
default, 262144 ctx, seq16, MNBT 8192, resident PLE, stock MoE, full decode graphs, GPU_MEM 0.78).
No sysctl, affinity, or persisted host change is warranted by the data.

## Winner table (medians of ≥3 repeats; tok/s; streaming decode rate for C1, e2e for aggregates)

| metric | k2 baseline | k3 | k4 | k4+GEMV (final) | final vs k2 |
|---|---|---|---|---|---|
| C1 code decode | 70.7 | 79.1 | 87.8 | **91.3** | **+29.1%** |
| C1 prose decode | 53.4 | 50.1 | 49.0 | 49.2 | −7.9% |
| C1 TTFT (code) | ~0.09 s | ~0.12 s | ~0.09 s | ~0.09 s | — |
| C4 e2e | 198.6 | 224.3 | 251.3 | **247.9** | +24.8% |
| C8 e2e | 344.4 | 378.2 | 404.5 | **404.3** | +17.4% |
| C16 e2e | 526.8 | 576.9 | 581.8 | **600.5** | +14.0% |
| MTP accept-rate (agg arm) | 0.952 | 0.915 | 0.883 | 0.883 | (by design) |

- Boot-to-boot drift check (k2 repeated at end): code 69.6 vs 70.7, C8 344.3 vs 344.4,
  C16 525.9 vs 526.8 — within ±2.6%; the k4 wins are far outside the noise band.
- C4 in the GEMV arm measured 247.9 vs 251.3 stock (−1.4%, within the 198.6→205.0 spread
  we observed across identical-config repeats) — judged neutral, not a regression.
- **Known tradeoff:** prose single-stream decode regresses ~8% at k4 vs k2 (per-position
  draft acceptance decays faster on prose; code accepts longer drafts). Code aggregates
  (the mandatory gate: C4/C8/C16) all improve ≥14%. If prose-latency-sensitive workloads
  dominate, k3 is the compromise (prose −6%, code +12%).

## Candidates

| candidate | verdict | evidence |
|---|---|---|
| MTP k=3 | superseded by k4 | +12/+10/+9.5% C1code/C4/C8 vs k2; all correctness 7/7 |
| MTP k=4 | **retained** | +24/+27/+17/+10% vs k2 on code metrics; 7/7 correctness; deterministic repeat hash identical to k2 |
| vm.compaction_proactiveness 20→0 (all ranks, transient, sudo -n) | **rejected** | A/B/A on 180 s sustained C1 at k2: 69.8 / 69.7 / 70.1 tok/s — no change. Telemetry: compact_stall and compact_daemon_wake counters FLAT at setting 20 across all 4 ranks during sustained decode; zero >500 ms inter-chunk gaps in every phase. The bilikaz 4–5 s stalls (2-box TP2, 28G KV pin) do not reproduce on our 4-node resident serve. Not persisted anywhere. |
| perf-core cpuset 5-9,15-19 (docker update, all ranks) | **rejected, restored** | C1 code 85.1 vs 87.8 (−3.1%, all reps separated); C4 +0.8%/C8 −0.6%/C16 +2.8% (noise). A/B/A confirmed return to 86.6–87.7 after restore. Restored to 0-19 on all ranks (live-verified Cpus_allowed_list). Note: HostConfig now records "0-19" where the original was unset — functionally identical, cosmetic only. |
| M=1 BF16 vocab GEMV (b12x kernel via mbx runner build) | **retained (opt-in image)** | Microbench at our exact per-rank shape (62080×2560 bf16, M=1): 1.225 ms vs 1.799 ms cuBLAS = 1.47×, rel err 5.4e-05, gates verified (M=2/non-contiguous rejected). Server A/B at k4: C1 code 91.3 vs 87.8 (+4.0%, clean separation), C16 600.5 (+3.2%), C4/C8 neutral, accept-rate unchanged. lm_head verified unquantized bf16 in checkpoint quant config. Old image `e1` untouched. |
| async-scheduling | **deferred** | Our installed vLLM (0.1.dev20073+g8e685d198) — the recipe's `async-scheduling: true` is a flag we did not validate for the hybrid (GDN/mamba)+MTP combination in bounded time; not bundled with the k change. Left for a follow-up campaign. |

## Final-candidate validation (stage 7)

- Correctness gate 7/7 PASS (models, non-empty content, temp0 determinism, explicit tool
  call, tool-history roundtrip, JSON-schema structured output, thinking opt-in).
- Mixed prefill/short-request TTFT (one ~27k-token prefill + active decodes): first short
  request 3.52 s (queued behind the initial prefill chunk), steady-state 0.08–0.20 s.
- Tokenizer-calibrated NIAH (exact prompt counts via /tokenize, 3 needles × depths, 4k/32k/128k):
  **19/19 PASS**.
- 30-minute varied-concurrency soak with per-rank telemetry: **110 rounds, 364,176 tokens,
  0 failures**; throughput stable throughout (C1 ~90, C2 ~145, C4 ~255, C8 ~398 tok/s).
  Telemetry: no swap usage change, no compactor wakes, min MemAvailable 5–9 GB/rank.
  Harness note: the soak's phase logic accidentally never cycled C16 (covered C1/C2/C4/C8 +
  long-prefill + prose rounds); C16 was separately measured 3× on this boot in the agg arm.
- Post-soak drift bench (same boot): C1 code 90.7–92.8 (median 91.1 vs 91.3 pre-soak), C4 251.4,
  C8 398.7, C16 591 — all within the ±2–3% noise band. No degradation.
- Contamination check: 0 in-flight requests at start of every arm; request counters showed
  no external traffic during benchmark windows (cluster exclusive per authorization).

## Honest comparison notes (per handoff)

- bilikaz's "80 peak / 73 mean" single-stream numbers are steady 10 s **engine-window**
  measurements on their custom hibrid47 NVFP4-table checkpoint with their image at TP2 —
  NOT our streaming-decode or end-to-end numbers, on a different checkpoint and topology.
  Our 91.3 tok/s C1 code decode is a first-to-last-chunk streaming rate on the official
  NVIDIA NVFP4 checkpoint at TP4; the figures are not directly comparable and we do not
  claim 4 nodes guarantees >100 tok/s for any workload.
- Our e2e aggregate rates include per-request TTFT and stream setup; they are not engine
  throughput windows.

## Provenance

- External recipe: `a950c2ee41b4786585a2fd900979d6ed38d37e12` (bilikaz qwen38-flash-next-cluster-recipe v2)
- External runner build: `cf0c755f20c595dcb0cae545a6dc7a36178eefd3` (myllmbox-runner; GEMV kernel
  vendored from b12x, Apache-2.0 — attribution preserved in `mbx_vocab_gemv.py` docstring and
  the candidate image Dockerfile comments)
- Base image (unchanged): `local/qwen38-gb10:e1` ← `vllm/vllm-openai:qwen38-flash-next@sha256:fc120ece…5bf8`
- Candidate image: `local/qwen38-gb10:e1-gemv-on` (sha256:1896b6b14e9c…4b55f88, identical ID on all 4 ranks)
- Launcher: `/home/jun/launch-qwen38-tp4.sh` (backed up: forge `~/qwen38-tuning-20260906/launch-qwen38-tp4.sh.orig`,
  local `~/nest/tmp/qwen38-tuning-20260906/rollback/`)

## Rollback

```bash
# exact campaign-start serve (k2, stock image):
PLE_MODE=resident CUDAGRAPH_MODE=full MOE_BACKEND=stock GPU_MEM_UTIL=0.78 \
  EXTRA_ARGS="--mamba-cache-mode all" \
  bash /home/jun/launch-qwen38-tp4.sh --wait
```

Private working telemetry: `~/nest/tmp/qwen38-tuning-20260906/` (local) and
forge:`~/qwen38-tuning-20260906/` (remote). Campaign lock: forge:`~/qwen38-tuning-20260906.lock`.

## Harness

New fail-closed harness in `models/qwen-3.8-flash-next/benchmarks/`:
`q38bench.py` (single/agg/sustained; validates count/usage/finish/content; thread
exceptions fail the run), `run-arm.sh` + `tel-collect.sh` (per-rank metrics/vmstat/PSI
telemetry + MTP counter deltas + contamination gates), `corrcheck.py` (correctness gate),
`niah2.py` (tokenizer-calibrated NIAH), `soak.py` (varied-concurrency soak).
Unlike the archived 2026-09-05 scripts, aggregates here fail closed on thread exceptions.

Known harness gap: the PSI column in telemetry CSVs is mangled (over-aggressive `tr`
deleted '0'/'1' chars); memory/swap/vmstat columns are valid. Raw un-simplified telemetry
CSVs remain in the private campaign dirs, not committed here.
