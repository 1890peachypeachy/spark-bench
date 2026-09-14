# Qwen3.8-Flash-Next v3 swap results — spark12 lane (spark2 head + spark1 worker), 2026-09-13

**Swap:** v4 image + hibrid47 → v5 image (vLLM 0.29.0) + hibrid48 (NVFP4 output head).
Same consumer identity: http://100.71.248.116:8000/v1 · qwen3.8-flash-next-spark12 · 262144 ctx.

## agent_sim (mixed tool_loop/longdoc/output_mix, ctx 100K, thinking off, median tok/s)

| tag | v4 baseline | v3 warm | speedup | TTFT v4 → v3 |
|---|---|---|---|---|
| C1 | 24.5 (TTFT 0.59s) | **29.4** | **1.20×** | 0.59 → 0.24s |
| C3 | 12.5 | **18.2** | **1.45×** | 0.81 → 0.45s |

Cold-start caveat: first run after boot pays lazy FULL-graph compile + Marlin autotune
(c1 10.4/c3 25.1 on a cold lane). All production numbers above are warm-lane.

## Raw decode sweep (512 max_tokens, temp 0.6, thinking off)

| concurrency | aggregate tok/s | per-stream |
|---|---|---|
| 1 | 63.1 | 63.1 |
| 2 | 103.0 | 51.5 |
| 4 | 155.8 | 39.0 |
| 8 | 226.5 | 28.3 |

Upstream reference (v3 kit, their boxes): c1 peak 107, c32 peak 589. Our boxes carry
fleet deltas (spark1 worker, fabric, seat count) — direction and shape match their ladder.

## Files
- `agent_sim_v4baseline_c{1,3}_20260913.json` + `v4baseline-summary-20260913.json` (pre-swap)
- `agent_sim_v3_c{1,3}_20260913.json` (cold) / `agent_sim_v3_c{1,3}_warm_20260913.json` (production numbers)
- `sweep-decode.py` + `sweep-v3-20260913.json` (raw ceiling)
- Swap runbook + forensics: `bilikaz-qwen38-cluster/docs/swap-runbook-v3-2026-09-13.md`
