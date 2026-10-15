# DeepSeek V4.1 Flash on the four Sparks — baseline per area (2026-10-15)

The DeepSeek-on-Sparks column for the model comparison. Every number is a **percentage** (or a speed in
tok/s) with the harness and the input set named, so a second model measured the same way lands in the same
table. Rulers are never mixed: results from another endpoint (Venice) or another engine are marked, never
averaged in.

Engine at bench time: **TensorFold Zig TP=4 over RoCE on four DGX Sparks**, `POST http://forge:8000/v1` ,
served id `deepseek-v4.1-flash` (root `DeepSeek-V4.1-Flash-TF`), thinking **off**, greedy.

## New in this run (`qbench`, 2026-10-15, 283 requests, 0 transport errors)

Source: `qbench-dsv41-zig-20261015.json` (raw per-item records inside), chart `qbench-dsv41-only-20261015.png`.

| area | what was asked | result | engine time |
|---|---|---:|---:|
| Knowledge / QA | MMLU-200, 0-shot, single A–D letter | **88.5 %** (177/200) | 48 s |
| Reasoning / math | GSM8K test items 0–29, exact final number | **100.0 %** (30/30) | 25 s |
| Coding | 5 tasks, hidden stdlib-unittest tests, run locally | **80.0 %** (4/5) | 6 s |
| Instruction following | 20 items with programmatic checkers (format, counts, forbidden characters, JSON keys) | **90.0 %** (18/20) | 6 s |
| Structured output | 6 JSON-Schema tasks via `response_format: json_schema`, validated client-side | **100.0 %** (6/6) | 2 s |
| Tool use | 8 single-call cases + 2 dependent multi-step chains, schema + argument checks | **100.0 %** (10/10) | 8 s |
| Long context (quality) | passkey at depth 1/3 of 32K / 131K / 299K-token logs | **100.0 %** (3/3) | 67 s |
| Summarization fidelity | synthetic 20-fact log (7.4K tokens) → compact summary | facts kept **100 %** (20/20) · stale returned **0 %** · invented numbers **0 %** | 6 s |

Speed, same frozen prompts, 320-token outputs (source: the `speed` area of the same result file):

| cell | decode tok/s | TTFT |
|---|---:|---:|
| code, 1 stream | **153.8** | 0.17 s |
| prose, 1 stream | **70.2** | 0.15 s |
| 4 streams, aggregate | **170.2** | 0.17–0.50 s |

## Worker-role suite on the Sparks (2026-10-15, 2 runs/cell, judge `z-ai-glm-5-3`, 0.16 DIEM)

Harness: `nest/scripts/model-role-bench/run_bench.py --candidate-base http://forge:8000/v1 --candidate-no-thinking`
(same fixtures as the 2026-09-01 Venice sweep; judge never from the scored model's family).
Summary copied to `rolebench-dsv41-sparks-2026-10-15-summary.json`; report
`nest/scripts/model-role-bench/results/2026-10-15-dsv41-sparks.md`.

| role | score | latency/cell | notes |
|---|---:|---:|---|
| builder (3 specs × 2) | **100.0 %** | 10.3 s | 0 failures |
| reviewer (3 diffs × 2) | **100 %** found | 6.9 s | 0 false positives |
| synthesis (40K-token bundle × 2) | recall **100 %** | 48.2 s | 1 hallucination flag |
| instruction following (6 tasks × 2) | **4.67 / 5** | 11.2 s | 0 English violations |
| cheap batch | **100.0 %** | 8.7 s | 0 failures |

## Already measured before this run (do not rerun — see `../RERUN.md` §3)

| area | result | harness / date | engine |
|---|---|---|---|
| MMLU-200 | 87.5 % (175/200) | fork `bench/quality.py mmlu`, 2026-10-05 campaign | TensorFold (Python engine) |
| MMLU-200, kit baseline | 87.5 % | MiaAI vLLM kit, 2026-10-01 | vLLM kit |
| Needle gates 32K / 400K / 1M | pass | SGLang lane gates, 2026-09-14 | SGLang |
| Structured output (6 schemas × thinking off/on, drafted = serial = batched) | pass | `structured-roce.w4b.json`, 2026-10-11 | Zig TP=4 |
| Tool roundtrip (3/3 clean) | pass | vLLM lane gates, 2026-09-13 | vLLM |
| Compaction fidelity on a real 161K-token corpus | facts 40/49 (81.6 %) thinking on, 39/49 (79.6 %) thinking off; threads 4/7 and 2/7; 5 invented either way | `nekocompact/eval/compaction-ab-2026-09-10` addendum, 2026-09-11 | then-live Sparks serve |
| Vision — exact text, positions, counts, colour | counts 39/23/11 **exact**; text 28/28, 48/48, 42/42 … (best arm); baseline full-frame read invented **41** strings, best arm ≈0; measured-hex ΔE 0.0 on flat fills | `nest/tmp/spark-vision`, 2026-10-15 | Zig TP=4 |
| Speed — cold 199,713-token prompt | TTFT **36.8 s** (≈5,400 prompt tok/s), `cached_tokens: 0`; 332,847 tokens → 66.6 s | `spark-bench` README / journal, 2026-10-14 | Zig TP=4 |
| Speed — lane cells (warm best-of-3 / cold 1 rep) | code 129 tok/s (×4 218), prose 66 (×4 138); cold 154K prompt 30.0 s | `artifacts/tensorfold-v41-zig-20261011/REPORT.md` | Zig TP=4 |
| Worker-role suite on Sparks | builder 0.99 (11.7 s), reviewer 1.0 (4.1 s), synthesis 0.96 (56.8 s), IF 4.0 (9.5 s), batch 1.0 | qwen3.8-flash-next, 2026-09-05 — **a different model**, shown only to prove the harness repeats | vLLM world |

## Not measured on the Sparks (and where the comparable number lives)

| area | DeepSeek-on-Venice number | note |
|---|---|---|
| synthesis via the Venice harness | 0.00 (reasoning burn, 0 content) | on Sparks with thinking off it is 100 % recall — the harness difference, not the model |
| IF via the Venice harness | 3.17 / 5 | Sparks: 4.67 / 5 |
| compaction with a private corpus on the Zig engine | facts 40/49 (81.6 %) thinking on / 39/49 thinking off | the 2026-09-11 arms ran on the then-live serve; a Zig-engine rerun needs a copied arm script |
