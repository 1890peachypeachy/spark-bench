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
| 3 | `config/serve.env` `TF_GLM_DISK_GIB` + `config/serve.conf` `SERVE_SESSION_GIB` | `64` | `192` | Disk session store. 64 GiB held only ~26 conversations and evicted states it then needed. See below. |

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

## 3. `TF_GLM_DISK_GIB` / `SERVE_SESSION_GIB` — raised 2026-10-07

Upstream's `64` is far too small for this lane's prompt sizes. **Real session
files reach 3.0 GB each** (`du` inside the container, not `staged_bytes` — see
the measurement trap below), so 64 GiB held only **~26 conversations**. The
store therefore sat permanently at its cap and evicted states it then needed
again: **265 `store-evicted` / `observed-prior-prompt` misses in a single boot**,
against 856 hits and 174 `fork` misses.

Cost of a miss, from the engine's own request log:

| session source | prompt | prefill |
|---|---:|---:|
| `memory` (89,779 resumed) | 93,259 | **21.0s** |
| `cold` / store-evicted | 99,999 | **279.7s** |
| `cold` / store-evicted | 145,213 | **476.0s** |

59 requests in one hour burned 10,553s of prefill (avg 178.9s). The slowness is
**prefill, not decode** — long agent turns re-read the whole prompt.

Raised to `192` (~78 conversations). Costs **no GPU memory**, unlike
`TF_GLM_CACHE_GIB`, which shares the pool budget (`ceiling = budget - CACHE_GIB`).

Constraints when changing it:
- **Size by the TIGHTEST node, not the roomiest.** The tier is per box, and
  `serve.sh` warns and stops writing below `150 GiB` free (`free < (150 +
  SERVE_SESSION_GIB)`). On 2026-10-07 spark4 had **434 GiB** free vs ~1250 on
  spark1/spark3, so 192 (needs 342, leaves 92 GiB margin) was the safe ceiling.
  **384 would have exceeded spark4's budget** and silently stopped writing there.
- **Both knobs move together.** `serve.env` `TF_GLM_DISK_GIB` drives the engine;
  `serve.conf` `SERVE_SESSION_GIB` drives the free-space guard and the operator
  message. Changing only one leaves the guard computing on a stale number.
- Requires a ring restart; the store itself SURVIVES it (verified: 64 G / 286
  session files intact across the 2026-10-07 restart), so there is no cold-start
  penalty from bouncing the lane.

### Measurement traps (both cost real time on 2026-10-07)

1. **`staged_bytes` is NOT the session size.** It is a staging increment
   (240-453 MiB) and reads ~6x smaller than the real 3.0 GB session file. Sizing
   the store from it overestimates capacity by the same factor.
2. **Read the store from INSIDE the container.** The store dir is
   `drwx------ root:root`, so a host-side `du`/`find` as the ssh user returns
   `60K` and `0` files — making a full 64 GiB store look empty. Use
   `docker exec <rank0> du -sh /sessions`. `disk_bytes` in the session-cache log
   is actual usage (it grew 42.6 -> 64.0 GiB across the boot), not a budget.

### What this does NOT fix

The 174 `fork` / `shared-prefix-divergence` misses are architectural: reuse
requires a prompt to start with the ENTIRE earlier prompt, and `LIMITATIONS.md`
is explicit that a shared system prompt with a different first message is read
in full. Those show `cached: 9` on 195K-token prompts. No store size helps;
that needs stable append-only prefixes per agent, or block-level prefix caching.

## Known-benign, not a deviation

- `PREV_IFACE` (`enp1s0f0np0`) is NO-CARRIER fleet-wide: we use the switched
  CRS504 RoCE fabric, not the recipe's direct-cable ring. `preflight.py` FAILs
  on it; both v2.0.1 and v2.0.2 serve fine this way.
- NCCL `ibv_query_port_speed ... errno 93` warnings at startup.
- `TF_GLM_SESSION_CHECKPOINTS=0` is upstream's OWN default, not our change.
