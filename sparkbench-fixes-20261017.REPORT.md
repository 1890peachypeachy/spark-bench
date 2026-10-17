# spark-bench fixes (branch fixes-qbench-chart-20261017)

## 1. qbench /tokenize calibration (bench/qbench.py)
Root cause: `--base-url` ends in `/v1`, and vLLM serves `/tokenize` at the server root, so `<base>/v1/tokenize` 404'd;
`tokenize()` swallowed the error and returned None, and `area_longctx` used `or 0`, skipping calibration silently.
Fix: `tokenize()` tries `<base>` then the root with `/v1` stripped, each with a messages body then a prompt body, and accepts
`count` or `len(tokens)`. New `tokenize_or_die()` raises a clear RuntimeError if nothing answers; `area_longctx` uses it and
also raises if the calibrated size is >5% off the target.
Before/after (fake server answering only `/tokenize`, base `.../v1`): old qbench -> None; new qbench -> 123.
Dead endpoint: new `tokenize_or_die` raises RuntimeError. Tests: `python3 bench/test_qbench_timing.py` -> 4 tests OK.

## 2. chart.py subtitle over legend
Legend sat at y=56-67 and the subtitle baseline at y=58. `pad_t` 76 -> 92 moves the legend below the subtitle. Also found the
legend entries overlapped each other (fixed 220px spacing, long tags); spacing now follows label length.
Evidence: results/sparkbench-fixes-20261017/before.png, after.png (same two qbench result files).
