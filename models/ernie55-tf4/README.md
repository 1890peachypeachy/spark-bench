# ernie55-tf4 — ERNIE-5.5-Flash-Preview on TensorFold-native, TP4 (4x DGX Spark)

Experimental TensorFold port of `baidu/ERNIE-5.5-Flash-Preview`, written by Antigravity (the owner's MacBook Pro) on 2026-11-24
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

## Prefill: expert-major tensor-core MoE, 1024-row chunks, ring all-reduce (build md5 5e534873)

- `mxfp4_situ.cu` gains an expert-major path for rows >= 128 (`cuda_forward.grouped_min_rows`): picks sorted by expert
  (`mxfp4_route_*`), w13+SITU and w2 as per-expert `mma.sync m16n8k16` bf16 GEMMs with the MXFP4 tile dequantized
  to bf16 once a block (exact), then the per-pick kernel's in-order top-k combine. `moe_test.cu` (synthetic weights):
  rel-L2 1.4e-4 vs the per-pick kernels, 99.7% of outputs bit-equal; 7.6 ms vs 66.7 ms a layer at 1024 rows,
  9.5 vs 134 at 2048. (`mxfp4_grouped.cuh` = a CUDA-core expert-major variant, bit-identical but compute-bound.)
- `prompt_rows` 256 -> 1024, `swa_cap` 1024 -> 2048 (ring >= chunk + 128). The cache grid stays 256 (`engine.snap_grid`):
  a chunk ends early at a mark the store asked for.
- All-reduces of >= 1 MiB go through `ncclAllReduce` (ring, 1.5x the shard on the wire) instead of the RoCE
  all-gather + rank sum (3x at TP4); decode-sized messages keep the RoCE gather.
- **Bug fixed:** the DSA indexer scored a whole chunk into `idx_scores`, which holds only `min(rows,64) x capacity`
  floats: at 256-row chunks it overflowed into neighbouring scratch past ~65K context (untested before). It now
  scores in 64-row slices, each bounded by its own last position.

| Test (quiet lane, `suite.py`) | 256-row build | 1024-row MMA build |
|---|---:|---:|
| Cold 6,662-token prompt | 22.08 s | 9.98 s |
| Prefill 3.3K tok | 301 tok/s | 683 tok/s |
| Prefill 13K tok | 273 tok/s | 591 tok/s |
| Prefill 33K / 66K tok (needle) | — | 439 / 312 tok/s, PASS / PASS |
| c1 prose / code decode | 32.7 / 53.3 | 31.9 / 50.8 |
| c4 aggregate | 30.4 | 29.7 |

Long-context prefill now falls with context: the DSA lightning indexer (64 heads x 128 dims a (row, older token)
pair, CUDA cores) is the next target.

## Rounds 3-4: DSA layers and mHC on tensor cores (build md5 e8bf0a26)

Profile of the 1024-row build at 13K context: indexer scores 24%, NCCL all-reduce 19% (NCCL picked the LL protocol),
`dsa_attn` 10%, MoE 12%, `absorb_q` 6%, `mhc_pre_gemv` 6%. Changes (each kernel checked in a standalone harness first):

| Kernel | Harness result | Speed |
|---|---|---|
| `dsa_indexer_scores_mma` (`indexer_mma.cuh`, `idx_test.cu`) | score rel-L2 1.8e-7, selected top-2048 sets identical | 7.4 -> 0.41 ms / 64-row slice at 13K; 36.4 -> 2.2 at 65K |
| `dsa_absorb_q_mma` + `dsa_rope_copy` (`dsa_heads_mma.cuh`, `heads_test.cu`) | bf16 outputs 100% bit-equal | 17.3 -> 0.33 ms at 1024 rows; 134 -> 20 us at 8 rows |
| `dsa_expand_v_mma` | bf16 outputs 100% bit-equal | 3.9 -> 0.16 ms at 1024 rows |
| `mhc_pre_tiled` (rows >= 512) (`mhc_tiled.cuh`, `mhc_test.cu`) | rel-L2 2e-6 (fp32) | 1.23 -> 0.81 ms at 1024 rows |
| Decode FP8G calls (<= 16 rows) pin 1-4 K slices (`cuda_forward.decodeSlices`) | different split sums | see `qmmf_bench.cu` |
| `NCCL_PROTO=Simple` in `start_tensorfold.sh` | — | large prefill all-reduces off the LL protocol |

Fatbins are rebuilt with TensorFold's own flags (`build_fatbins.sh`: `torch_flags` + per-kernel flags; `ops.cu` keeps
`--fmad=false --ftz=false --prec-div/sqrt=true`).

| `suite.py` (quiet lane) | 1024-row MMA build | Round 3 | **Round 4** |
|---|---:|---:|---:|
| Cold 6,662-token prompt | 9.98 s | 9.52 s | **7.58 s** |
| Warm (cached) | 0.73 s | 1.17 s | **0.68 s** |
| Prefill 3.3K / 13K tok/s | 683 / 591 | 675 / 778 | **829 / 889** |
| Prefill 33K / 66K tok/s (needle PASS) | 439 / 312 | 750 / 685 | **857 / 780** |
| c1 prose / code tok/s | 31.9 / 50.8 | 30.1 / 54.2 | **32.3 / 58.7** |
| c4 aggregate tok/s | 29.7 | 30.4 | **31.8** |

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
