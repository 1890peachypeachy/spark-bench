# DGX Spark lane artifact inventory (2026-11-06)

Purpose: know exactly which disk/image artifact belongs to which `spark-lane` lane, so a
cleanup never deletes something a lane needs at bring-up. Verified live on spark1-4; every
"NEEDED" row was traced to a lane's kit config or launcher, not guessed.

## Ground rules found while tracing

1. `/var/tmp/models` on spark1/2/4 is an **NFS mount of spark3's export** (autofs). Its 1.6 TB
   is spark3's disk. Pruning it on a worker frees nothing.
2. spark4 has a **916 GB** NVMe; spark1/2/3 have 3.7 TB. spark4 runs at ~95% full.
3. An image can be tagged twice: `tensorfold-glm53:v0.6.0` and
   `ghcr.io/miaai-lab/glm-5.3-flash-exl3-2x-dgx-sparks-tensorfold:<none>` are the **same image id**
   (`7f8f1b38...`) on spark3. Removing one tag frees no space.
4. GPU memory on GB10 is the host RAM pool: a TP4 lane consumes ~84 GB/node, so ~31-33 GB
   "available" on every node is normal, not a leak.

## Lane -> artifacts (what `spark-lane up <lane>` requires)

| Lane | Nodes | Kit / launcher | Image | Rank caches / weights |
|---|---|---|---|---|
| glm53-tp3 | spark1,3,4 | `/home/spark3/GLM53-TF3` | `tensorfold-glm53:v0.6.0` | weight NFS export on spark3 |
| glm53-tp4 | spark1-4 | `/var/tmp/glm53-tf4-trial` | `tensorfold-glm53:v0.6.0` | `SPILL_DIR=/var/tmp/tensorfold-spill` (51 GB/node) |
| glm53-tp4-ablit | spark1-4 | `/var/tmp/glm53-tf4-trial` | `tensorfold-glm53:v0.6.0` | abliterated weight variant |
| glm53-tf2 | spark3,4 | `/home/spark3/GLM53-TF` | `tensorfold-glm53:v0.6.0` | weight NFS export |
| dsv41-native | spark1-4 | `/var/tmp/dsv41-native-recipe` | `tensorfold-dsv41:native-01bb6e93ba8c` | `/var/tmp/tf1017/engram` (190 GB/node) |
| dsv41-tf4 | spark1-4 | `/var/tmp/tf1017` (+`config.spark-fleet.env`) | `tensorfold-dsv41:*` built FROM `nvcr.io/nvidia/pytorch:26.07-py3` | `/var/tmp/tf1017/cache` 65 GB, engram 190 GB |
| dsv41-tf4-ablit | spark1-4 | `/var/tmp/tf1017` (+`config.spark-fleet-ablit.env`) | same | `/var/tmp/tf1017/cache-ablit` 65 GB, engram 190 GB |
| dsv41-tf2 | spark3,4 | `/var/tmp/tf1017-tp2` | built in that root | `cache` 99 GB + `cache-r1` 99 GB (spark3), 103 GB (spark4) |
| dsv41-tf3 | spark1,3,4 | `/home/spark3/dsv41-3x` (`.env`) | `dsv41-3x-spark:local` (33 GB) + `lmsysorg/sglang:dev-dsv41` base | `ENGRAM_DIR=/var/tmp/dsv41-engram-1017-tp3` (63 GB), `/var/tmp/nccl-2.30.7` |
| comfy-engine | spark2 | `~/comfy-build`, `/var/tmp/comfy` | `spark-comfy:v0.38.1` | `/var/tmp/comfy` (138 GB) |
| comfy-studio-4x | spark1-4 | Studio comfy launcher | `spark-comfy:m-fd7639f4` | `/var/tmp/comfy` (138 GB) |
| studio-12 / studio-2 | spark2 (+spark1 worker) | `~/studio-src/Imagination-Studio`, `~/ImaginationStudio` | none (Python app) | uses the comfy root |
| glm53-gr8 | spark1-4 | `/var/tmp/gr8/repo` | — | **NOT STAGED** (path absent on spark3; `up` would fail the kit step) |
| glm53-vllm4 | spark1-4 | `/var/tmp/glm53-recipe-tp4` | `glm53-roce:v11-b58f34ea` | **image removed 2026-10-10** (needs rebuild/pull before `up` works) |

## Orphans — referenced by no registered lane

| Artifact | Where | Size | Note |
|---|---|---|---|
| `/var/tmp/dsv41-3x-worker` | spark4, spark1 | 63 GB each | no reference in any kit or spark-lane |
| `/var/tmp/glm-compile-cache` | all 4 | 3.3 GB each | GLM kernel cache; regenerates on next boot (slower cold start) |
| `/var/tmp/glm-legacy` | all 4 | ~280 MB each | no reference |
| `/var/tmp/glm53-flash-4x-spark` | all 4 | ~203 MB each | no reference |
| `/var/tmp/tf1017-ablit` | spark1,2,4 | ~196 MB each | no reference (the live ablit cache is `/var/tmp/tf1017/cache-ablit`) |
| `/var/tmp/dsv41-4x-spark` | spark2 | 48 GB | kit at `/home/spark3/dsv41-4x` does not name it — verify before removing |
| image `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` | spark1, spark3 | 18.8 GB | no reference in spark-lane |
| image `ghcr.io/miaai-lab/glm-5.3-flash-2x-dgx-sparks:exl3-instanttensor` | spark1 | 20.9 GB | `GLM53_IMAGE` is defined but never used |

## Unverified / do not delete yet

- `/var/tmp/dsv41-engram` (spark3, 63 GB) and `/var/tmp/dsv41-engram-1017` (spark2, 48 GB):
  the dsv41-tf3 `.env` names `-1017-tp3`; the other two appear only in an older build script.
  They look stale but I have not proven it.
- `vllm/vllm-openai:nightly-aarch64` (spark3, 19.9 GB): not named by spark-lane; likely the vLLM
  build base if `glm53-vllm4` is ever rebuilt.
- `nvcr.io/nvidia/pytorch:26.07-py3` (all, 24.3 GB): **build base** for the TensorFold image.
  Needed to rebuild images, not to run them.

## Reclaimable per node (orphans only, measured)

- spark4: ~67 GB (dsv41-3x-worker 63 GB + 3.3 GB compile cache + ~0.7 GB small dirs)
- spark1: ~85 GB (3x-worker 63 GB + instanttensor 20.9 GB; anemll image is on spark1 too)
- spark3: ~86 GB incl. anemll 18.8 GB (leave vllm + tf1017-tp2 + engram-1017-tp3)
- spark2: ~49 GB (dsv41-4x-spark 48 GB, pending the check above)

## Known gaps in `spark-lane` (cause of 2026-11-06 failures)

1. `up` does not verify the image exists on **every** node before launch; spark4 tried to pull
   `tensorfold-dsv41` from Docker Hub and was denied.
2. `up` does not verify per-node **Engram tables**; spark2 came up empty and rank 2 died with
   `MissingEngramTable`.
3. `start.sh` stops any running ranks before relaunching, so a manual `start.sh` while a lane is
   live tears that lane down.
