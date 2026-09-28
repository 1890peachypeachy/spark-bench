# GLM-5.3-Flash TP4 — knapcio NVFP4/lossless8 recipe (2026-09-27)

**IMPORTANT — served-name overload:** this deployment answers as `GLM-5.3-Flash-EXL3`
on port 8888 (matching TP3's client-facing identity), but it is a **completely
different backend** from `../exl3-tp4/` (Mia's actual EXL3 quant kit). This recipe
uses vLLM + NVIDIA NVFP4 base weights, converted offline to a lossless8 quant-mix,
with an FP8-quantized DFlash2 drafter — not EXL3 quantization at all. The name/port
were kept identical on purpose so existing clients don't need reconfiguring; do not
assume `GLM-5.3-Flash-EXL3` implies the EXL3 backend going forward. If both recipes
are ever run side by side, this is a real naming collision — check what's actually
serving via `docker ps` / a live `/v1/models` or canary call, never assume from the name.

## Source of truth

Recipe repo (clone, don't hand-reconstruct): `https://github.com/knapcio/GLM-5.3-Flash-4x-DGX-Spark-TP4`,
staged locally at `~/recipe-db/GLM-5.3-Flash-4x-DGX-Spark-TP4/` and mirrored to
Spark3 at `/var/tmp/GLM-5.3-Flash-4x-DGX-Spark-TP4/` (must run `start.sh` from
Spark3 itself — `HOSTS` includes `local`, which resolves to whatever host invokes
the script, and the head node must be Spark3).

Base weights: `nvidia/GLM-5.3-Flash-NVFP4` @ commit `09b04e5e74bca08ca8549fc736d4cdd8624bfde3`
(config.json SHA256 `e23c5d98f53e861d49a51bd3c68591621c5482ce829e42c31724152322fba03d`).
Drafter: `incoai/GLM-5.3-Flash-DFlash2` (config SHA256 `c4aeac0101196a6e26705b34c45230bcd0c7c68ee2d2d1efdb242087f3712573`).

Converted (offline, CPU-only container, `--network none`) via the recipe's own
`scripts/build_lossless8.sh` + `scripts/drafter_fp8.py`:
- Lossless8: `/var/tmp/models/glm-quant-mix/lossless8` (config SHA256 `f14dc13ce3bef88a5539c9e61b3e4f3dbef6958ebc3acda4b7f05f418642c3b0`)
- Drafter FP8: `/var/tmp/models/incoai/GLM-5.3-Flash-DFlash2-fp8blk` (config SHA256 `15bc842939ff7ca6ebf62b99b3207706d0ec1e75a7f7a2dc9dafc63c5ccc4c81`)

Both hashes match the recipe's own documented acceptance targets exactly — verify
against those, don't just trust a green exit code from the conversion script.

## Cross-node distribution: NFS, not per-node rsync copies

Spark4 cannot hold a local copy (its disk runs consistently near-full). The fleet
already runs a shared NFS exporter container, `dsv41-nfs`, on Spark3 — originally
scoped narrowly to `/var/tmp/models/DeepSeek-V4.1-Flash` only. **We repointed its
export root up one level to the shared parent `/var/tmp/models`** so any model
directory placed there (DeepSeek's, GLM's, or a future one) is automatically
NFS-reachable by all 3 workers under the same single NFSv4 pseudo-root — no new
export needed per model, no second NFS server. This is now the standing mechanism
for TP2/TP3/TP4 fan-out: **just drop the model under `/var/tmp/models/<name>/` on
Spark3 and it's live for every worker.**

Practical notes if you ever need to touch this again:
- `dsv41-nfs` is `--privileged --network host`, sharing the host's kernel nfsd —
  do **not** also run a host-level `nfs-kernel-server.service`; starting one sends
  a signal that makes the container's `rpc.mountd` restart and re-export from
  scratch (harmless — self-heals — but disruptive; just don't do it).
- NFSv3 is disabled on this nfsd config; only NFSv4.2 mounts work.
- With a single `fsid=0` export root, all real paths under it are reachable via
  `mount -t nfs4 -o ro,vers=4.2 10.73.0.3:/ /var/tmp/models` on each worker — no
  need to mount subpaths individually.
- Mounts are persisted in each worker's `/etc/fstab` with `_netdev,nofail` so a
  worker rebooting without Spark3 up doesn't hang on boot.
- Read-only, scoped to `10.73.0.0/24` (the RoCE fabric) only — never widen this.

## GPU_UTIL tuning — two distinct root causes, don't conflate them

We hit two different classes of TP4 rank crash on Spark2 in the same evening.
Diagnose which one you're looking at before reaching for `GPU_UTIL`:

1. **Kernel `MemAvailable` accounting anomaly** — `MemFree` looked normal (matching
   siblings) but `MemAvailable` (what vLLM's CUDA free-memory check actually uses)
   was understated by ~19G for no process-visible reason (`ps aux --sort=-%mem`
   showed nothing pathological). **Fix: reboot the affected node.** Lowering
   `GPU_UTIL` here is a band-aid on a phantom constraint, not a real fix — revert
   it once the reboot clears the anomaly.
2. **Real node-to-node memory variance** — after a clean reboot, Spark2 still ran
   ~1.5G short of the recipe's `GPU_UTIL=0.78` default (93.39G actual vs 94.92G
   desired). This is genuine and reproducible. **Fix: `GPU_UTIL=0.75`** in `.env`
   gives real headroom without meaningfully sacrificing KV cache capacity.

Both fixes are in the `.env` override block copied in this directory
(`env.tp4-fixes-reference`) — treat it as a reference/diff, not a full working
`.env` (secrets/paths are node-specific; sync the real `.env` from
`~/recipe-db/GLM-5.3-Flash-4x-DGX-Spark-TP4/.env`).

## Recipe's own dead-container bug

Same class of bug already fixed in `spark-lane` for `dsv41`/other lanes: this
recipe's `start.sh` verify step throws `RuntimeError: container name exists`
instead of cleaning up dead containers from a prior crashed attempt before
relaunching. Not yet patched upstream in this recipe — for now, manually
`docker rm` any `Exited` containers matching the lane's name pattern on all 4
nodes before re-running `start.sh serve`. Worth porting the same
`cleanup_dead_containers()` fix pattern into this recipe if it recurs often.

## Verified working (2026-09-27)

`curl http://100.99.120.29:8888/v1/chat/completions` → correct answer, TP4 across
all 4 Spark nodes, `system_fingerprint` confirms `vllm-...-tp4-...`. Cold start
~9 minutes from `start.sh serve` to `health 200`.

## Don't skip the recipe's own quality gate

We initially declared this "verified" from a couple of manual curl spot-checks
(one arithmetic question, one short story). A user later hit a garbled/repeating
output from a real agent session. Investigation found `SpecDecoding metrics: ...
Accepted: 0 tokens, Drafted: 915 tokens, Avg Draft acceptance rate: 0.0%` in the
server log right around that time — but the recipe's own `scripts/drafter_fp8.py`
docstring is explicit that a lossy/degraded drafter should only ever slow decoding
down, never corrupt output (rejection sampling always falls back to the verified
target). So a bad acceptance rate alone doesn't indict the drafter conversion.

The actually correct validation step, already in the recipe and skipped by us
the first time: `docs/validation.md`'s quality gate, `bench/qeval.py` (55
auto-scored tasks incl. explicit prose-degeneration checks), requiring **>=72/75
at both c1 and c4 concurrency**. Run it against the live endpoint before calling
any serving change validated - "a component speed result does not qualify a
serving change" is the recipe's own words for exactly this mistake.

Note: `qeval.py` hardcodes `"model": "GLM-5.3-Flash-FP8"` in its request body,
which 404s against any other `--served-model-name`. No `--model` CLI flag exists.
Fix is a local, throwaway `sed` swap on the copy you run from - do not commit
that change back upstream (it's request-shape only, not a recipe fix), and
restore the original file after.

Result on this deployment: **c1 73/75 (97.3%), c4 71/75 (94.7%)**, all prose/
degeneration checks clean at both concurrencies (5/5 both runs). Both clear the
gate. The two failures each run were ordinary wrong-answer misses (math/counting),
not repetition or corruption - consistent with the garbled output having been a
rare, transient edge case rather than a systemic defect. Re-run this gate after
any future config change to this lane (GPU_UTIL, spec-decode params, weight
re-conversion) before calling it done.

## Real root cause of the garbled first-interaction bug (confirmed, upstream recipe bug)

The qeval pass above does NOT mean there was no bug - it means the bug isn't a
weight-correctness problem. The actual cause: **`BOOT_WARM=1` (on by default)
is broken in this recipe.** `scripts/boot_warm.py` does
`sys.path.insert(..., "../bench"); import prefill_bench as pb` but
`bench/prefill_bench.py` does not exist anywhere in this repo (checked both our
local clone and the synced copy on Spark3) - confirmed by manually invoking it:

```
ModuleNotFoundError: No module named 'prefill_bench'
```

So the recipe's own protection against "first live request hits a cold engine"
(2x 16384-token cold prefills right after `/health` goes 200, per `start.sh`'s
own comment: "so the first user's long prompt does not pay the first-long-
prefill cost") **silently never runs, for anyone deploying this recipe** - it
crashes on import with no visible error at launch time (no log file, no pid
file, nothing in `start.sh serve`'s own output; only visible by invoking
`boot_warm.py` directly).

Confirmed timeline on this deployment: first real client request landed 27s
after `health 200`. That's genuinely the first live request against a stone-
cold engine - empty prefix cache, freshly-captured CUDA graphs, zero
calibration data in the custom adaptive-k scheduler. That is a textbook
condition for a degenerate decode loop that never hits EOS. qeval (run much
later, against an already-warm engine with 88%+ prefix cache hit rate and
tens of thousands of adaptive-k observations) could not have caught this even
if run immediately after launch, unless run within seconds of `health 200`.

**FIXED (not just mitigated), 2026-09-27:** added `bench/prefill_bench.py` to our
fork (`origin/main` @ `f228cc7` in `~/recipe-db/GLM-5.3-Flash-4x-DGX-Spark-TP4`) -
`post`/`build` already existed with matching signatures in
`bench/prefill_checked.py`; the shim re-exports those and adds the one missing
piece, `ttft()`. Verified against this live deployment:

```
[08:09:41] boot-warm: waiting for http://127.0.0.1:8888/health (up to 1800 s)
[08:09:41] boot-warm: healthy after 0 s
[08:09:42] boot-warm: short chat 0.349 s, 10 tokens
[08:09:44] boot-warm: long cold prefill 1/1: {"elapsed_s": 2.156, "http_status": 200, "prompt_tokens": 3966, "tok_s": 1839.3}
[08:09:44] boot-warm done in 3 s
```

`BOOT_WARM=1` (the default) will now actually run on every future `start.sh
serve` for this recipe - no more manual step needed. `manual_boot_warm.sh` in
this directory stays as a fallback/sanity-check tool, not the primary
mitigation anymore. Worth upstreaming this file to `knapcio/GLM-5.3-Flash-4x-
DGX-Spark-TP4` at some point (currently only on our fork, `origin`).

---

## 2026-09-27 (evening) - lane-ified, and the three things that actually break it

Second clean bring-up, this time registered as a real sparkDash lane:
`spark-lane up|down|verify|rotate glm53-tp4` (see `ops/spark-lane`). Endpoint and
served name are deliberately IDENTICAL to the TP3 lane -
`http://100.99.120.29:8888/v1`, `GLM-5.3-Flash-EXL3` - so nothing downstream
repoints when we swap backends. The two GLM lanes both own :8888 and are
therefore mutually exclusive; `spark-lane rotate glm53-tp4` is the safe swap.

Verified this run: 4/4 ranks (`glm53-lvkp-s-l2-r0..r3`), fingerprint carries
`tp4`, qeval **c1 73/75 (97.3%)** and **c4 74/75 (98.7%)**, prose 5/5 on both
concurrencies (no degeneration). c4 beat the morning's 71/75. Only misses were
ordinary math items.

### Three failure modes, each of which cost a full bring-up tonight

1. **The `.env` had been left pointing at the WRONG image.** A previous session
   debugging TP4 set `IMAGE=ghcr.io/miaai-lab/...:exl3` (Mia's TP3 EXL3 image)
   and `GPU_UTIL=0.65`, on BOTH the local clone and the spark3 mirror. That
   combination is what produced the infamous
   `tvm.error.InternalError: Unsupported sparse-MLA prefill configuration ... topk=2176`
   during CUDA graph capture. That error is **not a TP4 kernel bug** - it is what
   you get when you run this recipe on the EXL3 image. Correct values:
   `IMAGE=glm53-roce:v11-b58f34ea`, `GPU_UTIL=0.75`. Always diff `.env` against
   `env.tp4-fixes-reference` before concluding anything about kernels.

2. **NFS mounts do not survive a reboot reliably.** Workers read the weights from
   spark3 over NFS (`/var/tmp/models`, exporter = the `dsv41-nfs` container). The
   fstab entry is `_netdev,nofail`, so if a worker boots while spark3's exporter
   is not yet up, the mount is silently skipped and the node has NO weights - every
   rank then dies with a confusing peer-disconnect chain. All three workers had
   rebooted ~15:0x and all three had no mount. `systemctl restart
   var-tmp-models.mount` per worker fixes it; the lane now checks and self-heals.

3. **Page cache and the MemAvailable anomaly starve the GPU free-memory check.**
   GB10 is UMA, so the CUDA free-memory check competes with page cache. Right
   after `docker load` of the 31GB image, spark2 reported only 84.09 GiB free vs
   the 91.27 GiB that `GPU_UTIL=0.75` requires, and aborted before loading a
   single weight. `sync + drop_caches` recovered ~16 GiB. A second attempt still
   failed at 89.49 GiB - spark2 was sitting ~18 GiB below its siblings with zero
   containers and no process holding it: the documented kernel MemAvailable
   anomaly. A **reboot of spark2** took it to 105.9 GiB and the lane came up.
   Do NOT "fix" this by lowering `GPU_UTIL` - that is a band-aid on a phantom
   constraint and it silently costs KV cache.

Diagnostic note: when a rank dies, the head's log only shows
`Connection closed by peer [10.73.0.x]`. Chase the chain to the node that failed
FIRST (here: head blamed spark1, spark1 blamed spark2, spark2 had the real
memory error). The lane's failure `NEXT:` hint now prints the all-node log sweep.

### 2026-09-27 (later) - four bugs found by actually pressing the dashboard button

Registering the lane was easy; making it SAFE took four fixes. All four were in my
own lane code, and two of them could take down live inference. Lesson: an untested
lane function is more dangerous than no lane function.

1. **`node_occupant()` has a two-stage filter.** A pre-filter grep decides which
   container names are even considered, THEN the lane-detection chain runs. Adding
   `glm53-lvkp` only to the detection chain was useless — the pre-filter dropped it
   first, so the live lane reported `down`. Worse: `occupancy_conflict()` shares
   that function, so the fleet looked FREE while TP4 was serving, and `up`/`rotate`
   on any other lane would have launched straight on top of it. Add new container
   names to BOTH places.
2. **`docker rm -f` in a cleanup step will kill a healthy lane.** The cleanup ran
   before the already-up check and used `-f`, so pressing "up" on a serving lane
   force-removed all four running ranks and then reported "not serving yet" about
   the lane it had just destroyed. The rest of this harness uses bare `docker rm`
   on purpose: it refuses anything still running. Never add `-f`, and never put a
   destructive step ahead of the already-up short-circuit.
3. **A guessed memory headroom constant causes false refusals.** Gating on
   `GPU_UTIL*total + 10 GiB` refused a launch over a 0.1 GiB shortfall (101.2 vs
   101.3) and told the operator to reboot a node for nothing. Observed truth is
   only that 99.5G failed and 105.9G worked — the threshold is in between and
   moves. Gate on the physically impossible (`GPU_UTIL*total`), warn about the grey
   zone, and let the engine be the authority; it fails in ~2 min with exact numbers.
4. **An ssh failure is not a dead rank.** The liveness probe collapsed "ssh timed
   out" and "zero containers" into the same `0` and aborted on a single sample.
   During CUDA graph capture the head node is saturated and ssh times out routinely
   — so this aborted a healthy bring-up that was mid-warmup, reporting a crash that
   never happened. The lane actually came up fine on its own afterwards. Separate
   the probe's exit status from its output, and require 3 consecutive confirmations.

Regression test that matters: with the lane serving, `POST /api/lanes/glm53-tp4/up`
must return `PASS (already up, unchanged)` in <15s and leave health at 200.

### 2026-09-27 (night) - a non-streaming request can outlive its client

A librarian agent loop sent ~153k-token prompts and one generation ran away: 25+
minutes, ~50k tokens, `Running: 1` with `prompt_tokens_total` and
`request_success_total` both frozen — nothing arriving, nothing finishing, one
request pinning all four Sparks. For scale, all 94 normal requests that day
finished under 10k tokens.

Things that did NOT stop it:
- Stopping the Hermes session. That ends the agent loop, but Hermes's shared
  OpenAI client keeps the TCP connection open, so the server never sees a hangup.
- `ss -K` on the head node. GB10's kernel answers `RTNETLINK answers: Invalid
  argument` — no `INET_DIAG_DESTROY` support.
- RST-ing the connection (targeted iptables REJECT --reject-with tcp-reset, added
  and removed in one shot). The socket did die, but generation continued: for a
  NON-STREAMING request vLLM never writes to the socket, so it never notices the
  peer is gone. The request is orphaned and runs to its token cap.
- There is no abort route. This build's only cancel endpoint is
  `/v1/responses/{id}/cancel` (Responses API); chat-completions has none.

The only reliable kill is `spark-lane down <lane>`. Budget the bring-up.

Prevention is SERVER-side. ~~Client-side `max_tokens`~~ does not work for Hermes:
`model.max_tokens` is set in 7 profiles and is silently ignored — `gateway/run.py`
never passes it to `AIAgent`, and upstream issue #4404 was closed by deleting the
suggestion from the docs rather than implementing it. Use the recipe's
`DEFAULT_MAX_NEW_TOKENS` (see the 2026-09-27 deviation section at the end).

Also confirmed here: the memory preflight reads MemAvailable, but vLLM gates on
CUDA-visible free memory, which sits BELOW it. spark2 cleared the 91.3G floor and
still died with `Free memory on device cuda:0 (90.38/121.69 GiB) ... less than
desired (0.75, 91.27 GiB)`. A node power-cycle restored it to 106.0G and the lane
came up in 225s. MemAvailable is a proxy, not the authority — the grey-zone
warning exists for exactly this. ~~Power-cycling the node (not lowering GPU_UTIL)
is the fix.~~ **Corrected later the same night: see below. Power-cycling only helps
when nothing else is competing for the node.**

## 2026-09-27 (late) — GPU_UTIL 0.72 deviation, because spark2 has a co-tenant

**Effective config on spark3, NOT in git (`.gitignore:1` ignores `.env`).**
Re-clones and node rebuilds revert to the recipe default, so restore these by hand:

```ini
GPU_UTIL=0.72                    # deviation from the recipe's verified 0.75
DEFAULT_MAX_NEW_TOKENS=65536     # omitted-request output fallback (opt-in safety net)
IMAGE=glm53-roce:v11-b58f34ea
```

Backups of the 0.75 state: `.env.bak-20260927-util075` on the local clone and spark3.

### Why: it was never a "MemAvailable anomaly"

**Penpot runs on spark2** — 5 containers, all `restart=unless-stopped`. They come
back on every boot and re-take the headroom. That is why spark2 drifted 106.0 ->
99.1 GiB after a power-cycle, and why power-cycling it twice fixed nothing. The
earlier advice above is wrong whenever a co-tenant is `unless-stopped`.

| | GiB |
|---|---|
| spark2 MemAvailable | 99.0 |
| spark2 CUDA free (~10 GiB UMA gap below MemAvailable) | 88.8 |
| TP4 needs at GPU_UTIL 0.75 | 91.27 — fails |
| TP4 needs at GPU_UTIL 0.72 | 87.6 — fits, ~1.2 GiB margin |
| Penpot's own footprint | ~1.85 — so stopping it alone would NOT have cleared 0.75 |

### What 0.72 costs: effectively nothing

```
GPU KV cache size: 2,945,172 tokens
Maximum concurrency for 262,144 tokens per request: 11.23x
```

Context stays 262,144 and 11 concurrent full-context requests remain available,
against agent traffic that peaks near 1. Healthy in 120s, 4/4 ranks. The recipe's
"do not lower GPU_UTIL" guidance is about starving KV; at 11.23x we are nowhere
near that. Prefer 0.75 on a node with no co-tenant; use 0.72 while Penpot shares
spark2.

### Kit sync discipline (the root cause of this whole night)

The recipe already shipped `DEFAULT_MAX_NEW_TOKENS` plus three overlay patches, and
it never fired: spark3's `start.sh` was from 09-26 15:33, **older than the feature
commit `a49c3a5` (09-27 08:22)**, because only `.env` had been synced. The switch
was set with no wiring behind it.

**Sync the KIT (`start.sh` + `overlay/`), never just `.env`.** Verify by checksum,
not by grep count. Overlay files are mounted over vLLM's own modules, so confirm the
target paths exist in the image tag first and that the diffs are small (10/7/6 lines
here) — they are the image's own files plus the patch.

