# ernie55-tf4 — ERNIE-5.5-Flash-Preview on TensorFold-native, TP4 (4x DGX Spark)

Experimental TensorFold port of `baidu/ERNIE-5.5-Flash-Preview`, written by Antigravity (Victor's MacBook Pro) on 2026-11-24
and finished/brought up by Spark the same day. The vLLM lane (`../ernie55-tp4`, recipe `ERNIE-5.5-Flash-Preview-4x-DGX-Sparks`)
remains the production-grade recipe; this one is a bring-up, not tuned.

## What is here

| File | What |
|---|---|
| `tensorfold-ernie55.patch` | Full ERNIE family port as a `git apply`-able patch against `ashhart/TensorFold` **549b55a** (35 files: new `zig/src/families/ernie55/`, `zig/kernels/cuda/ernie55/`, `zig/build/ernie55.zig`, ERNIE chat/tool parsers, plus core/server/tokenizer edits). |
| `start_tensorfold.sh` / `stop_tensorfold.sh` | Host-process launcher as used on spark3 (`/var/tmp/ernie55/`). Ranks: spark3=0 (API), spark1=1, spark2=2, spark4=3. Fabric 10.73.0.x, master 10.73.0.3:29688. Serves `:8888` as `GLM-5.3-Flash-EXL3` (fleet contract). |

## Build (on spark3)

```bash
cd /var/tmp/ernie55/tensorfold-ernie          # TensorFold @549b55a + this patch
/var/tmp/tf1017/zig-aarch64-linux-0.17.0/zig build native -Dfatbins=/var/tmp/ernie55/fatbins -Doptimize=ReleaseSafe
cp zig-out/native/bin/tensorfold-native /var/tmp/ernie55/bin/
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do scp -q /var/tmp/ernie55/bin/tensorfold-native $h:/var/tmp/ernie55/bin/; done
```
Build takes ~2 min. Needs `/var/tmp/ernie55/lib/libnccl.so.2` and `/var/tmp/ernie55/fatbins` on the head; binary + lib on every rank.
Verify identical md5 of `bin/tensorfold-native` on all 4 before launch. Boot to `/v1/models` ≈ 300 s.

## Fix applied by Spark (2026-11-24)

`InvalidDraftCount` killed worker ranks after the first completed request: the shared lane host asks the family for a
depth-0 draft when a stream has no draft budget left; `cuda_dspark.Drafter.draft` rejects `n == 0`. Fix in
`cuda_engine.zig Engine.block`: absorb the kept rows, then `if (out.len == 0) return;` (all ranks take the same path).
MiniMax-M3's DSpark family already accepts depth 0. Earlier Antigravity fix (17:16 build): division-by-zero panic in
`qmmf.matmulOut` during drafter `absorb` on prefill.

## Measured 2026-11-24 (Spark, single run, quiet fleet)

| Test | TensorFold (this) | vLLM tuned E5 (ref) |
|---|---:|---:|
| c1 prose tok/s | 34.6 | 41.0 |
| c1 code tok/s | 53.6 | 53.6 |
| c4 aggregate tok/s | 30.4 (≈8/stream) | 104.2 |
| Prefill, 19.8K-token needle | 273 tok/s (72 s), exact retrieval PASS | ~1500 tok/s |
| Thinking (`reasoning_content`) | PASS | PASS |
| Tool call `get_weather(Tokyo)` | PASS | PASS |
| Back-to-back requests (crash trigger) | PASS after fix | — |

## Prompt cache (Spark, 2026-11-24, build md5 2dcf5497)

Added `snap_*` hooks (pattern from the MiniMax-M3 CUDA family): kept states stand on the 256-row prompt grid; rank 0's
store marks a chunk start, `Leader.save` broadcasts `Kind.save` so every rank copies its own shard under one id,
drops ride with the next step (`Kind.drop`), and a prompt pass resumes by sending the id in the chunk header (`seed`).
State kept: DSA `mla_kv`+`idx_k` rows `[0,at)`, each HCA layer's last 256 SWA ring slots + compressed blocks
`[0,at/128)` (the C128 compressor has no partial block at a 256-aligned mark), the DSpark ring. Prefill now absorbs
every chunk's tail into the draft ring (was: only the prompt's last 128) so a resume carries drafter context.
Startup line now reads "a 16.8 GiB prompt cache".

| Test (greedy) | Cold | Warm |
|---|---:|---:|
| 6,662-token prompt, same request twice | 22.08 s | **0.73 s** (6,656 cached), output byte-identical |
| Turn 2 = turn 1 + reply + new question (6,698 tok) | — | **0.97 s** (6,656 cached), answer correct |

The lane serves real traffic (GBrain's LiteLLM bridge on the Mac mini points at :8888); concurrency benchmarks taken
while it is busy are contaminated: check `POST` counts in the rank-0 log before trusting a cN number.

## Profile (nsys rank 0, `--cuda-graph-trace=node`; default graph tracing hides graph kernels and reads ~17% busy)

Decode is GPU-bound (~97% busy), ~57 ms GPU per verify round: FP8G qmmf GEMVs ~26 ms (80–190 GB/s on small
shapes; `qmmf_bench.cu` shows TensorFold's default cluster split-K of 8 is 15–50% slower than sk 1–4 here), routed
MXFP4 MoE ~10 ms (at bandwidth), RoCE gathers ~6.5 ms (~140/forward, latency-bound), `hca_attn` ~4 ms.
Prefill (256-row chunks) is 100% busy: `mxfp4_w13_situ`+`w2_combine` 48% (per (row, expert) GEMVs, no reuse across
rows), RoCE gathers 25%, DSA attention/absorb ~8%.

Known gaps (not fixed): streams are served one at a time per round (single-sequence `Engine.cur`), so concurrency
does not scale; prefill is ~5x slower than vLLM (256-row passes, no prompt cache); `libtfgrammar.so` missing →
structured output / `tool_choice=required` return HTTP 400; no API key on a 0.0.0.0 bind (same as other lanes on the fabric).
Not registered in `ops/spark-lane` yet (the `ernie55-tp4` id is the vLLM lane); `spark-lane status` will not see it.
