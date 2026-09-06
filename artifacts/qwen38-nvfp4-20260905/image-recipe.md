# Qwen3.8-Flash-Next-NVFP4 TP4+EP serve — image & launcher recipe research

## Goal
Produce the exact build recipe (Dockerfile + patch vendor list + quad launcher) to serve nvidia/Qwen3.8-Flash-Next-NVFP4 on our 4× DGX Spark (GB10, sm_121) as ONE vLLM endpoint, TP4 + expert-parallel. Jun's full spec is quoted at the bottom — treat it as binding requirements, verify each against reality.

## Context
- Cluster: forge (head, .1) + anvil/ember/flame (.2/.3/.4). Wired CX7 fabric rail B: 192.168.10.0/24 on iface enP2p1s0f1np1, HCA roceP2p1s0f1. Management/ssh via tailscale hostnames; BULK transfers only over 192.168.10.x.
- Reference for our proven TP4 patterns: /home/jun/git/spark-bench/artifacts/astra-perf-20260905/launcher.snapshot.sh (GLM EXL3 TP4 launcher — NCCL 2.30.7 host-staging, GID auto-detect, drop_caches, crash-log snapshotting, per-rank /tmp patch mounts). Read it.
- Model download to /home/jun/models/qwen38-flash-next-nvfp4 on forge is ALREADY RUNNING (do not restart it; you may check its log). 132.7 GB, 25 files, includes 53.7GB model-fp8-mtp-ple.safetensors.
- Our NCCL: pip NCCL 2.30.7 staged at ~/nccl-2.30.7 on each node (stock image NCCL breaks this fabric). GLM launcher preloads it via LD_PRELOAD.
- Watchdogs to coordinate around (do not modify, just document): glm-cluster-watch on eva-core box, spark-forge-watchdog timer.

## Tasks
1. Verify the three patch repos exist and read them:
   - https://github.com/blazux/qwen3.8-Flash-DGX
   - https://github.com/getrefined/Qwen3.8-Flash-Next-NVFP4-vLLM-DGX-Spark (3-line PLE FP8 resolver)
   - https://github.com/tsw2k/Qwen3.8-Flash-Next-Quad-DGX-Sparks (4-node launcher / NCCL / nofile / EP)
   Extract: exact patch files, which vLLM version/ tag they target, PLE resolver lines, exact-topk/persistent_topk fix, QSA/GDN Spark fixes, launcher env (NCCL_IB_ROCE_VERSION_NUM=2, ADDR_RANGE, HCA, SOCKET_IFNAME, GLOO, NO GID_INDEX), nofile ulimit, EP flags, MTP speculative-config, PLE mmap envs.
