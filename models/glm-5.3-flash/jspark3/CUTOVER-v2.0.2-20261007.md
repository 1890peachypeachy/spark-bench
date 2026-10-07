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

Open question, deliberately NOT closed: v2.0.2 derives its session namespace
from the wheel digest, so every session started cold by design at cutover. The
cold big-context prefills may be expected warm-up. One-shot cron
`jspark3-v202-resume-recheck` (job `e8827d963c41`) re-runs the audit ~5 h later.
If big-context requests STILL show `resumed=0` once warm, it is a real resume
defect; the next step is checking `session_miss_reason` on those requests for
`fork`/`shared-prefix-divergence` (an agent prompt changing early, e.g. a
timestamp in a system prompt) versus eviction.

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
