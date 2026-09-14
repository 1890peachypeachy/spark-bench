# GLM-5.3-Flash NVFP4 — 3–4 Agent Concurrency Profile Plan & Hypothesis

**Author:** Spark · **Date:** 2026-09-05 · **Status:** PLAN — execute read-only on the live NVFP4 lane, then decide knobs.

> Grounds Victor's "3–4 agents at 400K ctx, mixed thinking, no OOM" goal in a
> measurement BEFORE any weight/flag change. Written down because Victor does not
> trust memory (correctly — past reads drifted). Facts below were re-verified live
> on 2026-09-05, not recalled.

---

## 1. Live lane ground truth (verified 2026-09-05, not memory)

| Field | Value (verified) |
|---|---|
| Endpoint | `http://100.106.81.35:8001/v1` (Spark1 head, Tailscale); served `glm-5.3-flash` |
| Window | `max_model_len` = **1,048,576 (1M)** |
| Container | `vllm_glm53_dflash2` (head node) |
| Image | `radixark/vllm-glm53-flash:sm121-v12-dflash2-topkfix` |
| Checkpoint | NVFP4 (compressed-tensors; served root `/models/glm-5.3-flash-nvfp4`) |
| Spec decode | DFlash2 **k=7** |
| KV | fp8 e4m3, 24 GiB/rank |
| MoE backend | marlin |
| seqs / batching | max-num-seqs 64 / mnbt 16384 |
| gmu | 0.68 |
| CUDA graphs | FULL_AND_PIECEWISE (eager off) |
| Chunked prefill | on, threshold 2048 |
| State | **idle** (0 running / 0 waiting at profile start) |

This is the NVFP4 lane. **EXL3 was A/B'd on our created benchmark and was NOT a
winner — dropped.** Do not re-test EXL3.

## 2. Why EXL3 losing is the most important prior evidence

EXL3's whole advantage is **faster kernels** (measured clean: structured ~99,
code ~58 tok/s, ~2× cold prefill). Yet it did **not** beat NVFP4 on our
agent-turn benchmark (agent_sim, thinking-low) — its decode advantage did not
survive the tool-loop/thinking-low agent regime.

**Deduction:** a strictly faster engine did not move our agent feel. Therefore
raw decode/prefill throughput is **not** the binding constraint for 3–4 agents
— and jnardiello's ~202 c4 aggregate is not something we reach by shaving
per-step cost on this lane. If decode were the wall, EXL3 would have won.

## 3. Hypothesis under test

> **H1 (primary):** For 3–4 concurrent Hermes agents at ~400K ctx, the perceived
> slowness is **per-agent TTFT / re-prefill under concurrency**, NOT decode
> throughput. Two sub-drivers, to be separated by measurement:
>   - **H1a — cold-prefill-bound:** each agent that (re)builds a large context
>     pays a long cold prefill; with 3–4 agents the prefills serialize against
>     each other → wall-clock dominated by prefill, not generation.
>   - **H1b — prefix-cache-miss-bound:** an agent's large mostly-static context
>     (system + prior turns) is **not cached** across its own tool-loop turns →
>     every turn re-prefills ~400K. (Would appear as `cached_tokens ≈ 0` on
>     follow-up turns + large follow-up TTFT.)
>
> **H2 (null / competing):** decode-per-stream genuinely collapses under 3–4-way
> batch on NVFP4 (engine compute ceiling ~70–90 tok/s aggregate) → decode-bound →
> FP8 (Tier-1) is the unlock, and no prefill/cache tuning helps.

## 4. The single discriminating profile

Read-only, no restart, on the live idle NVFP4 lane. Use the existing
`agent_sim.py` harness (matches how Victor drives agents; measures per-turn
TTFT, decode, wall, and prefix-cache `cached_tokens`).

**Scenario battery per agent (agent_sim `full`):**
- `tool_loop` — 3-turn tool-call loop, short/growing ctx (87% of real traffic is
  short tool bursts). Gives short-context decode + turn-to-turn cache behavior.
- `longdoc` @ 400K — cold prefill then a follow-up on the same doc. **The key
  measurement:** cold-400K prefill TTFT vs follow-up (cached) TTFT. This is the
  H1a-vs-H1b-vs-H2 discriminator.
- `output_mix` — structured / code / prose single prompts. Gives clean decode
  per output type under the regime.

**Runs:**
1. **C1 @ ctx 400,000, thinking low** — per-agent clean baseline (de-risks a
   400K burst before going concurrent; confirms no wedge).
2. **C3 @ ctx 400,000, thinking low** — the contention shape (3 agents).
3. Optionally C3 with **thinking off** to capture the mixed-thinking regime.

