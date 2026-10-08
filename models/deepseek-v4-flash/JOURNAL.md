# DeepSeek V4 Flash on 4× DGX Spark — journal

Every dated entry for this model, newest first: what we changed, what it measured, what failed and why. Moved here unchanged from the top-level README on 2026-10-05 (old screenshots retired; the lane chart is on the [README](../../README.md)). Raw files stay where the entries link.

---

<a id="deepseek-v4-flash"></a>

## DeepSeek V4 Flash — 4× DGX Spark

Uncensored DeepSeek V4 Flash 0731 (abliterated NVFP4), vLLM + MTP speculative
decoding, TP=4 on the same fabric. The original recipe in this repo and still
the fastest raw decode we have measured on this cluster.

**In plain English:** it writes answers at **~136 tokens/second** for one
person (peaks of 145), reads long prompts at **~2,100 tokens/second**, and
serves four people at once at **~182 tokens/second** combined. That headline is
the *best case* — short prompt, code output. Regular chat at real conversation
depths runs ~66–93 tok/s; see [the honest map](#the-honest-map-what-speed-you-actually-get).

### 2026-08-26 · Engine record 290.3 gen tok/s

New engine record on the dashboard: **290.3 gen tok/s** (forge card), with 159 gen tok/s live on
one active sequence at the time. Dashboards are modified
[MiaAI-Lab sparkDash](https://github.com/MiaAI-Lab/sparkDash).

### 2026-08-20 → 21 · Dual-rail and SGLang experiments

- **Dual-rail NCCL** (rails A+B): busbw 23.1 vs 11.1 GB/s at 64 MB — a 2.1×
  interconnect win on paper. Formal C1 A/B vs rail B alone: **+0.4% mean /
  +3.6% median** (n=9/14). The earlier "+11%" claim was retracted; decode is
  not interconnect-bound at this size. Log: [`results/c1-dual-rail-2026-08-21.log`](../../results/c1-dual-rail-2026-08-21.log).
- **SGLang TP4 attempt:** booted on all four GB10s but the DSpark speculative
  path is blocked by a dsv4 kernel constraint in the dev image; no valid perf
  comparison possible. vLLM retained. Writeup:
  [`results/sglang-vs-vllm-2026-08-20.md`](../../results/sglang-vs-vllm-2026-08-20.md).

### 2026-08-18 · Six-sequence aggregate ~230 tok/s

Six active sequences at **229.9 aggregate gen tok/s** across forge / anvil / ember / flame (dashboard reading).

### 2026-08-16 · C1 record: 136.25 median, 145.5 peak

Abliterated NVFP4, thinking off, temperature 0, concurrency 1, 2048 completion
tokens, cluster idle. Server metric is
`Δ generation_tokens_total / Δ request_decode_time_seconds_sum`; client wall
is `(completion_tokens − 1) / (t_last − t_first)` on streamed text.

| | tok/s |
|---|---:|
| Observed peak (2026-08-16) | **145.5** |
| Formal C1 median (n=9 clean, 2026-08-16) | **136.25** |
| Formal C1 mean / sd | 136.6 / 1.27 |
| Formal C1 min / max | 135.1 / 139.3 |
| Previous record (2026-08-14, rail A, pre-cleanup) | 103.4 median, 113.8 engine window |
| Same cluster, no-spec (misconfigured boot) | 33.5 |

📈 [The full ledger: decode, prefill, and concurrency — TP2 vs broken vs record vs now, 2026-08-16](../../results/ledger-2026-08-16.png)
📈 [C1 decode journey: TP2 baseline, broken boot, old record, and now, 2026-08-16](../../results/c1-decode-journey-2026-08-16.png)

*One day of fixing (2026-08-15 → 08-16): from a misconfigured boot where "TP2
beats TP4" to the fastest this cluster has ever run.* Removing leftover IPv4
addresses from the NCCL interface alone was worth ~30% C1 (103.4 → 136.25 on
an otherwise identical config).

Live boot after this recipe (clean fabric):

```text
GPU KV cache size: 5,600,636 tokens
Maximum concurrency for 1,048,576 tokens per request: ~5.3x
```

**Thinking effort vs decode speed (2026-08-16).** C1 client-wall tok/s,
512-token completions, prose-summary task, n=2 medians per cell (±5–8 noise),
measured with `scripts/bench-depth.py --thinking off|low|high|max`. Off
dominates at 5k, everything ties at 10k, and at 50k thinking-**low** is fastest
while **high** is slowest — effort is not monotonic. Quote the thinking state
with any decode number.

📈 [Thinking off vs low, 2026-08-16](../../results/thinking-off-vs-low-2026-08-16.png)

> **Client-vocabulary caveat.** The template maps `max`/`xhigh`→max,
> `high`→high, and **everything else → low, silently**. Clients whose
> vocabulary includes `medium`/`minimal` actually run at **low**, with no
> warning. Verified live 2026-08-16. If you benched "medium", you benched low.

### 2026-08-15 · Decode at depth and concurrency

MTP acceptance — not prompt depth — is the variable. Code tasks hold 4.6–4.9
accepted tok/step at 5–10k (79–93 tok/s); repetitive prose drops to 2.1–2.4
(52–64 tok/s). C4 aggregate 182 tok/s.

📈 [Decode at depth: C1 tok/s vs prompt depth, 2026-08-15](../../results/decode-at-depth-2026-08-15.png)
📈 [C4 aggregate tok/s, 2026-08-15](../../results/c4-aggregate-2026-08-15.png)

### The honest map: what speed you actually get

The record is one cell of the matrix — short prompt, code output, long
completion. Decode depends on **how much conversation the model is carrying**
and **how predictable the output is** (MTP acceptance: ~4.8–4.9 tok/step on
code, ~2.1–2.4 on prose at depth).

| workload | decode tok/s |
|---|---:|
| Best case: short prompt, code, long run | **136 median · 145.5 peak** |
| 5–10k prompt, code task | ~79–93 |
| 5–10k prompt, regular chat / prose | ~72–89 |
| Deep session (~50k prompt) | ~66–74 |

Everyday chat lands close to — but under — 100 tok/s, and that is a workload
property, not a config problem. Quote prompt depth, task type, and thinking
state with any decode number. A short-prompt C1 number and a long-session
agent number are different measurements; publish both if you quote one.

### How to run DeepSeek V4 Flash (recipe)

**You need:**

- 4× DGX Spark (GB10), each with one 200G cable into one RoCE-capable switch
  (we use a MikroTik CRS812). Wire it per [docs/FABRIC.md](../../docs/FABRIC.md).
- The serving image on **all four nodes**:
  ```bash
  docker pull ghcr.io/anemll/dspark-vllm-gx10:0.1.1
  docker build -t dspark-vllm-gx10:0.1.1-flashinfer-0.6.15 -f Dockerfile.flashinfer-0.6.15 .
  ```
- The model on **all four nodes** at the `DSPARK_MODEL_HOST` path from `.env`.
  Our records use
  [`drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32`](https://huggingface.co/drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32)
  (DSpark-native MXFP4-path abliterated checkpoint — fastest on Sparks in our
  tests). Alternatives: stock `deepseek-ai/DeepSeek-V4-Flash-0731`, or
  [`neko-legends/DeepSeek-V4-Flash-0731-Abliterated-NVFP4`](https://huggingface.co/neko-legends/DeepSeek-V4-Flash-0731-Abliterated-NVFP4)
  for server-class NVFP4 stacks. Set `SERVED_MODEL_NAME` to match.
- `cp .env.example .env` and fill in hostnames, fabric IPs, and paths.

**Then:**

1. Fabric: exactly one IPv4 per fabric NIC, MTU 9000 end to end
   ([docs/FABRIC.md](../../docs/FABRIC.md)); install
   `scripts/spark-gpu-clock-lock.service` on every node.
2. Launch: `scripts/start-dspark-tp4.sh` — workers first; boots **disarmed**,
   then arms auto-restart only after the API and the spec-decode gate pass.
3. Verify: `scripts/status-dspark-tp4.sh` must print `OK: speculative decoding
   live`. Every decode number measured without spec is ~3× low.
4. Bench: `scripts/bench-decode.py` (C1 record protocol),
   `scripts/bench-depth.py` (5k/10k + C4).

**Topology.** Four GB10 nodes, one vLLM world, TP=4. Head serves the
OpenAI-compatible API (`0.0.0.0:18888`); three workers are headless ranks.
NCCL / Gloo / TP sockets stay on the CX-7 data NIC, never the tailnet. Fabric:
switched L2 RoCE, one 200G CX-7 port per node per rail (rail A `enp1s0f1np1`
`192.168.2.0/24`, rail B `enP2p1s0f1np1` `192.168.10.0/24`, MTU 9000);
serving runs rail B. The CX-7's second PCI function per port (`f0`/`np0`) is a
dark port on this board — the multi-HCA upgrade is dual-rail, not
dual-function.

**Serving shape.** Image `dspark-vllm-gx10:0.1.1-flashinfer-0.6.15`
(Anemll 0.1.1 / vLLM 0.25.2):

```text
--tensor-parallel-size 4 --nnodes 4
--kv-cache-dtype nvfp4_ds_mla --block-size 256
--max-model-len 1048576         # reserved catch-up window; KV pool GiB stays flat
--max-num-seqs 12
--max-num-batched-tokens 8264
--max-cudagraph-capture-size 96          # seqs × (k + 1)
--gpu-memory-utilization 0.85
--speculative-config k=7, draft_sample_method=probabilistic
--compilation-config {"cudagraph_mode":"FULL_DECODE_ONLY"}
--override-generation-config {"temperature":0.0}
--default-chat-template-kwargs {"thinking":false}
--moe-backend flashinfer_b12x
--enable-prefix-caching --async-scheduling --enable-chunked-prefill
```

`--ulimit nofile=1048576` on every rank — TP=4 opens enough NCCL sockets that
the image default of 1024 dies with `Too many open files`.

<details>
<summary><b>Why these knobs</b></summary>

| knob | we run | why |
|---|---|---|
| `num_speculative_tokens` | 7 | This image's kernels are shaped for dspark7. k=5 left ~18 tok/s on the table. |
| `draft_sample_method` | probabilistic | Matches the target distribution. Greedy collapses acceptance off temp 0. |
| `max_cudagraph_capture_size` | `seqs × (k+1)` = 96 | A copied `36` truncates to 32 and dumps larger batches into eager. |
| `max_num_batched_tokens` | 8264 | vLLM subtracts `(k−1)×seqs` from the prefill budget and warns below 8192. 32768 wedged the compile/autotune phase on all ranks (2026-08-15) — grow in stages. |
| `gpu_memory_utilization` | 0.85 | 0.80 wastes ~7 GiB. 0.90 does not boot on this weight split. |
| `max_model_len` | 1048576 | Legal size for the reserved catch-up window. KV pool GiB is almost flat from 327k–1M. Does not raise C1. |
| `cudagraph_mode` | FULL_DECODE_ONLY | One graph set. No measured cost. |
| GPU clock | `nvidia-smi -lgc 0,2200` on every node | Prevents throttling: unlocked DVFS dips to ~1970 MHz under sustained prefill; the lock holds ~2171 — prefill 32k cold ~2100 tok/s (was ~950 pre-cleanup). Decode unchanged (not clock-bound). Same throughput as a 2400 lock at ~21% fewer watts. Persisted via `scripts/spark-gpu-clock-lock.service`. |
| omitted `temperature` | forced 0.0 | `--generation-config vllm` otherwise defaults omitted temp to 1.0 and wrecks MTP accept. |
| thinking | off | On this checkpoint, thinking-on C1 was ~65 vs ~84–103 thinking-off. |

</details>

<details>
<summary><b>Landmines</b></summary>

1. **One IPv4 on the NCCL NIC — enforced in netplan.** A leftover
   switch-management address makes NCCL advertise it; workers hang at
   `ncclCommInitRank`. Stale point-to-point mesh files in `/etc/netplan`
   resurrect dead subnets on every reboot: delete or `.disabled` them.
2. **Launches start disarmed.** `DSPARK_RESTART_POLICY=no`; the start script
   arms `unless-stopped` only after the API is up *and* spec-decode counters
   appear in `/metrics`. A config that cannot boot healthy must never wedge a
   node across reboots (2026-08-15 incident).
3. **`ulimit -n` must be 1M inside the container.** `bash -lc` drops nofile
   to 1024 unless set in compose *and* in the entrypoint.
4. **Do not `netplan apply` an old point-to-point mesh file** after moving to
   a switch.
5. **Quote decode with prompt length and warmup.** A 10 s engine average
   during a 400k prefill is not a decode record. Warm the graphs before
   publishing C1.
6. **Prefix cache is LRU.** Nightly jobs with fat unique prompts can evict the
   reserved agent window. Cap those jobs; re-POST the agent snapshot after.

</details>

**Reproduce the C1 number** (cluster idle, thinking off, temp 0):

```bash
python3 scripts/bench-decode.py \
  --base-url http://HEAD:18888/v1 \
  --model deepseek-v4-flash-0731-ablit-32-32 \
  --max-tokens 2048 --warmup 8 --n 10
```

Report the Prometheus decode-only rate *and* the client stream wall rate.
Drop any trial where `request_success_total` increases by more than 1. Raw
trials: [`results/c1-decode-2026-08-14.json`](../../results/c1-decode-2026-08-14.json).

**What this is not:** not official (non-abliterated) 0731 numbers; not a
1M-prompt throughput claim (nobody here has decoded *at* 1M); not aggregate
multi-stream throughput (C4/C12 is a different measurement); not a license to
ship prompts — weights stay on the cluster.
