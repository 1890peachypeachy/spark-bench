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
