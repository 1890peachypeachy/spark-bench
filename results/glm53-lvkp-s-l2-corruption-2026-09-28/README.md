# GLM-5.3-Flash LVKP-S-L2 TP4 — output corruption under concurrency (2026-09-28)

**Status:** reproduced, root cause NOT isolated. Lane taken down by Victor; rotated to the
known-good EXL3 TP3 lane.

**Lane:** `glm53-lvkp-s-l2-r{0..3}`, TP4, rank0 on spark3, port 8888, up ~9h at time of report.
Recipe: `1890peachypeachy/GLM-5.3-Flash-4x-DGX-Spark-TP4`, accepted profile **LVKP-S-L2**
(`profiles/current.env`, "Accepted LVKP-S-L2, 2026-09-26").

## Symptom

Agent-facing output degenerates into a repeated-token run mid-response. Victor's report: a
minion triage answer that collapsed into `lock` repeated several hundred times after an
initially coherent paragraph. The corruption is **silent** — HTTP 200, `finish_reason=stop`,
no error in logs. Downstream consumers cannot tell the output is bad.

## Verified

1. **Spec-decode acceptance is collapsed.**
   Lifetime `33,428 accepted / 1,956,828 drafted = 1.7%`. Live window 29.6–33.3%,
   mean acceptance length 1.98. Per-position acceptance:
   `0.551, 0.265, 0.153, 0.015, 0.000, 0.000, 0.000` — positions 5–7 never accept, while
   the spec table still grants `k=7` at batch 1. Reference baseline for DFlash2 on this
   lane is **89.6%**.

2. **`GLM_TARGET_VOCAB_ARGMAX=1` is a no-op — ruled out.**
   Boot log: `glm-target-argmax: steps fast=3 full=557997 reasons={'grammar': 5, 'sampled rows': 557992}`.
   The argmax fast path effectively never fires. Not the corruption source.

3. **Single-stream decode is clean.** `longprobe.py` at prompt sizes 25,516 / 95,746 /
   224,345 tokens: all `finish=stop`, max consecutive token repeat = 3. Not a sampler
   break and not a plain long-context break.

4. **Concurrency reproduces it.** `concprobe.py`, 8 concurrent requests sharing a ~99K-token
   prefix: **1/8 degenerated** with a 16-token consecutive repeat run.

5. **The KV cache corrupted the PROMPT, not just the output.** The probe filler is
   machine-generated and uniform (`REC%04d ... t=<i*7>`). Three independent concurrent
   requests each spontaneously reported the *same* mangled record — ground-truth `t=4424`
   read back as `t=442` and spliced into the following record's fields. That text does not
   exist in the input. Multiple requests reading identical corruption from a shared
   prefix-cache block indicates genuine KV corruption, not model hallucination.
   Prefix cache hit rate on the lane was 83%, so production agent traffic hits this path
   constantly.

## Config audit — NOT a misconfiguration

All 28 `EXTRA_ENV` knobs in `profiles/current.env` match the running container exactly
(`live-env.txt`). Only additions are `GLM_KPOOL_FIX=1` (set by `start.sh:55`, correct) and
`TRITON_CACHE_DIR` (image default). All load-bearing serving flags match: `block-size 2304`,
`KV_BYTES`, `MAX_SEQS=32`, `BATCHED_TOKENS=6912`, spec table `[[1,1,7],[2,2,5],[3,32,3]]`,
`SCHEDULER_CLS=glm_levers_sched.LeversScheduler`, `--linear-backend marlin`, capture sizes,
`kv-cache-dtype fp8_e4m3`.

Four deviations found, none of which plausibly cause token corruption — but all four should
be fixed on the next LVKP bring-up:

