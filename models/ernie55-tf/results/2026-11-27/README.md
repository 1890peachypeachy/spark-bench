# ERNIE-5.5-Flash-Preview · TensorFold native TP4 · 4× DGX Spark: hill-climb, 2026-11-27

Engine: fork `1890peachypeachy/TensorFold` `feat/ernie55` @ `0c09727` (Wave-4; on spark3 `bb1c1a0`), plus
experiment branch `exp/ernie55-cost-graph-knobs`. Every new knob is env-gated, so the default behaviour is unchanged.
Harness: `scripts/bench/bench.py` from the ERNIE recipe repo (thinking on, T 0.6, top_p 0.95, 384-token replies,
unique prompts; c = 1, 2, 4, 8, 16, two waves each). Plus `w3_bench.py` gates: 17×23, parallel tools, 66K needle,
warm 66K+450 / +3312.

## Runs (aggregate tok/s)
| run | what | c1 | c2 | c4 | c8 | c16 | 9K prefill |
|---|---|---|---|---|---|---|---|
| base-w4 | production, from the Mac | 49.2 | 49.8 | 76.5 | 105.3 | 102.4 | 1,531 |
| e0-pricelog | production + `TF_SHARED_PRICE_LOG=1` | 48.3 | 50.1 | 76.5 | 101.4 | 106.9 | 1,578 |
| e1a-graphs64 | shared-graph cache 8 → 64 | 45.0* | **56.9** | 75.8 | **78.3** | **82.7** | 1,538 |
| e2a-g64-max2 | graphs only ≤2 streams | — | — | — | — | — | contaminated by live agent traffic, discarded |

\* c1 does not use the shared-graph path, so 45.0 vs 48.3 is prompt-content noise. Per-stream medians: 49.7 vs 48.8.

e0 long gates: cold 66K 1,510 tok/s (needle 3/3); warm 66K+450 0.60 s; warm 66K+3312 2.58 s (1,324 new tok/s).

## Finding 1: the shared-verify cost table is 1.2–1.9× too cheap
`hillclimb/e0/price_fit.json`, 1,929 priced shared rounds:

| total rows | 5 | 7 | 9 | 12 | 16 | 24 | 32 | 40–58 |
|---|---|---|---|---|---|---|---|---|
| measured median ms | 53.0 | 58.9 | 66.1 | 83.3 | 93.7 | 121.6 | 141.0 | ~140–155 |
| `gb10_shared_costs` ms | 44 | 48 | 52.3 | 56 | 60 | 67 | 75 | 83–101 |

Above ~32 rows the cost plateaus at ~145–155 ms. By then nearly every routed expert is read once: 512 × 6.7 MB / 4 ranks ×
42 layers ≈ 36 GB per rank, which takes ~145 ms at about 250 GB/s. Mia's DSV4.1 TP4 recipe found the same defect ("priced rows at half their cost →
over-drafted at 4–16 streams") and fixed it with a measured `TF_DS_ROUND_MS`. New knob: `TF_ERNIE55_SHARED_MS`.

## Finding 2: CUDA graphs mostly miss at c≥3
The shared verify key is (streams, slots[], rows-per-stream[], context buckets[]). Mixed draft depths make most rounds new
keys. Counts from `TF_ERNIE55_GRAPH_STATS=1` with a 64-entry cache:
- c2: 68% graph launches, 21% eager, 11% captures.
- c4+: 30% graph launches, 51% eager, 19% captures. Each captured graph is launched only ~1.6× before eviction.

A capture costs far more than an eager forward, so the larger cache (more keys reach their second sighting) loses 23% at
c8/c16 while gaining 14% at c2. New knobs: `TF_ERNIE55_SHARED_GRAPHS`, `TF_ERNIE55_CAPTURE_AFTER`,
`TF_ERNIE55_GRAPH_MAX_PARTS`.

The structural fix already exists upstream. TensorFold's own `deepseek_v41` family (`batch.zig`, `rowtab.zig`,
`graphs.zig`) runs "batched decode windows over several slots … rows padded to a bucket; eager and graphed run the same
program keyed by (bucket rows, context bucket)". Porting that row-table and bucketed-graph design to ERNIE's shared verify
is the main c2–c8 lever.

## Finding 3: c16 is bounded by KV memory
At boot: "8 streams at once, 3.58 GiB each at a 262144-token window, of 41.2 GiB left after a 12.2 GiB reserve", with
`max_parts = 8`. Options, from the Mia repos:
- mixed slot sizes (pico-dgx-ds4: 4 × 1M + 12 × 128K, smallest-fit admission);
- a shared growable KV pool (GLM-DERISKED `SHARED_KV`, `TF_GLM_SEQ_GROW`);
- FP8 MLA KV (lossy);
- a smaller reserve (risk of OOM wedges).

## Measurement notes
- The lane is shared with live agents. `hillclimb/idle_chain.sh` runs experiments only after 20 minutes of zero traffic,
  checks each run's request count (a clean SKIP_LONG run finishes exactly 71 requests), re-runs contaminated ones and
  restores production at the end.
- Per Mia's GLM campaign (`GLM-5.3-Flash-DGX-Sparks-1104/docs/speed/RESULTS.md`): random-content tok/s swings ~12% while
  rounds/s is stable to 0.5%, and host drift (~1.5%) exceeds small effects. Effects under ~5% need fixed-prompt greedy
  ABA runs.
