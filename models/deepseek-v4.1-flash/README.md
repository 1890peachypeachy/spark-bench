# DeepSeek V4.1 Flash — four-Spark profiles

> **2026-10-04: serving moved to TensorFold on four Sparks** (jayleaton's engine, our TP=4 port, the 2.9-bit EXL3 uncensored pack): 1.68× prose and 1.75× code decode over this SGLang profile across 1k–160k prompts, slower cold prompt reading. **[Current profile: tensorfold-4x/](tensorfold-4x/README.md)**. The SGLang TP4/EP2 profile below is stopped and kept as the rollback.

## SGLang TP4/EP2 (served 2026-10-02 → 2026-10-04)

As of 2026-10-02: SGLang on forge/anvil/ember/flame, **TP4 / EP2**, native FP8/MXFP4 uncensored checkpoint, DSPARK block 3, Engram on local SSDs. All four Sparks participate. EP2 partitions experts into two groups with two-way tensor sharding inside each group; TP remains four for the model.

[Measured depth sweep and raw results](../../artifacts/tensorfold-v41-depth-20261001/REPORT.md) · [Historical serving work](JOURNAL.md#dsv41-sglang-2026-09-14) · [Upstream kit](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks)

## Exact change from the EP4 profile

The image, checkpoint, quantization, TP4, DSPARK k=3, 4096-token prefill chunks, eight request slots and 1,048,576-token configured context are unchanged. Only expert layout and loading policy changed:

| Setting | Before | Selected |
| --- | ---: | ---: |
| `EP_SIZE` | 4 | 2 |
| `DSV41_FAST_LOAD_EP_SIZE` | 4 | 2 |
| `DSV41_FAST_LOAD_TP_SLICE` | auto | 1 |
| `DSV41_FAST_LOAD_INFLIGHT_GB` | 6 | 1 |
| `DSV41_FAST_LOAD_SLAB_MB` | default 256 | 64 |
| `DSV41_FAST_LOAD_THREADS` | default 16 | 4 |

`EP_SIZE` is a top-level `.env.tp4` setting. The five `DSV41_*` settings belong in the existing **`EXTRA_CONTAINER_ENV`** string on this kit: replace existing entries and append missing ones while retaining all other adapters. Merely adding arbitrary top-level shell variables does not establish that the launcher forwards them. Do not replace the whole environment string with these five settings.

Without sliced expert reads, the first EP2 load approached 1 GiB available memory and was stopped. The selected loader reads only the owned rank slices and bounds staging. Engram files and weights were not repacked or converted.

## What the measurements establish

72 single-stream 512-token trials: both profiles at 1k/20k/40k/80k/160k, prose and code, three trials each; restored EP4 at 1k and 160k adds 12 trials. One cold request plus two repeats per cell. Outside inference traffic was isolated during measurement. Reported decode speed is an SSE timing proxy, with complete token usage and raw outputs retained.

Prose improved 5–12% against the initial control. Code varied: -2% at 20k, +1.7% at 40k, larger gains elsewhere. Endpoint gains survived an EP4 reboot control. Cold prompt-reading latency did not materially improve. No C4-at-depth or broad quality claim is made. The earlier short-prompt C4 pilot measured 68.8 → 75.7 tok/s.

Final EP2 boot passed seven arithmetic, automatic tool-call/continuation, structured-output and reasoning smoke checks. Forced `tool_choice=required` returned raw DSML on both profiles and remains unresolved. The configured window is 1M; EP2's new depth tests stop at 160k. Effective total-token capacity on the selected boot was 7,179,008, not the configured 8M target.

## Our installation and rollback

On forge, the kit is `/home/jun/dsv41-sglang-trial-20260914/mia`, commit `cad252b7d3000cf21d919764e70a6912b6d3b0b0`. Settings are in `.env.tp4`. The image is `dsv41-4x-spark:local`, ID `sha256:c3eb554429c6b5167ae319d167587eee4c7f0446018573c4ad95ea6ff6f406aa`. Hostnames and paths describe our installation, not universal defaults.

The original EP4 profile is privately snapshotted at `/home/jun/tensorfold-v41-campaign-20261001/baseline/env.tp4`. To restore it on our cluster:

```bash
ssh forge 'bash /home/jun/tensorfold-v41-campaign-20261001/restore.sh'
```

This stops and restarts all ranks. The kit's readiness wrapper can hang after the engine is ready; verify a real completion as well as health. Keep the current EP2 profile separately before rollback if you intend to switch back. Never start a second full model on the occupied Sparks.

## Reproduce the benchmark

Run on the head against an idle, exclusively reserved server; the run command flushes its shared radix cache. The published fixtures avoid recalibrating prompts on a different tokenizer:

```bash
python3 scripts/bench-v41-depth-ab.py run \
  --fixtures artifacts/tensorfold-v41-depth-20261001/fixtures.json \
  --output my-new-run.jsonl --label my-profile --tokens 512 --reps 3
python3 scripts/test_bench_v41_depth_ab.py
```

The archived `depth-run-control.sh` is lab-specific: it temporarily changes inference-port ingress rules and runs a memory guard. Review its paths and node names before using it elsewhere. No native TensorFold V4.1 engine is deployed; the TensorFold port is separate work.
