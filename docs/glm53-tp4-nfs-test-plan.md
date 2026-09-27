# GLM-5.3-Flash TP4 on NFS — test plan (phase 1: prove the mechanism)

**Status:** planned. Nothing torn down, nothing wired to sparkDash. Lane `dsv41-tp4` is LIVE.

**Goal:** prove GLM weights can be served over NFS (head exports, workers read over the
RoCE fabric) *before* we build a launchable lane for it. Wiring to sparkDash / adding it to
`spark-lane` is a **separate, later step** — explicitly out of scope here.

---

## 0. Sequencing — read this first

The lane we are about to park (`dsv41-tp4`) is what serves the *assistant itself*
(`deepseek-v4.1-flash`). Bringing it down kills the session that is doing the work.

1. Switch the assistant to a cloud model. **Verify the switch** (reply round-trips on cloud,
   not just a config edit).
2. Only then park the lane.
3. Test. Then restore, or continue to a boot attempt.

## 1. Baseline to restore (verified 2026-09-26)

| | |
|---|---|
| lane | `dsv41-tp4` — nodes spark1, spark2, spark3, spark4 |
| endpoint | `http://100.99.120.29:8000/v1`, model `deepseek-v4.1-flash`, ctx 1048576 |
| containers | `dsv41-head` (spark3), `dsv41-worker` (spark1/2/4) |
| image | `dsv41-4x-spark:canary-roce` |
| deployed kit | `/home/spark3/dsv41-4x` @ `363b852` (= our fork `origin/main`) |
| fork | `1890peachypeachy/DeepSeek-v4.1-Flash-DGX-Sparks` (upstream MiaAI-Lab) |

**Restore = `spark-lane up dsv41-tp4`.** Park = `spark-lane down dsv41-tp4` (verifies it
really stopped; deletes nothing). Control script: `~/recipe-db/spark-bench/ops/spark-lane`.
Census first, always: `spark-lane status`.

## 2. The NFS pattern we are copying (already in production)

spark4 is rank 3 of the live DSV4.1 lane and holds **no** local checkpoint (~516 G vs 116 G
free). It reads weights over NFS:

```
worker volume dsv41-weights-4x -> /models/DeepSeek-V4.1-Flash
  type=nfs  addr=10.73.0.3  nfsvers=4.2  ro  nconnect=8
  rsize=1048576  wsize=1048576  hard  timeo=600
head export: /export 10.73.0.0/24(ro,sync,no_subtree_check,no_root_squash,insecure,fsid=0)
exporter container: dsv41-nfs (image dsv41-nfs:local) on spark3, over the FABRIC not LAN.
```

So this is proven, not speculative. For GLM it is **forced**: local needs ~371 G/node
(NVFP4 base 182 G + converted target ~185 G + 2 drafters) and spark4's `/home` is 916 G
total with 116 G free.

## 3. GLM lane facts (for the second phase)

- Recipe: `~/recipe-db/GLM-5.3-Flash-4x-DGX-Spark-TP4` (mirror of `knapcio/...`, MIT).
  Engine is **vLLM** TP4, not SGLang. Port **8093**, bind `127.0.0.1`, served as
  `GLM-5.3-Flash-FP8`.
- Already on the fleet: base image `ghcr.io/tonyd2wild/vllm-glm53-flash:sm121-v11-dflash2`
  (all 4 nodes), NCCL 2.30.7 dir (all 4), drafter `~/models/GLM-5.3-Flash-DFlash2` (2.2 G).
- Weights needed: `nvidia/GLM-5.3-Flash-NVFP4` @ `09b04e5e…` (120 shards on spark1/2/3,
  **0 on spark4**) + `incoai/GLM-5.3-Flash-DFlash2` @ `bf582e4e…`, then a CPU conversion
  (`scripts/build_lossless8.sh` + `drafter_fp8.py`) producing the mixed-quant target and an
  FP8 drafter. Base and overlay must share one filesystem (hardlinks) — NFS satisfies that.
- **Version check before conversion:** our copy reports `quant_method: modelopt` (right
  family) but its revision is unreadable locally. The recipe pins an exact revision and its
  assembly uses hardlinks + a sentinel, so a wrong base is not recoverable by inspection.

## 4. The two probes that must run before any boot

Both read-only, no lane state changed. Bounded so they cannot starve the live lane.

**P1 — fabric read throughput over NFS, worker-side.** Export a *scratch* directory (not a
weight dir) from the head, mount it read-only on spark4, read a few GB with
`dd iflag=direct` and with warm cache, and compute GB/s. Question answered: how long would
~3 × 182 G of rank-side checkpoint reads actually take? Their 271 s cold / 129 s warm boot
figures assume **local disk**, so they do not transfer.

**P2 — does `POSIX_FADV_DONTNEED` actually drop NFS client cache?** This is the one that
matters. The recipe's fast loader (`overlay/glm_fast_load.py`, `GLM_FAST_LOAD_DROP_CACHE=1`)
drops each range after reading precisely so the load does not fill **unified** memory with
~100 G of cached checkpoint pages — the page-cache wall our GLM notes already document.
`posix_fadvise(DONTNEED)` is frequently a no-op on NFS. Test: read a large file over NFS
with the advice on and off, watch `MemAvailable` / `Cached` and whether the cache is
released. If it is not, that changes the boot plan (or the mount options), not just the timing.

**P3 — as a corollary:** does `nconnect=8` actually aggregate? Our only prior number is
~450 MB/s single-stream rsync; 8 parallel TCP connections should be far better. Measure,
do not assume.

## 5. Design choice to settle with the probes

- **Option A (least invasive, preferred):** NFS-mount the head's weight dir on each node at
  the **same absolute path**, and let the recipe's existing `-v $MODEL_DIR:/model:ro` bind
  pass it through. **Zero launcher edits.**
- **Option B:** docker volume with the NFS options (what DSV4.1 does). More moving parts
  (stale-volume trap: a stale worker volume blinds the worker even with a healthy export).

## 6. Known traps carried over from DSV4.1 (each one cost real time)

1. Export must be up **before** any rank starts.
2. Stale worker volume/NFS mount = worker silently blind.
3. Teardown must **never** remove the shared exporter (`dsv41 stop.sh` already carries this fix).
4. The recipe's `compact_mem` needs `NOPASSWD` sudo we do **not** have — it silently no-ops.
   Our own ritual applies instead: `vm.swappiness=0`, `swapoff -a && swapon -a`,
   `drop_caches`, plus a flusher for the whole boot window. Skipping it hung a GLM boot before.
5. Never build on a serving head.

## 7. Open quality risk (unrelated to NFS, but decides whether we keep the lane)

The recipe starts from the **ModelOpt NVFP4** checkpoint — the build family our fleet already
abandoned for intermittent corrupted token IDs (vLLM #54150; reproduced on our rig as
ModelOpt 4/9/8 U+FFFD on the Hangul probe vs RedHat 0/0/0). Its conversion re-encodes the
non-expert weights but **leaves the routed NVFP4 experts unchanged**. Their `qeval 75/75`
is a different gate and does not refute this. First test if we boot it: the Hangul probe.

## 8. Explicitly NOT in this phase

- No sparkDash wiring, no new `spark-lane` profile, no Hermes provider entry.
- No `.env` committed as "the recipe" until a boot succeeds.
- No weights written to spark4.