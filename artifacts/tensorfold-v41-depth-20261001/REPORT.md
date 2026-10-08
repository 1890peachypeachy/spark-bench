# V4.1 context-depth comparison: TP4/EP4 versus TP4/EP2

Date: 2026-10-01 PDT / 2026-10-02 UTC. These are SGLang configuration measurements, not TensorFold inference results.

## Decision

EP2 is a modest, workload-dependent decoding improvement on this fixture. It is selected for serving with the bounded rank-sliced loader. It is not a claim of improvement on every workload or of beating unrelated V4/GLM benchmarks. Cold prompt-reading latency did not materially improve. The original EP4 configuration and restore script remain available on forge.

## Full depth sweep

Single-stream generation tok/s, median of three 512-token completions per cell. Actual prompt counts differ from the labels by at most one token. All 60 primary measurements completed with exactly 512 output tokens.

| Prompt depth | EP4 prose | EP2 prose | Change | EP4 code | EP2 code | Change |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 35.9 | 37.7 | +5.0% | 55.7 | 62.2 | +11.6% |
| 20,000 | 35.5 | 38.0 | +7.2% | 58.1 | 56.9 | -2.0% |
| 40,000 | 34.5 | 38.1 | +10.6% | 52.9 | 53.8 | +1.7% |
| 80,000 | 34.6 | 37.1 | +7.3% | 50.3 | 59.9 | +19.0% |
| 160,000 | 34.1 | 38.3 | +12.2% | 47.5 | 54.6 | +15.0% |

The prose gain was 5–12% throughout this sweep. Code was mixed: -2% at 20k, near parity at 40k, and larger gains at 1k/80k/160k. There are only three requests per cell and generated texts vary, so small differences are not established regressions or wins.

## Reboot control

After the full EP2 sweep, EP4 was restored and the exact 1k/160k fixtures were repeated three times each (12 additional measurements). These are independent control boots, not additional EP2 replications.

| Depth / workload | EP4 first boot | EP4 restored | EP2 | EP2 versus restored |
| --- | ---: | ---: | ---: | ---: |
| 1,000 / prose | 35.9 | 35.1 | 37.7 | +7.4% |
| 1,000 / code | 55.7 | 51.4 | 62.2 | +20.9% |
| 160,000 / prose | 34.1 | 35.0 | 38.3 | +9.3% |
| 160,000 / code | 47.5 | 49.8 | 54.6 | +9.7% |

The endpoint advantage survived the restored control. This supports a practical, modest decoding benefit; it is not a multi-boot statistical qualification of every depth or concurrency.

## Cold time to first token

One cold observation per cell after a successful radix-cache flush; seconds. This includes prompt processing and first-token work, not a pure prefill kernel measurement.

| Depth | EP4 prose | EP2 prose | EP4 code | EP2 code |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.52 | 0.50 | 0.52 | 0.53 |
| 20,000 | 5.42 | 5.48 | 5.34 | 5.34 |
| 40,000 | 10.85 | 10.72 | 10.77 | 10.76 |
| 80,000 | 22.12 | 22.03 | 22.04 | 22.00 |
| 160,000 | 49.17 | 48.12 | 49.17 | 52.06 |

At 160k, repeated-prompt TTFT was below 0.8 seconds on both profiles. Do not compare those cache-hit timings with cold prefill. The 160k code cold observation was slower on EP2 (52.06s versus 49.17s initially / 47.78s on restored EP4); cold TTFT has only one observation per cell per boot.

## Reproducible protocol

- Same checkpoint, tokenizer, image, four Sparks, TP4, DSPARK block 3, context limit, request limit and 4096-token prefill chunks. No precision, GPU clock or host tuning change.
- Deterministic synthetic reference corpus plus separate lighthouse-essay and LRU-cache coding tasks. Both arms use identical saved request bodies; comparison checks hashes and exact prompt counts.
- Prompts calibrated through /v1/tokenize. Temperature 0, seed 0, thinking disabled. Warmup excluded. At each cell, first trial follows /flush_cache, then two identical repeats.
- External requests to port 8000 were temporarily rejected during each measured sweep; localhost requests were allowed. Rules were removed afterward. Health checks call /health and do not generate benchmark traffic.
- Memory sampled on all four nodes; guard aborts after two samples under 3 GiB available. No abort occurred during measured sweeps.
- Rate is (usage.completion_tokens - 1) / (last visible SSE event - first visible SSE event). This is a streaming decode-rate proxy: speculative events may contain multiple tokens. Raw usage, text, hashes and event timestamps are retained.
- All 72 measured requests produced 512 tokens. Seven harness protocol tests passed, including missing usage, dropped stream, short output, unexpected reasoning and text-format cache-flush handling.
- Repeated greedy outputs are not byte-identical on this SGLang build. Output variation and speculative acceptance contribute to the observed run-to-run spread. Do not present these runs as proof of TensorFold exactness.
- This depth sweep is single-stream. Four-stream results in the earlier pilot are separate; no C4-at-depth claim is made here.

## Selected profile and rollback

Only expert parallelism and loading policy change; TP remains 4 and Engram remains SSD-backed:

```text
EP_SIZE=2
DSV41_FAST_LOAD_EP_SIZE=2
DSV41_FAST_LOAD_TP_SLICE=1
DSV41_FAST_LOAD_INFLIGHT_GB=1
DSV41_FAST_LOAD_SLAB_MB=64
DSV41_FAST_LOAD_THREADS=4
```

The slice/buffer settings avoid the whole-expert staging memory spike observed in the earlier pilot. They are forwarded through EXTRA_CONTAINER_ENV in the existing kit. No model weights were converted or modified.

Original EP4 snapshot: /home/jun/tensorfold-v41-campaign-20261001/baseline/env.tp4. Rollback: bash /home/jun/tensorfold-v41-campaign-20261001/restore.sh on forge. The readiness wrapper can hang; confirm restoration with a real completion, not only its exit status.

Runtime: dsv41-4x-spark:local, image sha256:c3eb554429c6b5167ae319d167587eee4c7f0446018573c4ad95ea6ff6f406aa; kit cad252b7d3000cf21d919764e70a6912b6d3b0b0. Native TensorFold V4.1 forward/TP4/Engram/DSPARK support is still unimplemented.

Raw files: fixtures.json; ep4-depth.jsonl; ep2-depth.jsonl; ep4-recheck.jsonl; comparison.json; memory and load snapshots. Scripts: ../../scripts/bench-v41-depth-ab.py and ../../scripts/compare-v41-depth.py (from repository root these are scripts/...).

## Final deployment verification

EP2 is serving. The final boot passed 7/7 automatic-tool/arithmetic/structured-output/reasoning gates. The inference-port isolation rules were removed, and a completion from the Windows client returned 42. Effective token capacity on the selected boot: 7179008. EP4 rollback remains preserved. No TensorFold model backend was deployed.