2. Check base image vllm/vllm-openai:qwen38-flash-next exists on Docker Hub (or wherever); record digest. Check the model card's stated vLLM commit d4d703caf908786416585ceb1f369e2e0363358b — is it in the image? If repos conflict with Jun's spec, report the conflict; do not silently drop requirements.
3. Read the model card (https://huggingface.co/nvidia/Qwen3.8-Flash-Next-NVFP4 resolve/main README.md + config.json + generation_config) — official flags, context length, chat template, tool parser expectations, MTP config.
4. Write deliverables under /home/jun/git/spark-bench/artifacts/qwen38-nvfp4-20260905/:
   - Dockerfile.qwen38-gb10 (base image digest-pinned + vendored patches applied via COPY from a patches/ dir you populate by fetching raw files)
   - patches/ directory with the actual patch files + a PATCHES.md mapping each patch to its source repo + commit + why
   - launch-qwen38-tp4.sh — adapted from our GLM launcher shape: preflight (nvidia-smi, mem, disk, CX7 link, MTU, digest match across ranks, weights present, drop_caches attempt with sudo-or-skip), NCCL staging, workers-first launch order (rank 1,2,3 then head after ~15s), crash-log snapshotting, /tmp patch mounts pattern, port 8000 (GLM owns 18888), served-model-name qwen3.8-flash-next, EP mandatory, max-model-len 262144, gpu-memory-utilization 0.80, MTP spec config, cudagraph FULL_DECODE_ONLY sizes [1,2,4,8], reasoning-parser qwen3, tool-call-parser qwen3_coder
   - PREFLIGHT-CHECKLIST.md mapping every line of Jun's spec to where it's satisfied (or a conflict note)
5. Do NOT: build images, run docker, ssh to the sparks beyond read-only checks of forge (the model download is the only active job), start any serve, take GLM down, or modify anything outside the artifacts dir. No commits to spark-bench (leave files uncommitted).

## Done when
/home/jun/git/spark-bench/artifacts/qwen38-nvfp4-20260905/image-recipe.REPORT.md exists, first line status: success|blocked|failed, listing what was verified (repo commits, image digest, model card requirements), the deliverable files, any spec-vs-reality conflicts, and the exact build + fanout + boot runbook for Depths to execute.

## Jun's spec (binding)
Serve on 4x GB10 as one endpoint; TP4+EP mandatory; vLLM only; no TP2 pairs. CX7 RoCE, aarch64, CUDA 13. One NVMe copy per node, rsync fan-out over CX7 (~16 Gbps), never scp 120GB over ssh. drop_caches before loads. Docker nofile 1048576, ipc host, network host, gpus all. NCCL: no GID_INDEX; ROCE_VERSION_NUM=2 + ADDR_RANGE + HCA + SOCKET_IFNAME + GLOO. Quantization modelopt. GB10 patches: PLE FP8 resolver, VLLM_PLE_MMAP=1 (~48GB table on NVMe), exact-topk/persistent_topk determinism fix, QSA/GDN Spark fixes. Pin image digest on all 4 nodes. Boot order workers then head. OOM fallback gpu-mem 0.75-0.78 or PIECEWISE with PLE/QSA/GDN splitting ops. FlashInfer CUTLASS Xid 31 on sm121 → --moe-backend marlin. Env: PLE mmap workers 32, prewarm, FP8 checkpoint, TORCH_CUDA_ARCH_LIST=12.1f, CUTE_DSL_ARCH=sm_121a, FLASHINFER_CUDA_ARCH_LIST=12.1a, NCCL_CROSS_NIC=1. Serve flags per spec (max-num-seqs 16, mnbt 8192, chunked prefill, prefix caching, mtp k=2). Success bar: /v1/models, temp0 3× byte-identical, NIAH 4k/32k/128k, tool call, SS >=28 (target 31), agg >=90@8 stretch 157@16, MTP accept >=0.80, KV pool ~millions. 1M YaRN NOT default. Report: digest, flags, SS/agg tok/s, KV pool, MTP accept, extra patches needed.

## Known gotcha: prefix caching under mamba align mode (found 2026-09-05, post-recipe)

`--enable-prefix-caching` is in the serve spec, but out of the box **you will see 0% prefix-cache
hits for any shared prefix shorter than one mamba block**. Mechanism: this hybrid (QSA attention +
GDN/mamba) defaults to `mamba_cache_mode=align` — the mamba state is only snapshotted when a
scheduler step's last token lands exactly on an 800-token block boundary (vLLM forces the attention
block size to 800 to match the mamba page). With `--max-num-batched-tokens 8192`, a typical agent
system prompt (1–3k tokens) prefills in a single chunk that ends off-boundary, so no snapshot is
ever written and every repeated prefix pays full prefill.

Verified on this image (vLLM 0.1.dev20073+g8e685d198):
- 12-round agentic probe, ~1.5k shared prefix: 0.0 hits (stock template AND alternative templates —
  template-independent).
- ~9.8k-token shared prefix (crosses a block boundary): cold 0 hits / 6.5s, warm +8,800 hits /
  0.4–0.5s (~16x faster). The cache works; the alignment quantum just prices short prefixes out.
- **`--mamba-cache-mode all` does NOT work for this model**: the engine logs "Hybrid or mamba-based
  model detected without support for prefix caching with Mamba cache 'all' mode: falling back to
  'align' mode" and silently stays in align. Don't rely on the flag.

Workarounds until the granularity lands upstream: shrink the alignment quantum if your build allows
(`--mamba-block-size` / `--prefix-match-unit` — check the page-size constraint first), or shape
traffic so shared preambles are canonicalized to 800-token multiples. Verify with
`vllm:prefix_cache_hits_total` / `vllm:prefix_cache_queries_total` from `/metrics`, and confirm with
a wall-clock resume test (warm resume should be ~16x faster than cold prefill), not just the meter.
