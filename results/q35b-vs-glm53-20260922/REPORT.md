# Qwen3.6-35B-A3B vs GLM-5.3-Flash-EXL3 — Fleet Benchmark (2026-09-22)

Same 33-case graded harness as `aeon27-vs-38flash-20260907` (Phase A) +
`agent_sim.py` (Phase B). 35B ran **co-tenanted with spark-image-lab** on spark2
(VLLM_GMU=0.45); GLM on the dedicated spark1+3+4 TP3 EXL3 lane.
Phase A pinned `reasoning_effort=high` on both (skill law: unpinned runs are not
comparable). flash38v3/glm53exl3 archive numbers are from the Sep-14 quality
canary at effort=**xhigh** — not directly comparable to tonight's high runs.

## Phase A — graded intelligence (pass/total)

| Model | Total | acc-T3 | int-T3 | instr-T3 | Median decode tok/s |
|---|---|---|---|---|---|
| glm53exl3 (tonight, high) | **30/33 (91%)** | 3/3 | 2/4 | 2/2 | ~20 |
| q35b co-tenanted (tonight, high) | **20/33 (61%)** | 0/1 | 2/2 | — | **~81–87 all categories** |
| flash38v3 (Sep 14, xhigh) | 32/33 | 3/3 | 3/4 | 2/2 | 40.3 |
| glm53exl3 (Sep 14, xhigh) | 33/33 | 3/3 | 4/4 | 2/2 | 24.7 |

q35b notes: perfect intelligence-logic T3 (2/2 vs GLM 2/4); weak factual
extraction T2/T3; **one `finish=length` empty-content failure** (b2b-t3) — MoE
thinks past token ceilings; give generous max_tokens in bounded agent loops.

## Phase B — agent_sim (aggregate = total completion tok / wall_clock)

| Run | q35b (spark2, co-tenanted) | glm53exl3 (TP3) | Winner |
|---|---|---|---|
| tool_loop c1 (agent-loop shape) | **77.1 tok/s** | 32.7 tok/s | 35B, 2.4× |
| full c1 aggregate (prefill-heavy) | 8.5 tok/s (TTFT ~4.9s) | 2.1* tok/s (TTFT 0.46s) | see note |
| full c3 aggregate | 7.0 tok/s | **12.8 tok/s** | GLM TP3 prefill |

*full-c1 GLM aggregate is depressed by scenario mix; its per-case decode and
TTFT dominate. Read: **decode speed = 35B (~2.3–4×); long-context prefill =
GLM TP3** (3 nodes of prefill compute vs one GB10).

## Conclusion (fleet roles)

- GLM-5.3-Flash TP3: main agent, checker/reviewer, any long-context lane. ~91%
  graded at ~20 tok/s decode, TTFT 0.46s, strongest compliance.
- Qwen3.6-35B-A3B on spark2: brain/dream/subagent lane — short-context
  structured work where its 77 tok/s tool-loop and 2/2 logic-T3 shine, at 61%
  graded accuracy. Keep max_tokens generous; GLM checks its output.
- Co-tenancy cost: q35b decode ~77 vs MiaAI's 95 dedicated (~19% haircut) —
  acceptable price for sharing the box with the image lab.

## Artifacts
- `results_graded/{q35b,glm53exl3}--*.json` (in `aeon27-vs-38flash-20260907/bench-harness/`)
- `results/q35b-vs-glm53-20260922/*.json` (Phase B raw)
- GBrain: `notes/q35b-vs-glm53-benchmark-2026-09-22`
