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

Known gaps (not fixed): streams are served one at a time per round (single-sequence `Engine.cur`), so concurrency
does not scale; prefill is ~5x slower than vLLM (256-row passes, no prompt cache); `libtfgrammar.so` missing →
structured output / `tool_choice=required` return HTTP 400; no API key on a 0.0.0.0 bind (same as other lanes on the fabric).
Not registered in `ops/spark-lane` yet (the `ernie55-tp4` id is the vLLM lane); `spark-lane status` will not see it.
