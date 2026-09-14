# qwen38fn v3 + GLM EXL3 quality canary — 2026-09-14

**Purpose:** local quality gate for the qwen38fn v3/hibrid48 swap (2026-09-13/14) and the
GLM-5.3-Flash-EXL3 default-routing decision. Speed was already verified (c1 +20%, c3 +45%,
TTFT 0.59→0.24s — commit 64543c9); this run measures whether quality moved.

**Method:** the 33-case graded capability battery from `results/aeon27-vs-38flash-20260907/`
(7 categories, deterministic scoring, tiers 1-3), run against BOTH live lanes at
`reasoning_effort=xhigh`, thinking on, temp 0.3. Runner: `run_graded_canary.py`.
Lane ids/hosts verified live from `/v1/models` + sparkDash immediately before the run.

| Lane | base_url | served id |
|---|---|---|
| Spark1+2 TP2 (Qwen3.8-Flash-Next **v3**) | http://100.71.248.116:8000/v1 | qwen3.8-flash-next-spark12 (root: hibrid48) |
| Spark3+4 TP2 (GLM-5.3-Flash-EXL3) | http://100.99.120.29:8888/v1 | GLM-5.3-Flash-EXL3 |

## Results

| Model | Graded score | Anchor comparison |
|---|---|---|
| flash38v3 (v3/hibrid48) | **29/33** | flash38 pre-swap anchor 2026-09-07: 29/33 → **quality-neutral swap** |
| glm53exl3 | **28/33** | q27b anchor 2026-09-11: 28/33 — same league, one point behind v3 |

Per-kind (from per-case JSONs in `results_graded/`):

| model | kind | PASS | FAIL | ERR |
|---|---|---|---|---|
| flash38v3 | accuracy | 12 | 2 | 0 |
| flash38v3 | instruction | 5 | 0 | 0 |
| flash38v3 | intelligence | 12 | 1 | 1 |
| glm53exl3 | accuracy | 13 | 1 | 0 |
| glm53exl3 | instruction | 5 | 0 | 0 |
| glm53exl3 | intelligence | 10 | 4 | 0 |

## Non-passing cases (all 9)

| Case | Lane | Detail |
|---|---|---|
| esc-t3-severity-rank | both | both returned `['1','2','3','4']` vs expected front `['1','2','4']` — consistently hard/strict scorer, fails both models identically |
| mkt-t2-cta-choice | both | both omitted required terms `start`,`free` in CTA pick |
| acc-t2 ×2 | flash38v3 | two arithmetic T2 slips |
| mkt-t2-price-framing | flash38v3 | omitted term `module` |
| esc-t2-refund-call | glm53exl3 | omitted term `replacement` |
| b2b-t2-outreach-prioritize | glm53exl3 | ordered-ranking wrong front |
| b2b-t3-prioritize-revenue | glm53exl3 | ordered-ranking wrong front (dict ids) |
| b2b-t3-prioritize-revenue | flash38v3 | **ERROR — harness artifact**: finish=length; xhigh thinking burned the 1600-token cap before emitting the JSON array |

## Caveats
- flash38v3's error is a token-cap artifact; treated as fail for strictness but noted here.
- Both models fail esc-t3 + mkt-t2-cta identically → scorer strictness / genuinely hard cases, fair comparison.
- glm53exl3 misses cluster in ordered-ranking/exact-term judgment cases (its 4 intelligence-kind fails).
- Single run per case (matches anchor methodology); no warm-up issue at xhigh chat loads.

## Verdict vs. the hold
- **qwen38fn v3 hold: lift.** Quality is identical to the pre-swap anchor (29/33 = 29/33) while
  speed improved +20-45% (commit 64543c9). No reason to keep v4/hibrid47 primary; rollback
  images remain on both nodes.
- **GLM EXL3 default-routing: numbers support parity-within-1-point** (28 vs 29) with 1M-class
  context vs 262k. Decision stays with Victor (per 1:1 section 3); this run is the gate data
  Peachy's hold asked for.
