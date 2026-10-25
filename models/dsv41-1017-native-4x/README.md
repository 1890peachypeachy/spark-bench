# dsv41-1017-native-4x — Mia's AI Lab 4x DGX Spark TensorFold recipe (native FP8)

Status: **staged, not yet live** (prep running 2026-10-25).
Recipe repo (upstream): `MiaAI-Lab/DeepSeek-V4.1-Flash-1017-4x-DGX-Sparks-TensorFold` @ `6beaad9`
Our fork: `1890peachypeachy/DeepSeek-V4.1-Flash-1017-4x-DGX-Sparks-TensorFold`
Local clone on Mac: `~/recipe-db/DeepSeek-V4.1-Flash-1017-4x-TensorFold/`
Staged on spark3: `/var/tmp/dsv41-native-recipe/`

## What this lane actually is

| | live `dsv41-tf4-ablit` | this recipe |
|---|---|---|
| Model | DeepSeek-V4.1-Flash-1017 **EXL3 3.5bpw** (LibertAI/tonyd2wild) | DeepSeek-V4.1-Flash-1017 **native FP8 / MXFP4**, DeepSeek's own release |
| Engine | TensorFold v0.3.5 (`0a0b69a5`) + patches 0003/0004, from tonyd2wild recipe | TensorFold `5940208` + **25 Mia patches** (0001-0025) |
| Served name | `GLM-5.3-Flash-EXL3` | `GLM-5.3-Flash-EXL3` (deliberately identical — Hermes needs no change) |
| Context | 262,144 | 262,144 (recipe default is 1,048,576; Victor's standing 256K constraint) |
| Vision / video | no | **yes** — image_url + video_url, vision tower on rank 0 |
| DSpark drafts | no | **yes** — checkpoint's own draft blocks |
| Weight location | local NVMe per node (`/var/tmp/tf1017`, NFS to spark4) | NFS from spark3 (`/var/tmp/models`, export `dsv41-nfs`) |
| Rank 0 host | spark3 | spark3 (same) |

So: not a re-run of the same thing. It is a **different weight line and a newer engine with vision, video and drafting** — same endpoint shape, so it is swappable with the EXL3 lanes rather than a separate client config.

## Why it can come up at all today

- **Checkpoint already on disk.** `/var/tmp/models/DeepSeek-V4.1-Flash-1017` = 475 GiB, 48/48 shards present, 96,085 tensors per its index, all 45 repo files size-matched against HF revision `1bae0e10`. No 510 GB download.
- **Base image already on all four nodes.** `nvcr.io/nvidia/pytorch:26.07-py3` 24.3 GB. Only the TensorFold image needs building (~5 min, no GPU).
- **Engram tables already local on every node.** `model-00047/48-of-00048.safetensors` (190 GiB) at `/var/tmp/tf1017/engram`, sha256-identical to the checkpoint's. Pointed `WORKER_ENGRAM_DIR` there so prep does not re-copy 190 GiB/node over NFS.
- **Fabric is a full mesh** on 10.73.0.0/24 with all pairs reachable, RoCE `rocep1s0f1,roceP2p1s0f1` GID 3 — the `./start.sh` (switch) path, not the ring path.
- **NFS export exists.** `dsv41-nfs` exports `/var/tmp/models` as `/export` (fsid=0) to 10.73.0.0/24 read-only.

## Settings chosen (scripts/local.sh on spark3)

```
WORKER=10.73.0.1  WORKER2=10.73.0.2  WORKER3=10.73.0.4   # ranks 1-3, fabric addresses
HF_CACHE=/var/tmp/models            # holds hub/, so the snapshot is found in place
NFS_PATH=/export                    # dsv41-nfs export root
SERVED_NAME=GLM-5.3-Flash-EXL3
PORT=8888
CONTEXT=262144                      # Victor: 256K even though the model does 1M
POOL=2097152
PARALLEL=16
WORKER_ENGRAM_DIR=/var/tmp/tf1017/engram
```

Worker targets are bare `10.73.0.x`, not hostnames: `spark1` does not resolve on spark3 at all, and `spark2` resolves via **Tailscale** (100.71.248.116) — both wrong for fabric. Each Spark has its own local username (`spark`, `spark2`, `spark3`, `spark4`), so `user@host` forms fail; bare addresses use the default user.

## Co-tenancy with Comfy

Recipe budget is ~100 GiB free per node ("weights take ~75 GiB, the caches the rest"). Comfy's guard floor is 4 GB. The recipe's own README notes the fourth Spark in *their* setup also ran unrelated workloads at ~11 GiB free and was "comfortable".

Measured MemAvailable before launch: spark3 7 GB, spark1 12 GB, spark2 16 GB, spark4 10 GB. That is **below** the recipe's 100 GiB expectation because Comfy + the EXL3 lane are resident — the EXL3 lane must come down first to free its ~40 GB/node.

Open question to settle by measurement, not assertion: whether Comfy can stay up alongside. Plan is to bring the lane up alone first, then re-verify Comfy co-tenancy the way the EXL3 lane was verified (one node at a time, guard floor intact).

## Bring-up sequence

1. `PREPARE=1 ./scripts/prepare.sh` — image build, token map, four ~80 GB rank-cache weight files, served folder, NFS volumes, NFS checks.
2. Take down `dsv41-tf4-ablit` (frees ~40 GB/node; only one TF lane can hold all four nodes).
3. `./start.sh` — ranks 3→1 then 0, waits for `/v1/models`, runs the recipe's own smoke test.
4. Verify independently: chat canary, math, tool call, `/v1/models` shows ctx 262144 and the served name, vision (image_url) and video (video_url) since those are this stack's differentiators.
5. Register as a spark-lane lane with an honest label, and confirm sparkDash sees it.
6. Re-test Comfy co-tenancy on one node, then all four if it holds.

## Rollback

`./stop.sh` on spark3, then `spark-lane up dsv41-tf4-ablit` (~2 min) — stock/ablit EXL3 caches are intact at `/var/tmp/tf1017/cache*`. Nothing about this recipe mutates the EXL3 trees: it writes only under `/var/tmp/models/tensorfold-dsv41/` and its own container name `dsv41-1017-tf`.

## Risks / unknowns

- **Not a documented weight/engine pairing?** No — unlike the EXL3 lane, this recipe is *designed* for exactly this checkpoint at `1bae0e10`. It is the supported configuration.
- **RAM headroom.** The recipe warns below 100 GiB. With Comfy resident we will be under that; watch for OOM during load (the crash-forensics wedge pattern). Start with Comfy up but be ready to stop it per node.
- **Disk on spark3.** `/` is 88% / 444 GB free. New writes: image ~25 GB, four rank caches ~320 GB total (on spark3's `/var/tmp/models/tensorfold-dsv41`), token map. That is ~345 GB against 444 GB free — tight but fits. spark4 has only ~81 GB free but receives **no** new bulk data (it reads over NFS; Engram already local).
- **First load is slow.** ~75 GiB/node over NFS plus cache baking; the recipe allows WAIT_TIMEOUT 2400 s.
- **NFS volume identity.** `dsv41-hf` will be created on the three workers; if one already exists naming a different export, prepare dies and names it.
