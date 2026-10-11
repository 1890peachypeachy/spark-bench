# DeepSeek V4.1 Flash · TensorFold (Zig engine) · 4× Spark: TP=4 + pipelined prefill on RoCE (2026-10-11)

**Result.** The Zig engine — the CUDA Zig port of TensorFold in our four-Spark fork — benched at TP=4 over **RoCE**
(window 8, 2026-10-11), with its pipelined prompt reading on. Against the same build in the same window with the
pipeline off, prompt reading is **+75 % at 32K and +102 % at 131K**, and the cold 154K-token prompt's time to first
token halves (60.5 → 30.0 s). Decode is unchanged by the pipeline (±2 %).

**These are benchmark numbers, not live.** What serves on the cluster is still the Python TensorFold engine (G19 on
RoCE, since 2026-10-07). The Zig migration is pending; this window's numbers are under independent review.

## Window 8 (RoCE): Zig TP=4 + pipelined prefill

Bench: `bench/zig_vs_python.py` in the fork, one boot of the Zig image, cells as labelled. Short cells are 384-token
replies; ×4 figures are the aggregate of four concurrent streams; T0 is greedy, T0.7 sampled (top-k 20). The 32K /
131K labels are workload sizes; the prompts are 37,987 and 154,196 tokens.

| cell | Zig + pipeline (RoCE) | Zig, pipeline off (same window) | Δ (controlled) |
| --- | ---: | ---: | ---: |
| **short decode, cold (one repetition)** | | | |
| code T0 ×1, tok/s | 129.13 | 130.49 | −1.0 % |
| code T0 ×4, aggregate tok/s | 218.33 | 215.24 | +1.4 % |
| code T0.7 ×1, tok/s | 122.04 | 122.01 | +0.0 % |
| code T0.7 ×4, aggregate tok/s | 226.87 | 229.03 | −0.9 % |
| prose T0 ×1, tok/s | 66.24 | 66.58 | −0.5 % |
| prose T0 ×4, aggregate tok/s | 138.17 | 136.56 | +1.2 % |
| prose T0.7 ×1, tok/s | 65.32 | 65.05 | +0.4 % |
| prose T0.7 ×4, aggregate tok/s | 139.08 | 140.70 | −1.2 % |
| **short decode, warm (best / median of 3)** | — not measured in window 8 | | |
| **long prompts (3 cold prefills)** | | | |
| 32K prompt, prompt tok/s best / median | 4,851.5 / 4,842.2 | 2,778.9 / 2,758.7 | **+74.6 %** |
| 131K prompt, prompt tok/s best / median | 5,148.1 / 5,133.5 | 2,548.9 / 2,546.5 | **+102.0 %** |
| time to first token, 32K (best, s) | 7.83 | 13.67 | −42.7 % |
| time to first token, 131K (best, s) | 29.95 | 60.50 | **−50.5 %** |
| decode after the 32K prompt, best tok/s | 96.33 | 94.58 | +1.9 % |
| decode after the 131K prompt, best tok/s | 99.58 | 90.65 | +9.9 % |
| **mix (131K decode beside code ×4)** | — not measured in window 8 | | |
| **mixed windows (131K + 3 code streams, 3 passes)** | | | |
| aggregate, best tok/s | 212.24 | 219.20 | −3.2 % |
| long stream, best tok/s | 34.44 | 40.76 | −15.5 % |

Cells marked "— not measured in window 8" were not run on RoCE in this window (the warm short cells and the mix
cells). They are left empty on purpose: they are not 0, and they are not copied from the NCCL window (window 7),
whose numbers sit in the fork's `docs/ZIG-RESULTS.md`.

Only the middle column pair is a **controlled** comparison: one window, one image, one transport, two boots, the
pipeline switch the only difference. Decode after a long prompt and the mixed-window cells vary a lot between
passes, so treat their deltas as indicative.

## Against the Python engine (cross-session)

The live Python TensorFold engine, benched with the same harness over RoCE on 2026-10-10 (best of 3 **warm**
repetitions; the Zig short figures above are a **cold** single repetition — different sessions, so more than one
variable differs and these are not controlled comparisons):

| cell | Python RoCE (2026-10-10) | Zig + pipeline RoCE (2026-10-11) | Δ |
| --- | ---: | ---: | ---: |
| code T0 ×1, tok/s | 119.08 | 129.13 | +8.4 % |
| code T0 ×4, aggregate tok/s | 207.93 | 218.33 | +5.0 % |
| prose T0 ×1, tok/s | 66.07 | 66.24 | +0.3 % |
| prose T0 ×4, aggregate tok/s | 129.78 | 138.17 | +6.5 % |
| 32K prompt, prompt tok/s | 4,083.6 | 4,851.5 | +18.8 % |
| 131K prompt, prompt tok/s | 4,354.1 | 5,148.1 | +18.2 % |
| time to first token, 154K-token prompt (s) | 35.41 | 29.95 | −15.4 % |

## Replies and failures

- Failed streams: 0 on either boot.
- Greedy short replies, pipeline on vs off: 10 / 16 byte-identical. The difference is expected, not a regression:
  a pipelined prompt carries one rank's arithmetic (world-1 bits) instead of the TP=4 reduction's — the same effect
  Python's pipeline has (the fork's `docs/ZIG-PREFILL-PIPE.md`, "Output parity"). Decode itself is untouched by the
  switch; pipelined and tensor-parallel prompt snapshots never resume each other (a session tag bit).

## What does not map onto this lane's older metrics

- **No 1k–160k depth sweep** was run on the Zig engine, so there is no Zig geometric-mean row for the 2026-10-07
  table, and none is claimed.
- **No `m2bench` steady-state run** (the "4 users, steady ~200 tok/s" figure) exists for Zig.
- Window 8 measured single cold repetitions of the short cells; the warm best-of-3 figures exist only for NCCL
  (window 7, in the fork's `docs/ZIG-RESULTS.md`) and are not quoted here.

## Sources

- Raw runs (forge `~/zigtp4-run/out/zvp/`, mirrored locally): `w8/zig-tp4-roce-pipe/` and
  `w8/zig-tp4-roce-control/` (`cold.json`, `long.json`, `mixwin.json`), summary `w8/compare-control-vs-pipe.w8.md`;
  Python comparison: `python-tp4-roce-live/`.
- Engine and method: the four-Spark fork
  [neko-legends/deepseek-v41-tensorfold-spark](https://github.com/neko-legends/deepseek-v41-tensorfold-spark) at
  `0b60c508` — `docs/ZIG-RESULTS.md` (the TP=4 comparison, windows 4b/7), `docs/ZIG-PREFILL-PIPE.md` (what the
  pipeline is and what its proofs cover), and two charts, both copied to `docs/images/` here:
  `prefill-pipe-comparison-20261011.png` (window 7: Python vs Zig vs Zig + pipeline, NCCL) and
  `engines-dsv41-comparison-20261011.png` (every engine on four Sparks; window 8's short cells marked not measured,
  window 8 marked pending review). Both charts are benchmarks, not live serving numbers.
- Host-side verification of the engine tree: 103/103 build steps, 645/656 tests (11 skipped) — see the fork's
  commit history on `zig-tp4`.
