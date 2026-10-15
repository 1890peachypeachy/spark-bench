# RERUN — benchmarking a new engine/model on the four Sparks

**The rule (Jun, standing):** bench a model once; never rerun a sweep that already exists. A comparison with a
changed variable is not a comparison — inputs, prompts, params and scoring must be identical across models.
Scores go in as percentages, and nothing that may be published carries pricing.

So this file is two things: (1) **what is already benched for DeepSeek V4.1 Flash on the Sparks** (do not rerun),
and (2) **the exact command for everything else**, written so the whole thing can be pointed at a different
model id/endpoint — e.g. Nemotron on TensorFold — and the numbers compare directly.

---

## 1. The one model-agnostic runner: `bench/qbench.py`

```bash
cd /home/jun/git/spark-bench
python3 bench/qbench.py --base-url http://forge:8000/v1 --model deepseek-v4.1-flash \
    --areas all --workers 4 --tag dsv41-zig-20261015 \
    --out results/qbench-dsv41-zig-20261015.json
```

* Endpoint and model id are arguments; thinking is **off** by default (`--thinking` to turn it on), max 4 requests
  in flight (`--workers`, the tailnet limit). Progress and results are written incrementally, so a long run is
  never lost. Transport errors are retried once; an area that fails is recorded as an error, not a crash.
* Areas: `speed, mmlu, math, coding, if, json, tools, longctx, summary` (≈290 requests, ~3 min wall on the
  DeepSeek Zig engine; the 299K-token passkey is the slow one).
* Frozen inputs live in `bench/inputs/`, built by `bench/mkfixtures.py` (deterministic, stdlib only). **Never
  edit a built input in place** — edit the generator, rebuild, and say so in the commit. sha256 at build time
  (2026-10-15):

| input | bytes | sha256 (first 16) | what |
|---|---:|---|---|
| `mmlu200.jsonl` | 93623 | `9afacd0317bd759d` | MMLU-200, copied from `deepseek-v41-tensorfold-spark/bench/data/` |
| `math.jsonl` | 8637 | `901dbf3069073c63` | GSM8K test split, first 30 items, one fetch, frozen |
| `if.jsonl` | 2986 | `fb1d9529e0fb770a` | 20 instruction-following items, programmatic checkers |
| `json_tasks.json` | 3134 | `071d53eeb779d95c` | 6 JSON-Schema tasks |
| `tool_tasks.json` | 4822 | `5ca70f2fc6ed23ff` | 8 tool-call cases + 2 dependent chains |
| `coding.json` | 3843 | `b5fb2a2cf573cf19` | 5 coding tasks + hidden stdlib-unittest tests |
| `longctx.json` | 388 | `ad186d6339747390` | passkey sizes (32K/131K/299K), depth 1/3 |
| `summary.json` | 38657 | `1b385e9dfc58e461` | synthetic log: 20 planted facts, 5 superseded, 1 buried detail |

  Rebuild: `python3 bench/mkfixtures.py --out bench/inputs` (needs network once for the GSM8K slice).

### Chart from two result sets

```bash
python3 bench/chart.py results/qbench-dsv41-zig-20261015.json results/qbench-<nemotron>.json \
    --png results/qbench-compare.png --svg results/qbench-compare.svg --md results/qbench-compare.md
```

An SVG is written by hand (no plotting library) and converted with `rsvg-convert`/ImageMagick; a missing series
is simply not drawn. Percentages only, no pricing.

---

## 2. Suites that live elsewhere (already frozen — reuse, do not rewrite)

| area | harness | exact command (retargeted by argument) |
|---|---|---|
| worker roles (builder / reviewer / synthesis / IF / batch) | `nest/scripts/model-role-bench/run_bench.py` | `cd /home/jun/nest/scripts/model-role-bench && python3 run_bench.py --candidate-base http://forge:8000/v1 --candidate-no-thinking --models <served-id> --date <date>-<tag> --roles builder,reviewer,synthesis,if,batch --runs 2 --workers 4 --budget 15 --no-allowlist` |
| long-context **speed** (cold prefill ladder, C1/C4 decode) | fork `deepseek-v41-tensorfold-spark/bench/` (`m2bench`, `stress.py`, `soak.py`) + `spark-bench/scripts/` lane harnesses | see `spark-bench/scripts/README-bench.md` and the fork's `docs/BENCHMARKS.md`; the lane harnesses are lane-specific (hardcoded host/port) — the model-agnostic speed numbers come from `qbench --areas speed` |
| structured output + tools (xgrammar gates) | fork `bench/structured.py`, `bench/tooleval/chains.py` | `python3 bench/structured.py --base http://forge:8000 --model <id> --out R.json` · `python3 bench/tooleval/chains.py --base http://forge:8000 --model <id> --mode off --out R.json` |
| MMLU-200 + needle, through the serving path | fork `bench/quality.py` | `python3 bench/quality.py mmlu --base http://forge:8000 --model <id> --data bench/data/mmlu200.jsonl --out R.json` · `... needle --sizes 32768,131072,299000 --out N.json` |
| compaction / summarization (private corpus) | `eva-core/extensions/nekocompact/eval/compaction-ab-2026-09-10/` | one arm per script (`bench-sparks.mjs` for the Sparks serve); a **new model needs a copied script with its own model id** — the file hardcodes `deepseek-v4.1-flash`. Private corpus, never committed. |
| long-context quality (LCD degradation curve) | `eva-core/docs/benchmarks/2026-09-08-long-context-degradation/run-arm.mjs` | endpoint/key resolved from `~/.pi/agent/models.json`; the sparks arm today is `results-sparks-auto.json` (**qwen3.8-flash-next on the old vLLM world**, not DeepSeek) |
| vision | `nest/scripts/spark-vision.py` (+ the bench harness in `nest/tmp/spark-vision/`) | now model-agnostic: `python3 nest/scripts/spark-vision.py --url http://forge:8000/v1 --model <id> read IMG` (defaults unchanged) |

