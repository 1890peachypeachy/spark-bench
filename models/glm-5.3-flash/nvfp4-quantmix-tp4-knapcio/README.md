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
