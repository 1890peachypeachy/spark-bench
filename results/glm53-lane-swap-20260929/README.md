# GLM-5.3-Flash TP4 lane swap: mentat/gx10 → knapcio align-fix (2026-09-29)

Cutover of the live 4x DGX Spark TP4 lane from the mentat/gx10 recipe
(`spark-glm53:v9`) to knapcio's fixed `GLM-5.3-Flash-4x-DGX-Spark-TP4` release,
after upstream fixed the KDA/prefix-cache corruption we filed as
[issue #2](https://github.com/knapcio/GLM-5.3-Flash-4x-DGX-Spark-TP4/issues/2).

Serving contract preserved so consumers needed no change:
`GLM-5.3-Flash-EXL3` on `:8888`, host bind `0.0.0.0`.

## Verdict

**Corruption fixed (verified on our hardware). Real but moderate speed win.
Upstream's headline numbers did NOT reproduce on our fleet.**

## Corruption gate — PASS

`bench/prefix_scan.py run --conc 8 --rounds 3 --logprobs` (upstream's own gate,
built from our issue #2 reproduction). Full output: `prefix-scan-score.json`.

| metric | issue #2 (broken) | fixed target | our lane |
|---|---|---|---|
| cold-vs-warm logprob drift | 0.25–0.36 | 0.02–0.04 | **0.039** |
| cold-vs-cold floor | 0.04–0.09 | — | 0.0464 |
| gate limit | — | — | 0.0696 |
| degenerate responses | the bug | 0 | **0 / 48** |

Cold-vs-warm (0.039) landed *below* the cold-vs-cold floor (0.0464): a prefix-cache
hit now restores the same state a fresh cold run had. The test genuinely exercised
the bug path — prefix sized to `P mod 2304 = 593–651` (inside the `[1,1152]` stale
window) and `warm_without_hit: 0`, so every warm request really hit cache.
Residual `misquotes` 2 cold / 1 warm and `incorrect` 6/7 on the anomaly-scan task
are the T=0.8 quality warnings upstream tolerates; `reasons: []`.

Fix confirmed armed in the engine log, not merely present:
`glm-mamba-align-fix: Scheduler._mamba_block_aligned_split aligned to mamba_block_size, last full block stop added`
with `block_size 2304`, `max_num_batched_tokens 6919`.

## Decode: measured, c1, same script both lanes (`spark-bench/bench/c1_decode_screen.py`)

| prompt | old lane (mentat/gx10) | new lane (knapcio align-fix) | change |
|---|---|---|---|
| prose | 35.8 | **62.2** (idle window) | **+74 %** |
| code | 42.0 | 48.9 (1 concurrent req) | +16 % (understated) |
| structured | 76.1 | 81.4 (1 concurrent req) | +7 % (understated) |

Upstream's claim for this release: prose 90.3 at default clocks, 83.8 at the
2200 MHz cap. **We measure 62.2.** The gap is not speculative decoding failing —
acceptance is healthy: 27.0 % of draft tokens accepted, 1.89 accepted per draft
step (≈2.89 tokens per target forward pass), per-position 73.6 / 43.8 / 27.8 /
17.6 / 12.3 / 8.4 %. Unexplained; spark1's 2190 MHz clock cap (vs 3003 max) is a
candidate but upstream's 83.8 was itself measured capped, so the cap alone does
not account for it.

### Measurement trap worth remembering

`GLM_LV_MODE=batch-uniform` + `SPEC_TABLE [[1,1,7],[2,2,5],[3,27,3],...]` means a
single extra concurrent request drops the whole batch from 7 drafts to 5. A "c1"
benchmark taken while any consumer is active is really c2 and reads far low
(39.5 vs 62.2 prose here — a 1.6x error). Gate c1 benchmarks on
`vllm:num_requests_running == 0` immediately before each sample.

Second trap: GLM-5.3-Flash streams thinking tokens under the `reasoning` delta key
with `content: None`. A harness watching only `content`/`reasoning_content`
measures nothing, or starts its timing window after all thinking and reports
absurd rates (451 tok/s observed).

## Configuration

- Recipe: our fork at merge commit `f986b9e` (upstream `770d115` + our 3 commits),
  staged on head node spark3 at `/var/tmp/glm53-recipe-tp4`.
- `CTN=glm53-alignfix-20260929` (fresh name — `start.sh stop` preserves containers,
  and preflight inspects them, so a new deployment requires a new CTN).
- `GPU_UTIL=0.72` (below the recipe's 0.78): the new profile triples CUDA graph
  capture to 66 sizes across 7 verify families, so graph memory headroom matters.
- `--restart no` (the launcher's default; never `unless-stopped` on this lane).
- Boot to health 200: **5.3 min**.

## Rollback

`rollback/` holds `docker inspect` plus the compose file for the previous lane on
each node. Restore with, per node:

```sh
docker compose -f /var/tmp/glm53-gx10/compose/glm53.yaml up -d
```

The previous lane ran compose project `glm53` from
`/var/tmp/glm53-gx10/compose/glm53.yaml` with `restart=unless-stopped`, so it must
be taken down with `down`, not `stop`.
