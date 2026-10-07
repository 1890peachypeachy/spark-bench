---
type: note
title: jspark3 v2.0.2 LIVE on GLM-5.3 TP3 — cutover, acceptance, and a shared-lane prefill finding (2026-10-07)
tags:
  - dgx-spark
  - glm53
  - jspark3
  - tensorfold
  - lane-cutover
  - benchmarking
---

# jspark3 v2.0.2 live on GLM-5.3 TP3

Cutover executed 2026-10-07 ~04:03Z on Victor's approval, replacing jspark3
v2.0.1 (which had itself replaced Mia's TensorFold recipe on 2026-10-04).

## Lane identity (live-verified, not recalled)

- Containers `jspark3-rank0/1/2` on spark3 (rank 0) / spark1 / spark4
- Checkout `/var/tmp/jspark3/jspark3-v202`, `DATA=/var/tmp/jspark3/data-v202`
- Release v2.0.2, base weights, drafter `dflash2`, session tier `disk`
- Endpoint `http://100.99.120.29:8888/v1`, served id `GLM-5.3-Flash-EXL3`
- v2.0.1 checkout, data and containers retained for rollback

## Cutover sequence that worked

1. Gated on idle (`num_requests_running`/`waiting` = 0), then stopped ranks 2, 1, 0
2. Confirmed no compute apps on any GPU; MemFree recovered to ~110 GiB/node
3. `scripts/pull-image.sh` — see deviation below
4. `scripts/build-wheel.sh` on all three; content sha256 `35b0ccd7ee67e4f0a1b22db95566c8924425045552a8e08b3ca49454d3571e60` matched the pin on every node
5. `scripts/split.sh --verify-only` — all three weight thirds verified
6. `scripts/preflight.py`, then `serve.sh` on rank 2, rank 1, rank 0
7. `wait-ready.sh`: ready in ~1 min

## Staging shortcuts that are safe (verified, reusable)

`wheels.lock` and both weight manifests are byte-identical v2.0.1 -> v2.0.2, and
the base NGC image digest is unchanged. Therefore:

- Weights can be SYMLINKED from the v2.0.1 data dir instead of re-copied
  (60 GB/node saved). `split.sh --verify-only` passed against the shipped
  manifests on all three ranks, so the reuse is sound.
- No image pull from the network is needed; layers are already present.
- Only `config/serve.conf`/`serve.env` changed (session namespace). Everything
  else carries over from v2.0.1.

Consequence: the build/split/verify steps are the only ones that need the lane
down. Checkout, symlinks, wheels and config can be staged while v2.0.1 serves.

## Deviations from the upstream recipe (both pre-existing, both benign)

1. **`PREV_IFACE` preflight FAIL on all three nodes.** `enp1s0f0np0` is
   NO-CARRIER fleet-wide because our fabric is the switched MikroTik CRS504,
   not the recipe's direct-cable ring. Only `enp1s0f1np1` (`rocep1s0f1`) is
   cabled. The lane serves correctly on this topology. Any OTHER preflight FAIL
   blocks a cutover.
2. **`build-wheel.sh` does not read `cluster.env`.** Our `IMAGE=` override
   (local tag `jspark3-glm53:26.08-py3`) lives in `cluster.env`, which only
   `serve.sh` reads, so the build saw the unpulled NGC digest reference and
   refused. Fix: run `scripts/pull-image.sh` once per node. It completes in
   ~1 s because the layers are already local under our tag, and it creates the
   digest reference the build needs. The local tag's image ID already equals
   `pins.env` `IMAGE_ID` (`15b8de8baabe...`).
3. **`smoke.sh` `models` check FAILs** because of our deliberate `SERVE_NAME`
   pin. Expected; 5/6 is a pass for this lane.

## Acceptance results

| Check | Result |
|---|---|
| `smoke.sh` | 5/6 (only the `SERVE_NAME` `models` FAIL) |
| `cache-check.py` | 3/3 (`cache_salt` SKIP — not enabled) |
| `prefill-check.py` | 2/2 — 1728 tok/s @8K, 1831 tok/s @32K (v2.0.1 baseline: 1745 / 1846, no regression) |
| GIF frame-zero (v2.0.2 fix) | PASS — HTTP 200, frame zero read correctly (was HTTP 400) |
| Rolling-image reuse (v2.0.2 fix) | PASS — 2485 tokens resumed, `miss=none`, `evidence=hit` |

Scripts for the two release-specific checks are committed at
`spark-bench/models/glm-5.3-flash/jspark3/checks/`.

## Rolling-image reuse: the trap that cost two false negatives

The headline fix appears BROKEN unless the fixture is right. Two mistakes made
in sequence, both worth remembering:

1. **Rebuilding the conversation per probe.** Sending the 8-, 9- and 10-image
   states as three independent requests forks at message 1 every time
   (`session_miss_reason=fork`, `evidence=shared-prefix-divergence`), so reuse
   is 0 by construction. A rolling conversation must be sent turn by turn.
2. **Keeping a trailing question message.** A question appended after the image
   turns MOVES every turn, so the shared prefix diverges where it sat. Result:
   a flat `cached=9` (the system prompt only) on every turn, which looks like
   total failure. Real agent clients are append-only: one user message (image +
   its question), then the assistant's real reply.

With an append-only chain, pre-rotation reuse climbs 478 -> 2010 tokens
(`src=memory`, `miss=none`). The first rotated turn can still collapse to
`cached=9`/`fork`: upstream states the image-boundary checkpoint must be
durably SAVED before a later rotation can reuse it, and "continuous traffic can
still skip optional saves under the bounded writer policy". Re-probing the same
rotated state returned `cached=2485`, `miss=none`, `evidence=hit`. So a rapid
first pass through rotation outruns the save; once the checkpoint is durable,
reuse engages. **Do not declare the rotation fix broken from a single fast pass.**

Also: `prompt_tokens` EXCLUDES image tokens on this engine (a 1-image request
reports 35). It is not a proxy for prompt size. `tensorfold.cached` is the reuse
signal (known issue 15: it is not reported as `prompt_tokens_details.cached_tokens`).

## Shared-lane finding: idle-gated benchmarks are not possible during the day

~15 Hermes profiles route to this endpoint (astrid, brush, crash, didi, eden,
freud, jarvis, librarian, momo, ollie, pandy, peachy, sila, spark,
therapyconsult). Sampled over 60 s the lane was **0% idle** — a persistent
1 running + 1 waiting.

**Do NOT read `vllm:num_requests_running=1` as "the lane serializes".** That
gauge is a vLLM-compatibility shim. The engine's own gauge,
`tensorfold:inflight`, read **3** at the same instant the shim said
`running=1, waiting=2`. Concurrency is configured (`SERVE_PARALLEL=8`,
`TF_GLM_FAIR_SCHED=1`) and verified from the client side: 3 barrier-released
streams all began decoding within 10 ms of each other, overlapped pairwise
(2.86 / 2.86 / 7.04 s) and gave a concurrency factor of **2.37x** on 3 streams
(1.0 would be serialized). Peak gauges during that run reached
`inflight=6, running=5, waiting=5`, so `running` is not pinned at 1 either.
The steady 1-running/1-waiting simply reflects our real demand shape: the fleet
sends FEW but VERY LARGE requests (69 requests / ~1.24M prompt tokens in ~30
min), not many small ones.

The cost is therefore not a concurrency cap but **head-of-line prefill
blocking**: those same 3 test streams each waited **23.2 s for their first
token** while a large prefill owned the GPUs. Concurrency cannot rescue a lane
where one ~155K-token prefill monopolizes the step loop for ~110 s.

A streamed decode benchmark run against it returned 8-10 tok/s with TTFT of
49-101 s. Those numbers are pure queueing artefact and must NOT be recorded as
lane performance. The idle gate caught it; without the gate they would have
looked like a catastrophic regression. **The open "jspark3 decode vs Mia
baseline" item still cannot be answered during active hours** — it needs a
genuinely quiet window or a drained lane.

Better evidence for a shared lane is the rank-0 engine log, which reports real
production prefill/resume/decode per request. Audit script committed at
`checks/lane-prefill-resume-audit.py`.

### Production numbers from the log (first ~25 min after cutover, 62 requests)

- Decode by reply length (median / max tok/s): 0-50 -> 51.8 / 130.4;
  50-200 -> 48.3 / 89.0; 200-600 -> 20.7 / 58.6; 600+ -> 45.1 / 79.1
- Resume rate 63% (39/62); small sessions resume well
- **3 agent requests with ~155K-token contexts arrived with `resumed=0`,**
  each costing 102-115 s of prefill at ~1400 tok/s. Three requests out of 62
  owned **74% of all prefill GPU time** — this is the head-of-line blocker that
  produces the permanent 1-running/1-waiting backlog, and it starves every
  other profile on the lane.

### ROOT CAUSE (found 2026-10-07, supersedes the warm-up hypothesis)

The cold big-context prefills are **NOT** post-cutover warm-up. Reading
`session_miss_reason` on each big request over a 90-minute window:

| sid | prompt | resumed | prefill | miss / evidence |
|---|---:|---:|---:|---|
| 53 | 156616 | 0 | 101.9s | cold / none / unknown |
| 57 | 154540 | 0 | 112.1s | cold / none / unknown |
| 60 | 156996 | 0 | 114.7s | **store-evicted / observed-prior-prompt** |
| 64 | 154872 | 0 | 90.0s | store-evicted / observed-prior-prompt |
| 65 | 157889 | 0 | 92.6s | store-evicted / observed-prior-prompt |
| 66 | 155273 | 0 | 90.7s | store-evicted / observed-prior-prompt |
| 67 | 158380 | 0 | 92.7s | store-evicted / observed-prior-prompt |
| 68 | 156912 | 0 | 106.3s | store-evicted / observed-prior-prompt |
| 70 | 158907 | 0 | 116.5s | store-evicted / observed-prior-prompt |
| 75 | 157255 | 0 | 92.4s | store-evicted / observed-prior-prompt |

Only the first two were genuine cold starts. Every subsequent one is
`store-evicted` with evidence `observed-prior-prompt`: **the engine saw the
conversation's prior prompt and had lost the stored anchor.** `dropped_anchors`
climbs monotonically (59 -> 82 -> 83 observed).

Upstream's own `release/v2.0.2/ROOTCAUSE.md` and `LIMITATIONS.md` explain why:

> The existing bounded writer refuses another optional snapshot batch while a
> write is pending. Its **quiet gate requires 0.5 seconds without model work or
> request preparation.** Continuous traffic without that opportunity can
> therefore skip optional disk saves. [...] This does not promise lossless
> checkpoint persistence under sustained backpressure. **The two fixes do not
> change that writer policy.**

So this is a **self-reinforcing trap**, not a transient:

1. Our agents RESUME long conversations (~155K contexts) rather than starting
   new ones (Victor, 2026-10-07 — this is the demand shape that makes the
   checkpoint store load-bearing in the first place).
2. Resuming requires a persisted anchor.
3. The writer only persists during >=0.5 s of true quiet.
4. The lane is 0% idle (~15 profiles), so that quiet never arrives.
5. Anchors are dropped -> next turn reports `store-evicted` -> full ~155K
   re-prefill at 90-116 s.
6. That re-prefill keeps the lane busy, which prevents the quiet gate, which
   prevents checkpointing. Loop closes.

**v2.0.2 does not fix this** — upstream states the fixes do not touch the writer
policy. The upgrade's GIF and image-rotation fixes are real and verified; this is
a separate, pre-existing limitation that our specific load pattern maximizes.

`TF_GLM_SESSION_CHECKPOINTS=0` in `config/serve.env` is **upstream's own
default**, not a local deviation. It is undocumented anywhere else in the repo;
whether enabling it changes the anchor-persistence path is UNKNOWN and untested.

Levers, none yet tried (ordered by expected value / risk):
- **Reduce resumed-context size agent-side** (more aggressive Hermes
  compaction, or start new sessions): attacks step 1, no lane risk.
- **Create quiet windows** (stagger fleet polling / cap concurrent agents) so
  the 0.5 s writer gate can fire: attacks step 4.
- **Test `TF_GLM_SESSION_CHECKPOINTS=1`** on a drained lane: unknown effect,
  needs a controlled A/B, do not flip on the live lane.
- **Raise with upstream**: the quiet gate is unachievable on a shared
  always-busy lane; a time-budgeted or forced-save policy would help.

Raising `SERVE_PARALLEL` would NOT help — see the concurrency note above; the
lane already batches (2.37x on 3 streams) and the cost is prefill monopoly.

### The real concurrency ceiling is the shared KV pool, not `--parallel`

Live engine cmdline: `--tp 3 --context 262144 --max-tokens 32768 --parallel 8`.
So **8 request slots are configured** (the earlier "3" was only this probe's N).

But all running requests share ONE context pool. From the rank-0 startup log:

```
[tensorfold] GLM shared token pool: 360,448 usable tokens (requested 360,448);
             per-request context 262,144
[tensorfold] CUDA rank 0 startup estimate 79.70 GiB within 102.16 GiB
```

`docs/OPERATIONS.md`: "All running requests share one pool of context memory. A
request near the full context window can wait in the queue until other long
requests finish."

Arithmetic against our own limits (Hermes agents are capped at 256K = the lane's
`--context`):

| concurrent sessions of... | pool needed | fits in 360,448? |
|---|---:|---|
| 1 x 256K (max-size agent) | 262,144 (73% of pool) | yes, barely |
| 2 x 256K | 524,288 | **no** |
| 2 x ~156K (observed real size) | ~312,000 (87%) | yes |
| 3 x ~156K | ~468,000 | **no** |
| 8 x ~156K (to use `--parallel 8`) | ~1,248,000 (3.5x pool) | **no** |

**So effective concurrency for our workload is 2, not 8** — and exactly 1 if an
agent actually fills its 256K allowance. That, not a metrics shim and not a
scheduler cap, is the structural reason the lane sits at ~1 running.

Why is the pool so small? `TF_GLM_POOL_TOKENS=360448` is **upstream's default**
and equals 1.375x context — just above the engine's legal floor. From
`engine/src/tensorfold/families/glm5_next/cuda/engine.py`, the accepted range is
`--context` through `parallel * --context`:

- floor: 262,144 (1x)
- **current: 360,448 (1.375x) = 17% of the legal maximum**
- ceiling: 2,097,152 (8x)

It was never tuned for our context sizes. Headroom exists: rank 0 reports 79.70
GiB used within a 102.16 GiB budget, and `fit_shared_pool` subtracts the
`TF_GLM_CACHE_GIB=5` snapshot reserve, leaving **~17.5 GiB** to grow into. Ranks
1 and 2 are slightly lighter (77.40 GiB within 103.38 / 102.82 GiB), so **rank 0
is the binding node.**

Two safety properties of this knob, both read from the source:

1. `fit_shared_pool` **binary-searches the largest pool that fits the budget and
   clamps** — it does not OOM on an over-large request. Our log shows
   `usable == requested`, proving we were never memory-limited, just modest.
2. The chosen size is `min()` across ranks and must match on every rank, so the
   weakest node governs and a mismatch is a hard startup error, not a silent skew.

**This knob plausibly attacks BOTH problems at once**: a larger pool keeps more
sessions resident, which should reduce the `store-evicted` re-prefills as well as
raise usable concurrency. Untested.

Not changed, and must NOT be changed on the live lane: raising it requires a
restart, so it needs a drained lane plus Victor's approval, and the GB10
crash-forensics rule applies (an NVRM OOM wedges the node). The honest test is
to raise the request on a drained lane and read back the
`usable tokens (requested N)` line to discover the true ceiling empirically.

One-shot cron `jspark3-v202-resume-recheck` (job `e8827d963c41`) re-runs the
audit to quantify the standing cost and confirm `store-evicted` persists.

## Mia TensorFold recipe (parked lane) updated in the same session

Fast-forwarded v1.5 -> v1.8 (38 commits, 0 ahead, clean) and synced to
`spark3:~/GLM53-TF3`, excluding `.env`/`.env.tp3`/`local.sh`/logs/results.
82 patches, image pin `v0.6.0-31557ed1cef6`. Node-local wiring preserved:
`KV_POOL_GIB=27`, `CONTAINER_NAME=glm53-tf3`, TP3 rank wiring in
`scripts/local.sh`. No `IMAGE`/`SKIP_PULL`/fair-prefill pin was present to
neutralize the update. Not started — the lane is parked behind jspark3.

Mia v1.6-v1.8 highlights: shared-prefix copy (5% -> 99% resume on a coding
agent re-reading 150-210K tokens; TTFT 16.5 s -> 1.0 s), queued-request
cancellation, optional gated Ablit weights (`ABLIT=1`), a system-prompt resume
fix once the kept cap fills, an `NV_ERR_NO_MEMORY` fix on a fresh conversation
after a long one, a picture cache (TTFT 0.45 s -> 0.17 s on 10-image chats),
and 429 + Retry-After capacity refusals.
