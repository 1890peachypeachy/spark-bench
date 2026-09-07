# AEON-27B vs 3.8-Flash — Capability Matrix Harness

Prepared 2026-09-07 as Phase A (intelligence) of the AEON-27B vs 3.8-Flash
benchmark. Phase B (speed) uses `../agent_sim.py`.

## What's here
- `graded_prompts.yaml` — 33 graded cases, 7 categories, difficulty tiers 1-3,
  ground-truth scored. Categories map to real fleet agents:
  - accuracy-arithmetic (5) — order math, refund rate, ad ROAS (peachy/momo)
  - accuracy-extraction (4) — commitments, dates, distractor dates (peachy)
  - intelligence-logic (5) — constraint puzzles, invalid-premise traps (peachy)
  - instruction-following (5) — multi-constraint, JSON schema, format (all)
  - **marketing-copy (5, NEW)** — pandy = all marketing
  - **partnerships-b2b (5, NEW)** — momo = partnerships + B2B
  - **escalation-judgment (4, NEW)** — peachy = escalation/director
- `run_graded.py` — runner. Pins `reasoning_effort=high`, temp 0.3, captures
  latency + completion_tokens. MODELS dict has placeholders for aeon27/flash38.

## New scorer added
`inst_ordered_ranking` — order-aware JSON-array ranking scorer. Used by the
3 ranking cases (b2b-t2, b2b-t3, esc-t3). Plain `contains_all`/`json_contains`
could not enforce rank order; this requires the expected ids as the leading
prefix of the array.

## Run
```bash
python3 run_graded.py aeon27,flash38
# verify served model id from /v1/models first; update MODELS urls/ids
```

## Method notes (from cross-model-capability-benchmarking skill)
- Pin reasoning_effort — unpinned runs are not comparable.
- Recompute every expected value independently before trusting a FAIL
  (2026-08-24: all 3 models were right, scorer was wrong twice).
- Verify constraint puzzles have unique solutions before running.
- Smoke each endpoint first — served ids/ports drift on this fleet.