Judge routing rules still apply: a model is never judged by its own family, and `synthesis`/`batch` slots are
private-tier only.

---

## 3. Already benched for DeepSeek-on-Sparks — do not rerun

| area | status | where | retargetable? |
|---|---|---|---|
| speed: decode (code/prose), C1–C4, cold prefill, TTFT, RoCE/NCCL controls, Zig vs Python | **done**, many windows | `spark-bench/artifacts/`, `results/`, `models/deepseek-v4.1-flash/JOURNAL.md`; fork `docs/ZIG-RESULTS.md` | lane harnesses are lane-specific; `qbench --areas speed` is the model-agnostic re-measure |
| speed: cold 200K/332K-token prompt on the live Zig engine (2026-10-14) | **done** | `spark-bench` README + `models/deepseek-v4.1-flash/JOURNAL.md` | yes (cold prefill client) |
| long context: depth sweep 1K–160K, needle gates 32K/400K/1M | **done** (SGLang lane + TensorFold campaign) | `artifacts/tensorfold-v41-depth-20261001/`, `artifacts/dsv41-sglang-20260914/gates/` | yes, `quality.py needle` |
| tool use / JSON: tool roundtrip, tool-bearing decode bench | **done** (vLLM/SGLang lanes) | `artifacts/dsv41-vllm-20260910/ab-unc-20260913/g2-toolroundtrip.log`, `artifacts/dsv41-sglang-20260914/toolbench-*.json`, `scripts/toolbench.py` | yes via `--base/--model` edits (script is hardcoded today) |
| structured output (xgrammar schemas) on the Zig TP4 engine | **done** 2026-10-11 | `nest/tmp/zvp-20261011/structured-roce.w4b.json` (pass) | yes, fork `structured.py` |
| summarization / compaction (thinking on and off, on the then-live Sparks serve, 2026-09-11) | **done** | `eva-core/extensions/nekocompact/eval/compaction-ab-2026-09-10/REPORT.md` addendum | needs a copied script per model id |
| vision (token budget, glyph/CER curves, crops, counts, colour, bboxes) | **done** 2026-10-15 | `nest/tmp/spark-vision/LOG.md`, `nest/tmp/worker-handoffs/spark-vision-20261015.REPORT.md` | yes, `spark-vision.py --url/--model` |
| worker-role suite on Sparks | **done for qwen3.8-flash-next** (2026-09-05), **new for DeepSeek** (`results/2026-10-15-dsv41-sparks/`) | `eva-core/docs/benchmarks/2026-09-05-qwen38-nvfp4-sparks-role-bench.md`, role-bench results dir | yes, `--candidate-base` |
| quality areas with no Sparks result before 2026-10-15: MMLU/knowledge, GSM8K math, coding (hidden tests), IF, JSON schema, tool chains, passkey long context, compaction fidelity | **NEW — `qbench` ran 2026-10-15** | `results/qbench-dsv41-zig-20261015.json` + `.md` + chart | yes, by argument |

DeepSeek numbers measured on **Venice** (not Sparks) — comparable only within their own harness, never mixed
with the Sparks column: role suite `nest/scripts/model-role-bench/results/2026-09-01/`,
`2026-09-10/` (synthesis), `2026-10-14-dsv41-flash-uncensored/`; compaction addenda
`ADDENDUM-dsv41f{high,max}.md`; vision `vision-bench` (Venice `deepseek-v4-1-flash`, 11/15 detection).

---

## 4. Order for a new model (e.g. Nemotron on TensorFold)

1. Confirm the served id: `curl -s http://forge:8000/v1/models`.
2. `qbench` (all areas) → `results/qbench-<tag>.json` (~3 min).
3. Worker-role suite against the same endpoint (`--candidate-base`), same fixtures, judge must be another
   family (~10 min; cells are the slow part).
4. Speed: `qbench --areas speed` for a like-for-like number; only then the lane harnesses if you need the
   controlled A/B rulers (they are engine-specific).
5. `chart.py` with the DeepSeek result first, the new model second → one PNG.
6. Anything with a changed variable (engine, thinking mode, quantization, prompt bytes) is its own labelled
   column — never folded into an existing comparison.
