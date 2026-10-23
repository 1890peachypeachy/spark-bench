# Spark3 reclaim — 2026-10-23T03:24Z

Freed **~902 GiB** on spark3 (302 G → 1.2 T free, 92% → 69% used).
Live lane (`dsv41-tp4` → `dsv41-head` on spark3 + workers) stayed up throughout:
`/v1/models` 200 before and after, `dsv41-head` healthy, `dsv41-nfs` running.

## Gate applied

A tree was deleted only if BOTH held:

1. **Not reachable from `spark-lane`**: absent from `ALL_LANE_IDS`, and no live kit
   referenced it (`GLM53-TF`, `GLM53-TF3`, `glm53-tf4-trial`, `glm53-recipe-tp4`,
   `dsv41-4x`, `dsv41-3x`, `glm53-tf4`, gr8 repo, comfy). Grep of all of
   `~/recipe-db` plus the registry returned zero hits for each path.
2. **Recoverable**: either publicly re-downloadable at a recorded repo+revision, or a
   byte-identical duplicate of a copy kept on spark3 or another Spark. Verified with
   `st_nlink`/inode identity, shard counts and byte totals — not with a `du` eyeball.

Zero open file handles under every target (`/proc/*/fd` scan), and no container
bind-mount pointed inside one (only the two `~/.cache` / `/var/tmp/models` parents are
mounted, which is why those were checked specifically).

## Deleted

| tree | freed | why it was safe |
|---|---|---|
| `~/models/GLM-5.3-Flash-EXL3-TR3-4bpw` | 163.6 G | independent copy, `nlink=1`; the 120 shards are byte-identical to the HF-cache blobs **kept on this node** (`~/.cache/huggingface/hub/models--…TR3-4bpw`, 175.76 GB, 153 blobs, intact after) |
| `~/models/GLM-5.3-Flash-NVFP4` | 181.3 G | `nlink=1` standalone; identical trees on **spark1 and spark2** (182 G, 120 shards each). Upstream `Mia-AiLab` copy 401s, but the artifact survives on two nodes |
| `~/.cache/…DeepSeek-V4-Flash-Vision-Exp` | 156.3 G | public `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` (48 shards, 156.3 GiB) — matches exactly; repo is ungated |
| `/var/tmp/models/Step-5-Preview-Spark` | 179.6 G | public `0xSero/Step-5-Preview-Spark`, rev `51a46a7f`, ungated. No recipe/kit in `~/recipe-db` references it |
| `/var/tmp/tensorfold-spill` | 125.8 G | TensorFold KV/spill scratch; `SPILL_GIB=0` in the live TF4 kit, regenerated on next boot, holds no weights |
| `~/.cache/…Qwen3.8-Flash-Next-NVFP4` | 21.7 G | `Mia-AiLab` repo now 401s, **but** 124 G copies exist on spark1 and spark2 (5.6× this one) |

A 41-byte root-owned `refs/main` stub survived the Vision-Exp `rm` (root-written by an
earlier container run). Moved to `~/backups/spark3-reclaim-20261022/vision-exp-stub-refs`,
not deleted.

## Deleted nothing / kept on purpose

| tree | size | reason |
|---|---|---|
| `/var/tmp/dsv41-engram` | 63 G | **generated**, not downloadable — engram repack for the pre-1017 checkpoint generation. Regeneration is hours of compute. Also `ENGRAM_DIR` in `.env.tp4` still names a `/var/tmp/dsv41-engram-1017` path that does not exist, so this tree is the only surviving artefact of that generation. Decide separately. |
| `~/qwen3-tts` | 12 G | hand-built sidecar venv (TTS), not a Spark lane weight |
| `~/.ollama` | 5 G | runtime store; ollama inactive |

## Re-download commands

```bash
hf download nvidia/GLM-5.3-Flash-NVFP4 --local-dir ~/models/GLM-5.3-Flash-NVFP4          # different layout; NOT our copy — use spark1/spark2 instead
hf download deepseek-ai/DeepSeek-V4-Flash-Vision-Exp --revision 6821d6ad --local-dir <dest>
hf download 0xSero/Step-5-Preview-Spark --revision 51a46a7f --local-dir <dest>
# TR3: restore from this node's own cache, no download needed:
#   convert-to-hf-cache.sh --src ~/.cache/huggingface/hub/models--Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw
# Qwen38-NVFP4: rsync from spark1:/home/spark/models/qwen38-flash-next-nvfp4 over 10.73.0.1
```

Full per-item record (bytes, file counts, config sha256, upsteam revision) was written to
`spark3:/tmp/spark3_delete_record/` before deletion.

## Also noted but NOT touched (docker image store)

`docker system df` reports 109.3 GB reclaimable (15 of 18 images unused: `dsv41-3x`,
2× `canary-pre-*`, `exl3-instanttensor`, `tonyd2wild/vllm-glm53`, `anemll dspark`,
`vllm nightly`, 3 dangling). Left alone because the `glm53-tp3`/`glm53-vllm4`/
`glm53-tf2` arms are live registry entries and their images must stay. Pruning is a
separate call.