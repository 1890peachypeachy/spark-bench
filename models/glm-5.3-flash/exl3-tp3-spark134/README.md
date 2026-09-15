# GLM-5.3-Flash-EXL3 TP3 — spark1+spark3+spark4 (head spark3)

Cutover 2026-09-15. Replaced the TP2 (spark3+4) lane. Source recipe:
`MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks` @ `a35eaab`
(fork: `1890peachypeachy/GLM-5.3-Flash-EXL3-2x-DGX-Sparks`), launcher
`start-tp3.sh`, vendored TP3 overlays from FlyCockpit (MIT) via her repo.

## Measured (our fleet, same-day A/B, bench_decode.py runs=5 400tok temp0 thinking-off)

| | structured | prose | TTFT | accept | KV tokens @1M |
|---|---:|---:|---:|---:|---:|
| TP2 (spark3+4) | 63.7 | 27.3 | 0.34/0.28 s | 0.938/0.34 | ~14 GiB cap |
| **TP3 (spark1+3+4)** | **85.8** | **37.1** | 0.25/0.21 s | 0.935/0.34 | **2,753,284 (2.75× @1M)** |

Raw JSON in `results/2026-09-15-glm53-tp{3,2}*decod*.json`. Matches Mia's receipts
(87.8/39.6) within 2% — first cross-kit transfer that held on our hardware.

## Bring-up

    # on spark3 head:
    cd ~/GLM53-TP3          # clone of the fork @ a35eaab; .env + .env.tp3 alongside this README
    ./start-tp3.sh          # worker-first internally; ~15-20 min cold boot (320B MoE + JIT warmup)
    ./start-tp3.sh status | logs | stop

Endpoint: `http://100.99.120.29:8888/v1` (tailscale) / `10.73.0.3:8888` (fabric),
served id `GLM-5.3-Flash-EXL3`, 1M ctx, fp8 KV, GPU_UTIL 0.80, DFlash2 k=7 + MTP 2,
`DFLASH_DRAFT_TP=1`, TP3_HEAD_OVERRIDE=66, expert parallel on, MM data-mode.

## TP3-specific traps (verified the hard way, 2026-09-15)

1. **NFS_SHARE=0 for our switched CRS504 fabric.** Her `.env.tp3.example` NFS route
   never materialized the share container here; all 3 ranks already hold complete
   EXL3 weights locally (120 shards). Set `NFS_SHARE=0` + explicit
   `WORKER_CACHE_DIR`/`WORKER2_CACHE_DIR`.
2. **The padded drafter dir must be replicated to every worker.** Under
   NFS_SHARE=0, `prepare_tp3_draft` builds `~/.cache/huggingface/glm53-tp3-draft/<rev>/`
   (GQA-padded 36/9 config + hardlinked blob) on the HEAD only, but the launcher
   still resolves `DFLASH_MODEL_DIR` to that path inside every rank container.
   Workers die with pydantic `SpeculativeConfig ... Invalid repository ID`.
   Fix (done during cutover, in `.env.tp3`-adjacent state): on head,
       REV=dc77ff1c99eeb2df044ee3d4f0094eb033fee410
       for h in spark@10.73.0.1 spark4@10.73.0.4; do
         ssh $h "mkdir -p ~/.cache/huggingface/glm53-tp3-draft"
         rsync -aL ~/.cache/huggingface/glm53-tp3-draft/$REV/ $h:~/.cache/huggingface/glm53-tp3-draft/$REV/
       done
   `-aL` is required: the safetensors is a hardlink into ../../blobs which does
   not resolve from the receiver path.
3. **Stop before launch.** A squatting head container holds MASTER_PORT 29521 and
   the launcher aborts with `port 29521 is held`; use `./start-tp3.sh stop` first.
4. Recipe stamp moved at a35eaab → head auto-rebuilds the exl3 image (~4 min).
   Workers refresh from the head image automatically (launcher compares layer hashes).
5. `GLM53_MIXED_PREFILL_CHUNK=skip` pinned to match the TP2 production behavior;
   her fair v5 scheduler was 2 days old at cutover — A/B it separately later.

## Rollback

TP2 containers (`glm53-exl3-head` on spark3, `glm53-exl3-worker` on spark4) are
stopped, NOT removed. `cd ~/GLM-5.3-Flash-EXL3-2x-DGX-Sparks && ./start.sh`
restores the 2-node lane (spark1 free again for the Qwen cluster lane, whose
containers are likewise kept on spark1/2: `~/bilikaz-qwen38-cluster/run.sh`).
