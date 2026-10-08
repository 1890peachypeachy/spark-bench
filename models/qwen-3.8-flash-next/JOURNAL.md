# Qwen 3.8 Flash Next on 4× DGX Spark — journal

Every dated entry for this model, newest first: what we changed, what it measured, what failed and why. Moved here unchanged from the top-level README on 2026-10-05 (old screenshots retired; the lane chart is on the [README](../../README.md)). Raw files stay where the entries link.

---

<a id="qwen-3-8-flash"></a>

## Qwen 3.8 Flash Next (NVFP4) — 4× DGX Spark

### Upgrade — 2026-09-06 (PDT): MTP k=4 + opt-in GEMV

The official NVIDIA checkpoint is unchanged. After a controlled tuning campaign,
all four nodes serve `local/qwen38-gb10:e1-gemv-on` with **MTP k=4**;
resident PLE, FULL_DECODE_ONLY, TP4+EP, 262,144 context and 16 sequences remain.
The original `e1` image is retained for rollback.

Raw measurement timestamps span September 6–7 UTC; the report and raw results linked below are the evidence.

| Metric (median tok/s, three repeats) | Fresh k2 baseline | k4 + GEMV | Change |
|---|---:|---:|---:|
| C1 code, streaming decode | 70.7 | **91.3** | **+29.1%** |
| C1 prose, streaming decode | 53.4 | 49.2 | **−7.9%** |
| C4 code, end-to-end aggregate | 198.6 | **247.9** | +24.8% |
| C8 code, end-to-end aggregate | 344.4 | **404.3** | +17.4% |
| C16 code, end-to-end aggregate | 526.8 | **600.5** | +14.0% |

Temperature 0, thinking off; C1 budgets 1,400 output tokens, aggregates 1,200
per stream. These are **fresh same-campaign baselines**, not the September 5
first-pass figures below. C1 decode and end-to-end aggregate use different timing
boundaries. Workload-specific observations, not a universal speed guarantee.

