# jspark3 GLM-5.3-Flash TP3 — our deviations from upstream

Upstream: <https://github.com/jakejharris/jspark3> (canonical recipe now cloned
locally at `~/recipe-db/jspark3`, tag `v2.0.2`, commit `14ee56e`).

Serve from the recipe repo, never from memory. Every item below is a DELIBERATE
local deviation. `stage-jspark3-v202.sh` applies all of them, so a restage does
not silently revert to upstream defaults.

| # | Setting | Upstream | Ours | Why |
|---|---|---|---|---|
| 1 | `config/serve.conf` `SERVE_NAME` | `glm53` | `GLM-5.3-Flash-EXL3` | Served model id the whole fleet's clients already point at. Keeps `/v1/models` stable across lane cutovers. **Causes the one expected `smoke.sh` FAIL** (`models glm53 listed`) — 5/6 is a PASS for us. |
| 2 | `config/serve.env` `TF_GLM_POOL_TOKENS` | `360448` | `786432` | Shared KV pool. See below. |

## 1. `SERVE_NAME`

Do not "fix" the smoke failure by reverting this. `smoke.sh` asserts the
upstream id; we intentionally serve a different one. A 6/6 smoke on this lane
would mean the pin was lost.

## 2. `TF_GLM_POOL_TOKENS` — raised 2026-10-07

Upstream's `360448` is 1.375x context, just above the engine's legal floor.
All running requests share ONE context pool (`docs/OPERATIONS.md`: "All running
requests share one pool of context memory. A request near the full context
window can wait in the queue until other long requests finish").

Our Hermes agents are capped at 256K context = the lane's `--context 262144`.
So the old pool held exactly ONE max-size conversation (1.38x) and ~2 at
observed sizes (~156K) — capping usable concurrency at ~2 **regardless of
`--parallel 8`**. That, not a scheduler limit, is why the lane sat at ~1 running.

Measured cost (engine's own geometry functions, `checks/pool-slope.py`):
**20,224 bytes/token = 19.75 KiB/token; 1 GiB buys ~53,000 tokens.**

| setting | tokens | x ctx | concurrent ~156K | concurrent 256K |
|---|---:|---:|---:|---:|
| upstream | 360,448 | 1.38x | 2.3 | 1.4 |
| **ours** | **786,432** | **3.00x** | **~5.0** | **~3.0** |
| calibrated max | 1,287,442 | 4.91x | ~8.3 | ~4.9 |

**Do NOT raise to the calibrated max.** It leaves zero spare against an
*estimate*, and GB10 crash forensics show an NVRM OOM wedges the node. Legal
range is `--context` .. `parallel * --context` = 262,144 .. 2,097,152, but the
MEMORY ceiling (~1.29M) binds well before the legal one.

Constraints when changing it:
- **Must be identical on every rank** — the engine hard-errors on a mismatch
  (`TF_GLM_POOL_TOKENS must match on every rank`). Verify with `md5sum` of
  `config/serve.env` across all three boxes before starting.
- `config/serve.env` is the ONLY sanctioned source. `scripts/lib.sh` refuses
  engine settings from profiles ("every engine setting has one source,
  config/serve.env") and `serve.sh` passes it with `--env-file`.
- Requires a ring restart. Do it on a drained lane (`tensorfold:inflight 0`).
- `ceiling = budget - TF_GLM_CACHE_GIB`, so the pool and the 5 GiB conversation
  store compete for the same budget. Raising both is not free.

### Verifying the pool actually took

1. The engine's own line — `usable` must equal `requested`, else it clamped:
   ```
   [tensorfold] GLM shared token pool: 786,432 usable tokens (requested 786,432)
   ```
2. **Do NOT use the startup estimate line as a pool check.** It still reads
   `79.70 GiB within ~102 GiB` because `admit()` prints it BEFORE
   `fit_shared_pool` runs, sized on the context window, not the pool. An
   unchanged number there does not mean the change failed.
3. Functional proof: `checks/pool-proof.py` fires two concurrent ~195K
   DISTINCT-content requests (390,875 tokens combined — more than the old pool
   could hold). Overlapping TTFTs prove both were resident at once. Content
   must differ per stream or the prefix cache collapses them and fakes a pass.

## Known-benign, not a deviation

- `PREV_IFACE` (`enp1s0f0np0`) is NO-CARRIER fleet-wide: we use the switched
  CRS504 RoCE fabric, not the recipe's direct-cable ring. `preflight.py` FAILs
  on it; both v2.0.1 and v2.0.2 serve fine this way.
- NCCL `ibv_query_port_speed ... errno 93` warnings at startup.
- `TF_GLM_SESSION_CHECKPOINTS=0` is upstream's OWN default, not our change.
