# dsv41-tp4: thinking on by default at effort 100 — STAGED, NOT DEPLOYED

Victor 2026-10-17: "Lane wide. But don't take it down yet. I got work happening. Max thinking...
but look online to see what others are saying is better for this model."

## What the profile now generates (build-dsv41-tp4-env.py)
Three deltas from the live profile, nothing else:
- `EXTRA_CONTAINER_ENV` + `SGLANG_DEFAULT_THINKING=1` → SGLang's OpenAI path reads
  `request.chat_template_kwargs.thinking` else this env (serving_chat.py:1409); unset = off,
  which is why every silent request got zero reasoning.
- `EXTRA_CONTAINER_ENV` + `SGLANG_DSV41_REASONING_EFFORT=100` (was a top-level
  `SGLANG_DSV41_REASONING_EFFORT=75`, removed so only one definition exists).
- `DSV41_MAX_NEW_TOKENS=65536` (was 32768): effort 100 spends far more completion tokens and
  the old cap truncated long traces mid-answer.

Revert: `THINK_DEFAULT_EFFORT = "75"` in the builder, rerun, redeploy.

## Why not max, per the sources (the honest version)
- The recipe's own authors measured it: "we run 75 because 100 measured 3x the reasoning tokens
  for about 3 points of tool-eval score" (NVIDIA DGX Spark forum, knapcio/stu.miller). That is
  the same trade we measured locally: 6,240 vs 2,359 reasoning chars, 2,580 vs 1,124 tokens.
- DeepSeek's own eval table is at max (`reasoning_effort=100`), and Artificial Analysis rates the
  max variant #9/120 at 39 on its Intelligence Index — so max is the setting the published numbers
  use, and the setting that benchmarks fairly against them.
- Dissent is real: r/opencodeCLI calls V4.1 Flash "annoyingly overthinking"; HN says 4.1 mostly
  fixed V4's overthinking but "still prefers to plan everything before making a single file change."
- 1017 specifics (sference, 1,440 paired requests, 2026-10-17): the refresh cuts reasoning 20-30%
  and makes the effort dial actually work — budget 1 still solved 29/30 AIME, and effort 25 was
  full marks on both math suites ~20% cheaper. Tool calling unchanged (41/66 BFCL either way).
  Their recommendation for latency-sensitive traffic is effort 25, not 100.

## Verified on the live (unmodified) lane before writing this
- Silent request → `reasoning_content` empty; `thinking: true` → reasoning returned.
- Named tiers all accepted; `low` 2,528 / `medium` 3,194 / `high` 2,378 / `xhigh` 2,223 / `max` 6,240 chars.
- Integer tiers (`25`, `75`, `100`) return HTTP 400: this build validates
  `literal['none','minimal','low','medium','high','xhigh','max']` or a float <= 0.99.
  Floats work (0.5, 0.75, 0.99 tested). The env value 100 is NOT sent over HTTP, so it is unaffected.
- Tools + thinking: works. `max` and `high` both returned tool calls; a tool round-trip does not
  require `reasoning_content` to be echoed back (no 400), so Hermes tool loops are safe.
- Effort 100 on a hard proof: 38 s, 2,507 completion tokens, finish=stop (well under the 65k cap).

## Deploy (when Victor's work is clear)
1. `spark-lane down dsv41-tp4` (this is the untested path — the stop script carries the dsv41-nfs
   guard but has not been run against the 1017 kit).
2. Regenerate the kit profile from the builder and push `.env.tp4` to spark3:/home/spark3/dsv41-4x/.
3. `spark-lane up dsv41-tp4`, then confirm the three env vars are inside the container:
   `docker exec dsv41-head env | grep -E 'SGLANG_DEFAULT_THINKING|REASONING_EFFORT'`.
4. Re-run the canary and a silent (no thinking flag) request: it must now return reasoning.