- **Retained:** k=4 drafting and a gated M=1 BF16 vocabulary GEMV, adapted from
  [bilikaz's recipe](https://github.com/bilikaz/qwen38-flash-next-cluster-recipe)
  / myllmbox-runner's b12x kernel. Exact TP4-shape microbench: 1.47×;
  incremental server A/B at k4: +4.0% C1 code, +3.2% C16 (smaller than the
  combined upgrade; aggregate variation warrants further repeats).
- **Rejected:** compaction 20→0 (no measurable benefit or compaction events in
  our A/B/A windows) and performance-core pinning (−3.1% C1 code). Restored;
  no persistent host tuning. This does not establish why another topology stalls.
- **Validation:** reported 7/7 correctness gates, 19/19 tokenizer-calibrated
  retrieval checks, and a 30-minute soak with 110 rounds / 364k tokens / zero
  failures. **The soak missed C16** due to phase-selection logic; C16 was
  benchmarked separately. Long-run production qualification remains open.
- **Tradeoff:** single-stream prose is ~8% slower. Their TP2 peak of 80 tok/s
  used different weights and steady engine windows, so it is not a direct
  comparison with our streaming rate. We have not reached 100 tok/s here.

**[Campaign report and rollback](../../results/qwen38-tuning-2026-09-06/REPORT.md)**
· [Raw arm results](../../results/qwen38-tuning-2026-09-06/arms)
· [Benchmark harness](benchmarks/README.md)
· [GEMV candidate image recipe](../../results/qwen38-tuning-2026-09-06/gemv-candidate-image)

**Image availability:** the GEMV variant is currently a **local build**, not a
published GHCR tag. The public `ghcr.io/neko-legends/qwen38-flash-next-nvfp4-gb10:e1`
remains the original image and does not include this GEMV upgrade.

### Initial resident-PLE benchmark — 2026-09-05

The mmap and external-reference comparisons published that day were not controlled: thinking
modes differ in the mmap C1 comparison, and the claimed mmap “gather tax” was not isolated. See
the measurements and limitations below.

[nvidia/Qwen3.8-Flash-Next-NVFP4](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-NVFP4),
the official NVIDIA checkpoint, first served **2026-09-05**. One vLLM endpoint
at `forge:8000`, **TP4 + expert parallel**, one NVMe checkpoint copy per node,
CX-7 RoCE between all four GB10s. No checkpoint conversion or TP2 pairs.

**Status: stopped 2026-09-10**, when the cluster world moved to DeepSeek V4.1 Flash; the
recipe, launcher and results are retained and it can be relaunched from
`~/qwen38-tuning-20260906/rollback-serve.sh`. It was campaign-qualified, not
production-qualified: the benchmarks below are preliminary, and long-run stability was never
the gate that got exercised.

### Tested configurations and measurements (2026-09-05, archived k2 results)

| Metric | NVMe mmap PLE + PIECEWISE | Resident PLE + FULL_DECODE_ONLY (September 5) |
|---|---:|---:|
| GPU memory utilization setting | 0.80 | 0.78 |
| bf16 KV pool | 5,055,959 tokens | **4,016,501 tokens** (15.32× native context) |
| Aggregate @4, end-to-end | 105.5 tok/s | **191.5 tok/s** |
| Aggregate @8, end-to-end | 210.6 tok/s | **334.1 tok/s** |
| Aggregate @16, end-to-end | 344.0 tok/s | **510.6 tok/s** |
| C1 code, thinking off | not separately measured | **70.0 tok/s**, median of 70.3 / 70.0 / 69.6 |
| C1 prose, thinking off | not separately measured | **51.4 tok/s**, median of 52.6 / 51.2 / 51.4 |
| C1 code, thinking on | 26.3 tok/s (one run) | **52.3 tok/s**, median of 3 |
| C1 prose, thinking on | 24.8 tok/s (one run) | **53.4 tok/s**, median of 3 |
| Cumulative MTP accepted/drafted tokens | 22,705 / 24,042 (94.4%) | 25,062 / 27,496 (91.1%) |

**Reading these honestly:** aggregate cells are one 1,200-token-per-stream code
run at each concurrency, temperature 0, thinking off, usage-based token counts
divided by wall time. C1 uses 400-token budgets and first-to-last streaming-delta
timing. These are preliminary observations, not paired multi-boot significance
estimates. MTP ratios cover each boot's accumulated traffic, not isolated bench
windows. The initial 26.3/24.8 C1 figures had thinking **on** and must not be used
as a direct baseline for the 70.0/51.4 thinking-off figures.

The September 5 resident configuration improved both observed aggregate throughput and C1
speed, at the cost of ~1.04M KV tokens. PLE residency, graph mode and memory
budget changed together; we have **not isolated their individual contributions**.
The earlier claim that mmap adds 0.4–1.3 seconds to *every decode step* was not
established by the logs (they also included long-prefill traffic). Keep mmap as
a capacity-oriented alternative, not a universal dead end.

### Real-work validation: agent worker tasks (2026-09-05)


| Task (latency) | Cloud | Qwen 3.8 NVFP4 on 4× Spark |
| --- | ---: | ---: |
| Builder | 344 s | **12 s** |
| Reviewer | 50 s | **4.1 s** |
| Synthesis | 355 s | **57 s** |
| IF | 36 s | **9.5 s** |
| Batch classification | ~5 s | 12 s |

The point of the cluster: not synthetic decode speed, but doing the work this
household's agents actually do. Same fixtures, same judge across all columns;
the Sparks column ran with thinking off. Local holds **quality parity or better
on all five tasks** (Builder 0.99, Reviewer/IF/Batch 1.00, Synthesis 0.96) at
**zero marginal inference cost**, with latency wins up to ~29× on the heavy
tasks. Honest caveat: batch classification is *slower* locally (12s vs ~5s
cloud) — small-prompt traffic doesn't amortize the TP4 collective overhead.

### September 5 configuration, validation and references (historical)

September 5 launch settings: **resident PLE, FULL_DECODE_ONLY**, graph capture sizes
`[1,2,4,8]`, MTP k=2, bf16 KV, 262,144 native context, 16 sequences, MNBT 8192,
GPU memory utilization 0.78, stock-selected MoE backend, TP4+EP. Native context
is the supported target; **1M YaRN is not our production default**.

- Greedy repeatability: simple probe byte-identical ×3 on the resident lane.
  Tool-call smoke passed on the initial mmap lane; repeat validation under load
  and a longer stability soak remain open.
- Retrieval smoke: **9/9 passed** on the resident lane, across three nominal
  sizes and 0/50/100% insertion positions. Sizes were estimated from word counts,
  **not tokenizer-verified 4k/32k/128k**; those exact-length gates remain open.
- SGLang was source-reviewed, **not benchmarked here**. The inspected SM121 QSA
  implementation restricts supported head topologies to TP1/TP2, and the NVIDIA
  MTP checkpoint needs additional dispatch work. We are retaining vLLM TP4;
  external TP2 measurements are not a measured engine comparison or a universal
  claim that SGLang TP4 can never work.

[Qwen model guide](README.md)
· [Full configuration, image identity, patches and methodology](nvfp4-tp4/README.md)
· Published image: `docker pull ghcr.io/neko-legends/qwen38-flash-next-nvfp4-gb10:e1`
· [Recorded benchmark summary](../../results/qwen38-nvfp4-tp4-2026-09-05.json)
· [Resident-lane retrieval smoke output](../../results/qwen38-resident-niah-smoke-2026-09-05.jsonl)

Community references: [tsw2k quad recipe](https://github.com/tsw2k/Qwen3.8-Flash-Next-Quad-DGX-Sparks),
[NVIDIA forum writeup](https://forums.developer.nvidia.com/t/381897),
[MiaAI dual-Spark recipe](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Dual-DGX-Sparks),
[blazux GB10 patches](https://github.com/blazux/qwen3.8-Flash-DGX), and
[getrefined NVIDIA PLE fix](https://github.com/getrefined/Qwen3.8-Flash-Next-NVFP4-vLLM-DGX-Spark).
The forum's 31 C1 / 97 @8 / 157 @16 are useful reference points, not a controlled
comparison against our prompt corpus, output lengths or timing protocol.