| Knob | `current.env` | Live | Impact |
|---|---|---|---|
| `SERVED_NAME` | `GLM-5.3-Flash-FP8` | `GLM-5.3-Flash-EXL3` | Mislabel. `/model` mounts `glm-quant-mix/lossless8` (`modelopt / MIXED_PRECISION`), the correct target per `docs/runtime.md`. Wrong nameplate, right weights. Actively misleading during triage. |
| `PORT` | `8093` | `8888` | `bench/final_sparkdash.py` and `bench/qeval.py` both hardcode 8093 — **the validation suite was never pointed at this container.** |
| `HOST_BIND` | `127.0.0.1` | `0.0.0.0` | Exposure deviation from the recipe's own bind. |
| `GPU_UTIL` | `0.78` | `0.72` | More conservative; not a correctness factor. |

## Root cause gap — the qualification envelope

`docs/validation.md` gates performance and quality at different concurrencies:

- **Decode performance:** c1, c2, c4, c8, c16.
- **Quality / correctness (`qeval` ≥72/75, KLD ~0.03):** **c1 and c4 only** (lines 66, 68).

`docs/history.md` records LVKP-S-L2 passing qeval **75/75 at c1 and c4**, KLD 0.0288366.
Genuinely clean — at c1 and c4. But `README.md` advertises "up to **32** concurrent
sequences" and the spec table covers batch 3–32.

**The corruption reproduces at c8: inside the advertised envelope, outside the
quality-qualified one.** This is not a deployment error; it is an accepted profile whose
correctness was never gated at the concurrency it ships with.

## Leading hypothesis (INFERRED — not proven)

KV corruption in the shared prefix-cache path under batched decode. Suspects, in order:

1. `GLM_KDA_STASH_NOCOPY=1` — aliasing stashed state instead of copying it is a textbook
   source of cross-request corruption once batching interleaves writes.
2. `GLM_L2_PREFETCH*` family — the *only* lever distinguishing LVKP-S-L2 from the
   previously accepted LVKP-S (`docs/history.md`: "adds read-only L2 prefetch to LVKP-S").
3. `GLM_LV_SPLIT_INEXACT=fc` — boot log confirms
   `glm-levers: split: bit-exact check skipped for drafter part(s) ['fc']`. Bit-exactness
   checking is deliberately disabled on the drafter's `fc` layer, and `/draft` also excludes
   `fc` from fp8 quant (`ignored_layers: ["model.fc","fc"]`).

`--block-size 2304` with `fp8_e4m3` KV widens the blast radius of any single corrupt block.

## Cheap bisect ladder for next session

The accepted-profile lineage makes step 1 a single knob, not a search:

1. **`GLM_L2_PREFETCH=0`** → reverts LVKP-S-L2 to the previously accepted LVKP-S. One knob.
2. **Adaptive-k off with NO restart.** `glm_levers_sched.py:187` (`_probe_reload`) re-reads
   `SPEC_PROBE_CONTROL` (`/cache/levers_policy_final.json`) on every mtime change. Setting
   `"enabled": 0` neuters adaptive-k live and is instantly reversible.
3. **Run the recipe's own gate at the failing concurrency:** `qeval.py` at c8 and c16
   (remember to point `--url` at the real port). A sub-72/75 result where c1/c4 pass is the
   recipe failing its own criterion in its own language — reportable upstream.

## Files

- `live-launch-cmd.txt` — full vLLM argv of the running rank-0 container.
- `live-env.txt` — all 95 container env vars (sorted).
- `metrics-snapshot.txt` — `/metrics` spec-decode / prefix-cache / preemption counters.
- `mounts.txt` — weight, draft and overlay bind mounts.
- `lever-and-spec-log.txt` — filtered boot/runtime log: levers, adaptive-k, SpecDecoding.
- `longprobe.py` — single-stream long-context probe (clean at 224K).
- `concprobe.py` — **the reproduction**: c8 shared-prefix, 1/8 degenerate.
- `echo_probe.py` — staged, NOT RUN: verbatim-echo KV corruption diff, sequential vs
  concurrent, to localize corruption against the 2304 block boundary.
- `shared_vs_unique_probe.py` — shared-prefix vs unique-prefix control arm.
  **Produced no verdict**: 5 of 6 rounds completed but the run was killed before its
  end-of-script summary printed, and results were held in memory. Re-run needs incremental
  per-round output. Honest gap, not a finding.
