# Spark disk cleanup 2026-11-22 (the owner)

Outcome: spark4 113 -> 602 GB free (916 GB drive). Others: spark1 764 -> 828, spark3 725 -> 798, spark2 unchanged (~2 TB; the gr8 KV store refilled to its 100 GB cap after the lane restart, which offsets small gains).

What was done, in order:
1. `disk_map.sh` (read-only du/docker map per node) + sparkDash 2.91 "Remove agent junk" scan + delete advisor (`tier1_advise.py`) to rate candidates.
2. Tier 1, regenerable caches (`tier1_delete.py`, exact paths, guarded; manifest `tier1-manifest.json`): old VS Code servers, pip, Playwright, uv caches on spark1-3.
   Real gain only ~9 GB, not the 27 GB the scan listed: uv hard-links its cached wheels into virtual environments, so deleting the cache frees almost nothing while the venvs exist.
3. `spark-ds41f:1107` (23.9 GB unique per node, the owner's 2026-11-07 experiment, crashed 2026-11-09): archived from spark1 to the NAS
   (`/volume1/homes/hermes/spark-models/spark1/retired-20261122-spark-ds41f/`, sha256 a25d82d17a859b0fd6f8b7e0f7b09a6f003b1f313c1a9d8a931db2deca3f2044 verified on both ends),
   then removed with its stopped containers from all four nodes (`remove_ds41f.sh` refuses unless the image id matches the archived one).
4. spark4 payload drop (`verify_replicas.py` then `spark4_drop.sh`): ComfyUI `h3`/`models`/`yue2` and DeepSeek `tf1017/{engram,model,cache}` + the 27 GB `spark-comfy` image.
   Replicas verified by file names + sizes on peers before deleting. Restore procedure: `ops/LANE-INVENTORY.md`.

Lessons:
- Docker's "reclaimable" figure is wrong for images sharing layers: tensorfold-dsv41, tensorfold-glm53 and the pytorch base share one 24 GB stack (unique 0.77 / 0.25 GB). Use `docker system df -v` UNIQUE SIZE.
- A script fed to `ssh host 'bash -s' < script` dies at the first inner `ssh` that reads stdin (the archive silently did nothing the first time). Copy the script and run it with `ssh -n host bash file`, and give inner ssh calls `-n`.
- A guard that greps `pgrep -af <path>` matches its own SSH command line; use `pgrep -x <binary>`.
- The gr8 KV store (`/var/tmp/gr8/home/kv`, 101 GB per node) refills after every lane restart, so free-space readings jump by up to ~100 GB: compare readings taken at the same lane state.