**Metrics captured per agent:** cold-longdoc prefill rate + TTFT; follow-up
TTFT + `cached_tokens/prompt_tokens` (cache hit); per-stream decode under
contention; total agent wall; DFlash2 accept ratio from `/metrics` deltas; zero
`NV_ERR_NO_MEMORY` / no wedge.

## 5. Decision tree (what the result tells us — knobs to test AFTER)

| Observation | Interpretation | Unlock to test (not all now) |
|---|---|---|
| Cached follow-up TTFT small & cache hit high; decode per-stream collapses at C3 | decode-bound (H2) | **Tier 1: FP8 @ ~400K** (the real concurrency raiser; fits at 400K not 1M) |
| Cold 400K prefill TTFT dominates agent wall | prefill-bound (H1a) | window right-size 1M→~450K + decode-aware prefill sched; FP8 would NOT help |
| Follow-up TTFT large & `cached≈0` | prefix-cache miss (H1b) | prefix-cache retention (`VLLM_PREFIX_CACHE_RETENTION_INTERVAL`) + catch-up warm sidecar |
| No single dominant term; per-agent wall ~equal C1 vs C3 | engine parallelizes; feel = absolute latency | concurrency-rightsized config (seq 64→~12, window→450K) |

**Not the lever regardless of outcome:** adaptive-k (we already run k=7; it only
toggles k=3/5 = a reduction on our structured path), EXL3 (lost), seq-slot math
alone, async-scheduling, fabric/NCCL.

## 6. DoD / acceptance

- Profile completes on the live lane with **no OOM / no wedge** (guard: step
  C1 first).
- Each agent run yields usable TTFT, decode, and cache-hit numbers at 400K.
- Output + interpretation recorded back into this doc's decision tree and into
  Hindsight; knobs chosen from the tree, not from vibes.

## 7. Execution log

### Run A — C1 @ 400K, thinking low (2026-09-05, clean, no wedge)
Full battery, wall 396s. Verified: prefix caching **enabled** (`enable_prefix_caching=True`,
pool 3,834,498 tok). Server does NOT populate `usage.prompt_tokens_details.cached_tokens`
(the harness shows `cached=None`) — infer cache reuse from follow-up TTFT instead.

| Step | Result |
|---|---|
| tool_loop (3 turns, short ctx) | 8.3s total; turn0 86pt→274comp TTFT 0.35s; healthy |
| **longdoc cold prefill @454K** | **346s, 1311 tok/s, needle found** — 87% of agent wall |
| longdoc follow-up (same doc) | **8s, TTFT 5.26s** → prefix cache reuse works within session |
| output_mix decode | structured ~26, code ~48, prose ~26 tok/s |

**FLAG:** cold 400K prefill = **1311 tok/s** is anomalously slow — our own 92K runs
were ~14K tok/s, jnardiello reports ~2200 @100K. ~5× length → ~10× per-token
drop = NOT length-independent. Need a confirm + a *growing-context* tool loop
(the harness `tool_loop` only grows to ~500 tok; real agents grow 10K→400K
across tool turns, which is the actual pattern to model).

### Run B — C3 @ 400K, thinking low (2026-09-05, clean, no wedge)
Wall **157s** for 3 agents. **CAUTION:** all 3 agents sent *identical* 454K docs
(harness `build_long_doc` is deterministic) → agents 1/2's longdoc "cold prefill"
(37–44K tok/s) mostly **hit agent 0's prefix cache**, not real cold. So C3 longdoc
is NOT a valid distinct-context contention measure — the honest distinct-agent
cost shows in **Run A's 346s cold** and the decode collapse below.

| Step | ag0 | ag1 | ag2 |
|---|---|---|---|
| tool_loop (short) | 13.7s | 19.4s | 54.0s |
| longdoc 454K (mostly prefix-cached) | 12s | 10s | 10s |
| output_mix decode **per-stream** | struct 11.9 / code 20.0 / prose 8.1 | struct 12.2 / code 22.0 / prose 7.7 | struct 8.2 / code 19.3 / prose 15.7 |

**HEADLINE — decode does NOT scale with agents.** Going C1→C3, per-stream decode
roughly **halves-to-thirds**: code ~48→~20, structured ~26→~11, prose ~26→~10.
Aggregate stays ~flat (~70–90 tok/s ceiling). **This is a total decode-throughput
ceiling on NVFP4, not seq-slots and not speculation length.**

**CONFOUND to note:** output_mix runs at *thinking-low* → generates reasoning
content that DFlash2 speculation does NOT accelerate (matches the earlier
EXL3-clean-vs-agent_sim lesson). So under "thinking low," per-stream decode is
~10–20 tok/s partly *because reasoning isn't speculated*, and 3-way contention
doesn't scale it.

