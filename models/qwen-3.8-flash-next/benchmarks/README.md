# Qwen benchmarks

## Current: fail-closed campaign harness (2026-09-06 tuning campaign)

New harness for the TP4 tuning campaign — results in
[`results/qwen38-tuning-2026-09-06/`](../../../results/qwen38-tuning-2026-09-06/)
(report: `REPORT.md`). All scripts target `http://127.0.0.1:8000`, model
`qwen3.8-flash-next`; run on the serving head, only when benchmarking is
authorized. They generate real inference traffic.

```bash
python3 q38bench.py single --repeats 3 --max-tokens 1400 --out /tmp/arm   # C1 code+prose
python3 q38bench.py agg --repeats 3 --concurrencies 4,8,16 --out /tmp/arm  # C4/8/16 aggregates
python3 q38bench.py sustained --seconds 180 --out /tmp/arm                # stall telemetry
python3 corrcheck.py <label>                                              # correctness gate (exit 3 on any fail)
python3 niah2.py                                                         # tokenizer-calibrated NIAH (19 cases)
python3 soak.py 30                                                       # varied-concurrency soak
bash  run-arm.sh <armname> -- single --repeats 3 --max-tokens 1400       # wraps a bench arm with
                                                                          # metrics snapshots + per-rank
                                                                          # telemetry + contamination gates
```

Differences from the archived first-pass scripts below: `q38bench.py` fails
closed (thread exceptions fail the run; request count, usage, finish reason,
non-empty content and a ≥900-token floor are validated per stream; explicit
timeouts; TTFT / streaming decode / e2e reported separately; raw JSONL +
summary JSON per arm). `niah2.py` calibrates prompt lengths through the
server's `/tokenize` endpoint instead of word-count estimates.

Known harness gap: `tel-collect.sh` PSI column is mangled (tr deleted '0'/'1');
memory/swap/vmstat columns are valid.

## Archived: first-pass scripts (2026-09-05)

Archived as executed; not a finished regression suite. They use
`http://127.0.0.1:8000` and model ID `qwen3.8-flash-next`.

```bash
python3 q38_ss.py
python3 q38_agg.py
python3 niah.py
```

- `q38_ss.py`: greedy repetition smoke, code/prose C1, thinking off/on,
  three runs each, 400-token budgets, first-to-last-delta decode timing.
- `q38_agg.py`: code at 4/8/16 concurrent requests, thinking off,
  1200 tokens per stream, usage tokens divided by wall time.
  Thread exceptions do not reliably fail the parent process: check completed
  request/token totals, not merely its exit code.
- `niah.py`: nine fixed-needle retrieval cases. `ctx` is a word-count estimate,
  not measured token length; `s` is elapsed seconds, not tokens/second.
  This does not certify tokenizer-calibrated long-context correctness.

Save output under a new dated path in `results/`; never overwrite an earlier run.
See [methodology and remaining gates](../nvfp4-tp4/README.md).
Old paths in `scripts/qwen38-first-pass/` remain symlinks to these files.
