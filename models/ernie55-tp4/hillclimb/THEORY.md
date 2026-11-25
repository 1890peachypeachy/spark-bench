# ERNIE-5.5-Flash-Preview vLLM TP4 — ceilings (2026-11-25)

Method: github.com/sybil-solutions/inference-optimisation-skill (fda968e). Measure the hardware, count the bytes, then compare.

## Hardware (measured on spark3, `scripts/probe_hw.py`, in the lane's own image, lane down)

| | per GB10 | x4 (TP4) |
|---|---:|---:|
| read bandwidth (4 GiB reduction) | **238.6 GB/s** | 954 GB/s |
| copy bandwidth (read+write) | 224.4 GB/s | |
| BF16 GEMM 8192^3 / 4096^3 | 95.0 / 88.0 TFLOPS | 380 |
| FP8 GEMM 8192^3 | 196.4 TFLOPS | 786 |
| fabric | 100 Gb/s RoCE v2 (~12.5 GB/s) | |

## Model bytes (from the safetensors headers, `scripts/sizes.py`, `scripts/draft_sizes.py`)

| Part | GB | Notes |
|---|---:|---|
| routed experts, target | 143.747 | 42 MoE layers x 512 experts, MXFP4 (I8 codes + E8M0 scales), 6.69 MB per expert |
| target dense | 7.807 | attention 5.449, shared experts 1.057, mHC/norms 0.773, routers 0.352, layer-0 dense MLP 0.176 |
| lm_head | 1.648 | BF16 201216 x 4096 |
| embed | 1.648 | lookup only, not read per token |
| draft (DSpark, `model.mtp.*`) | 11.031 | 3 MoE layers: experts 10.268, other 0.557, Markov head 0.103 (rank 256); block size 7, we run 3 |

## Decode ceiling (bytes / bandwidth, TP4 = 1/4 per rank, zero communication cost)

- No speculation: 7.807 + 1.648 + 143.747 x 10/512 = **12.26 GB/token** -> 3.07 GB per rank -> 12.9 ms -> **77.8 tok/s** c1.
- DSpark k=3, one verify of 4 rows: experts union 1-(502/512)^4 = 7.59% -> 10.90 GB; verify = 20.36 GB.
  Draft (3 positions, 3 layers): 0.557 + 10.268 x 5.75% + 1.648 (LM head) + 0.103 = 2.90 GB. Step = 23.26 GB -> 5.81 GB/rank -> **24.4 ms**.
- c1 ceiling = accepted tokens per step / 24.4 ms: **100 tok/s at a=2.45** (long essays, sampled), **131 tok/s at a=3.2** (operator's agentic session).

## Where the baseline step goes (torch profile, rank 0, 80 decode iterations, c1, `prof_steps.py`)

Iteration period **53.9 ms** (47.5 ms target verify + 6.5 ms draft). GPU busy 96%: not CPU/scheduling bound.

| Kernel group | ms / iteration | vs floor |
|---|---:|---|
| deep_gemm FP8 block linears (attention, shared, dense) | 16.7 | floor ~8.8 ms at 238.6 GB/s: ~53% efficient at M=4 |
| b12x MoE (routed experts) | 11.0 | ~at the bandwidth floor |
| NCCL all-reduce (186 calls, ~49 us each; 46 of them FP32) | 11.5 | latency-bound; ~0 by bytes |
| bf16 `cutlass_80_wmma` GEMM (~42 calls) | 7.8 | unattributed (graphs hide the op); SM80 fallback path |
| fp32 `gemmSN_TN<float>` (42 calls) | 5.0 | unattributed; an FP32 GEMV per layer |
| mHC, sparse MLA, quant, split-K, other | ~10 | |

So the measured step is ~2.2x the bandwidth floor. The three addressable gaps, in order: FP8 linear efficiency (~8 ms),
all-reduce latency (~11 ms), and the two unattributed BF16/FP32 GEMM groups (~13 ms).

## Prefill ceiling

2 x 14B active params = 28 GFLOP/token. At 50% of the measured BF16 peak across four nodes (190 TFLOPS): ~6,800 tok/s.
Measured ~1,500 tok/s at 8-44K: ~22% of the practical ceiling. TP all-reduce traffic for an 8,192-token chunk is ~0.66 s
at 12.5 GB/s against ~5.4 s per chunk measured, so the gap is compute efficiency, not the fabric.