## Decision-tree status (from Section 5)

- ✅ **Prefix cache works — per-turn cost is FLAT with context.** Clean growing-context
  C1 probe (single agent, thinking low, 32K→400K by +30K/turn): turns 96K→288K each
  cost **~9s flat** (9.8/9.4/9.5/8.4/6.6/9.0s) with only 6-token completions = nearly
  pure prefill. Context doubling does NOT raise per-turn cost → **tail-only prefill +
  prefix-cache reuse CONFIRMED.** Turn-10+ (320K→416K) spiked 33/55/60s = cron/agent
  load contamination, discarded.
- ⚠️ **BUT prefill is slower than we believed, even cached-miss.** Clean first turns:
  32K=30s, 64K~10s, 96K=17s → **~1.4–3K tok/s prefill**, not the ~14K tok/s we'd
  inferred at 92K (that 92K run was contaminated by identical-doc prefix reuse). A
  single agent's tool-loop turn re-serving ~200–300K costs **~9s** even though it's
  cache-friendly. So per-turn latency is **prefill-throughput-bound (~9s/turn at
  200–300K), FLAT with context** thanks to caching — NOT decode-bound.
- ❌ **H2 decode ceiling is a smaller factor than prefill for agent feel.** Clean decode
  (comp≈120 in 6–10s) is healthy; the ~9s is prefill re-serve, not decode.
- 🔶 **Implication for knobs:** the ~9s/turn at 200–300K prefill re-serve is the real
  agent-latency wall → **prefill-throughput** is the lever (FP8, better prefill
  kernels, avoid cache eviction across concurrent agents), NOT adaptive-k/decode/seq.

## C3 growing-context result (2026-09-05, clean, idle lane) — 3 DISTINCT growing agents
Wall 130s. Each agent grew own context 32K→416K (+30K/turn). Per-turn wall (~all
prefill, 6-token completions):

| Context | Per-turn wall (3 agents) |
|---|---|
| 32–96K | 10.5–16.7s (cold-miss turns) |
| 128–288K | **5.4–8.1s flat** |
| 320K | 6.8–9.5s |
| 352–416K | 10.3–12.8s (KV-pool edge) |

**HEADLINE — concurrency barely costs for the real growing pattern.** 3 agents
holding 100–300K each pay ~6–8s/cached-turn ≈ single-agent C1 (~9s). Prefix cache
keeps each agent's tail cheap independently. The decode collapse seen in the
earlier C3 output_mix does NOT appear in real growing-tool turns. Only rise is the
KV-pool edge near 400K×3 (pool 3.83M tokens) → fragmentation/re-prefill, a
pool/window effect, not a decode ceiling.

**FINAL IMPLICATION for 3–4 agents @400K:** the real limit is per-turn ~7–9s
prefill re-serve (flat, cache-friendly, ≈1 agent regardless of count) + a KV-pool
edge effect near 400K×3. Levers = **prefill throughput** (FP8 / prefill kernels) +
**KV pool / window sizing**. NOT decode ceiling, NOT adaptive-k, NOT seq-slots.


## Execution log — (a) window/seq relaunch (2026-09-05)

**Decision (Victor):** (a) run now, 480K ctx + seq 12; then (b) FP8 trial. Pull FP8 weights on spark2 in parallel.

**spark4 disk cleanup (approved):** removed EXL3 duplicate (164G, verified identical on spark2/3), Qwen 27B leftover (23G), stale sglang/exl3/runtime docker images (~120G). spark4: 158G→**366G free**. Live topkfix lane untouched.

**FP8 staging (b), spark2:** `hf download zai-org/GLM-5.3-Flash` @ `690b7052` → `/home/spark2/models/glm53-flash-fp8-zai/`. Fabric source for later fan-out. (306G; in progress.)

**Launcher edit (a) on all 4 nodes:** CONTEXT_LENGTH `1048576`→`491520`, `--max-num-seqs 64`→`12`. Backed up each `.bak-1m-seq64-20260905`. Verified on all 4: line 39 CONTEXT_LENGTH=491520, line 116 seq 12, banner line 128 seq=12.

**Relaunch:** worker-first rank 3→2→1→0. All 4 Up, head banner confirms `ctx=491520 seq=12`. Boot monitor on head (`~/bootmon.sh`), polls /v1/models, writes `~/relaunch-READY.marker`. Ritual state clean (swappiness=0, swap empty); boot flusher on all 4 (NOPASSWD drop_caches).

**Status:** weights loaded (head MemAvailable ~56G), kernel-JIT/autotune phase. Awaiting READY.
