# Nemotron 3.5 Super VL 120B-A12B (NVFP4) · TensorFold (Zig engine) · four Sparks, TP-4

The canonical result files behind the [Nemotron lane](../../README.md#nemotron-tensorfold), copied from
[tensorfold-4x-sparks](https://github.com/neko-legends/tensorfold-4x-sparks) (`engine/zig-nemotron/results/`), where the
engine, the scripts and the full run logs live. Live config: TP-4 over RoCE, `--parallel 16 --context 307200
--segments 4 --prompt-cache-gib 40`, disk tier on, `NCCL_MAX_NCHANNELS=2`, MTP drafting on (build c3ede919 since
2026-10-16). Thinking off, greedy.

| folder | what | when |
| --- | --- | --- |
| [`rebench/`](rebench/) | `qbench` areas one at a time against the persistent server (each step bracketed by the server's counters, `counters.jsonl`) + the vision reads | 2026-10-15 |
| [`live-speed/`](live-speed/) | qbench's speed area and `draft-speed.py` on the live build (drafting on): the speed numbers below | 2026-10-16 |
| [`prefill/`](prefill/) | cold prompts at 32K / 131K / 200K tokens, before and after staggered segments | 2026-10-15 |
| [`serving/`](serving/) | 16 streams at once at 4 vs 16 slots (`p4base-conc`, `p16-conc`); 200 agents × 10K-token history at a 16 vs 40 GiB cache; 8 × 30K-token conversations after a restart without and with the disk tier | 2026-10-15 |
| [`memory/`](memory/) | memory per Spark: idle (read-only `free` / `nvidia-smi`) and with the cache full | 2026-10-15/16 |
| [`vision-serving/`](vision-serving/README.md) | 1 / 4 / 8 / 16 image requests at once, new and seen images; one-stream decode on image vs text prompts | 2026-10-16 |
| [`numbers.json`](numbers.json) | every number in the charts, with its source file | 2026-10-16 |

| Area | Nemotron 3.5 Super VL | DeepSeek V4.1 Flash (same suite) |
| --- | ---: | ---: |
| Knowledge, MMLU-200 | 85.0 % (170/200) | 88.5 % (177/200) |
| Math, GSM8K 0–29 | 96.7 % (29/30) | 100 % (30/30) |
| Coding, 5 tasks | 80 % (4/5) | 80 % (4/5) |
| Instruction following, 20 | 95 % (19/20) | 90 % (18/20) |
| JSON schema / tools / long context to 299K / summary facts kept | 100 % / 100 % / 100 % / 100 % | 100 % / 100 % / 100 % / 100 % |
| Vision text, 166 strings | 100 % | 100 % |
| Vision shapes, 30 / objects counted, 23 | 87 % / 4 % | 87 % / 96 % |
| Code / prose, 1 stream (tok/s) | 185.4 / 94.9 | 155.4 / 72.0 |
| 4 streams, aggregate (tok/s) | 206.8 | 172.1 |
| 16 streams, aggregate (tok/s) | 214–230 | – (4 slots) |
| Cold 200K-token prompt | 48.3 s | 36.8 s |

DeepSeek's column: [`../qbench-dsv41-zig-rebench-20261015.json`](../qbench-dsv41-zig-rebench-20261015.json) (the
re-run after the fabric fix, quality identical to the first run) and the same vision harness. Nemotron's shapes figure
is with `NCCL_MAX_NCHANNELS=2`: the shapes scene read 17/20 with the cap and 19/20 without it.
