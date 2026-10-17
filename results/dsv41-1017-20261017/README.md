# DeepSeek-V4.1-Flash-1017 (EXL3 2.9 bpw) · TensorFold Zig engine · four Sparks, TP-4 — 2026-10-17

The new official release (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) as the third-party 2.9 bpw EXL3 quant
`LibertAIDAI/DeepSeek-V4.1-Flash-1017-EXL3-2.9bpw` (rev `afc7aa0a`), on the **same engine, image and serving settings** as the
DeepSeek row below. That row served the uncensored V4.1 2.9 bpw pack. The bench used the same harnesses, with no changed
inputs or scoring.

**Drop-in, with new derived data.** The config, tokenizer and every tensor name/shape of the old pack are unchanged. The 1017
pack adds 43 `gate.bias_vl` tensors, and its 46 dense MTP matrices are 6 bpw instead of 4. The loader reads K from the trellis
shape, so no code change was needed. Three weight-derived inputs had to be rebuilt from the 1017 base checkpoint:
- **The Engram tables changed in 1017.** The per-rank shards were repacked from base shards 47/48, sha256 `76a05106…` / `9dc51433…`.
- **The image-routing bias changed in 1017.** 34 of its 43 tensors differ from the old V4.1.
- **The prepared layer folders** were written fresh on the first boot (405 s).

Prompt format: the engine's renderer equals 1017's `encoding/encoding.py` on every request shape this bench sends.
Its effort map is already 1017's: low 50, high 75, max 100, default 75.

| Area | DeepSeek V4.1 Flash **1017** (TensorFold) | DeepSeek V4.1 Flash, uncensored pack (TensorFold) | GLM-5.3-Flash FP4 (vLLM) | DeepSeek V4.1 Flash full precision (Venice, hosted) |
| --- | ---: | ---: | ---: | ---: |
| Knowledge, MMLU-200 | 89.5 % (179/200) | 88.5 % | 88.0 % | 90.0 % |
| Math, GSM8K 0–29 | 100 % | 100 % | 100 % | 100 % |
| Coding, 5 tasks | 80 % | 80 % | 80 % | 80 % |
| Instruction following, 20 | 90 % | 90 % | 90 % | 95 % |
| JSON schema / tools / long context to 299K | 100 / 100 / 100 % | 100 / 100 / 100 % | 100 / 100 / 100 % | 100 / 100 / 100 % |
| Summary: facts kept / stale / invented numbers | 100 / 0 / 0 % | 100 / 0 / 0 % | 100 / 0 / 4.2 % | 100 / 0 / 0 % |
| Vision text, 166 strings | 166/166 | 166/166 | 166/166 | – |
| Vision shapes 30 (a3 + a5) / objects counted 23 | 29/30 / 22/23 | – / 22/23 | 28/30 / 0/23 | – |
| Code / prose, 1 stream (tok/s) | 151.8 / 67.3 | 155.4 / 72.0 | 82.0 / 36.5 | – |
| 4 streams, aggregate (tok/s) | 162.4 | 172.1 | 81.2 | – |
| TTFT, short prompt (code / prose) | 0.17 / 0.19 s | 0.17 / 0.14 s | 0.25 s | – |
| Cold prompt 32K / 131K / 200K tokens | 6.2 / 22.8 / 35.7 s | – / – / 36.8 s | 12.3 / 50.8 / 79.4 s | – |

Notes.
- Speed is one sample per cell, as in the other rows. Single-stream prose is −6.5 % and the 4-stream aggregate is −5.6 %
  against the uncensored pack. Earlier rebenches put run-to-run noise at 1–2.5 %, so this gap is probably real but small.
  A likely cause is draft acceptance: the 1017 pack's drafter is a different, higher-bpw quant. Not isolated.
- Cold prefill runs at 5.3–5.8K tokens/s (server clock). The DeepSeek 200K figure came from the 2026-10-14 cold-prompt measurement.
- Vision: spark-vision `read` (refine on, coords auto = pixels for DeepSeek, fresh cache) via `window-vision.py`.
  Text reading is exact. Text box positions are 8–63 px off in pixel units (a1 62.7, a4 20.2), against 1–2 px for GLM. The
  shape positions are 9–19 px off. The prompts and harness are unchanged; the known `-crop` +repage issue is not fixed
  mid-comparison.
- MMLU per item, 1017 vs the uncensored pack: 9 gained, 7 lost (net +2). The Venice full-precision old V4.1 vs the uncensored
  2.9 pack: 7 gained, 4 lost (net +3), plus one IF item (`if-08`).

Files: `qbench-dsv41-1017-zig-20261017.json` (283 requests, 0 transport errors) · `prefill/` (prefill-ladder.py, the same script
as the GLM rows) · `vision/vision-all.json` + `vision-live-run.jsonl` · `venice/` (the hosted full-precision row, qbench
`--venice`, all areas but speed).
