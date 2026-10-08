# DeepSeek V4.1 Flash · TensorFold · 4× Spark: where single-user decode time goes (2026-10-07)

**Question.** Two Sparks run ~80 tok/s on code; four run ~120. What else can speed up one user?

**Answer.**
- No setting gives more than ~2%. Every exact switch for the exchanges and the L2 prefetch measured inside boot-to-boot noise.
- One small win was adopted: the drafter reads a 4-bit copy of the vocabulary head (`TF_DSV41_DRAFT_HEAD=q4`). Code
  went up +2.5% and prose +1.4%, two boots each. It is exact, because drafts only propose. Live since 14:06.
- A trace of the exchanges shows where the four-Spark tax is. Per decode window, the Sparks wait **~2.5 ms for each
  other** (about 10% of a window), and the exchange kernels hold the slowest Spark for **~2.5 ms** more:
  - ~0.9 ms of the waiting is structural. Spark 1 and 2 hold 25% more of every expert, 640 vs 512 columns, because
    2,304 doesn't split into four whole 128-column blocks.
  - ~1.6 ms is random jitter. A step waits for the slowest of four GPUs, not two.

## 1. A/B of the exact switches

Method:
- one fresh boot of the live configuration per row (G19, RoCE, 420K context, images);
- `m2bench`, one stream, code and prose, 3 reps;
- exact on: drafted == serial;
- the verify window is the boot calibration, in ms.

| variant | code tok/s | prose tok/s | 1-row window | draft pass |
| --- | ---: | ---: | ---: | ---: |
| live (3 boots) | 119.4 / 119.8 / 121.7 | 65.9 / 67.4 / 67.1 | 16.0-16.7 | 2.56-2.81 |
| `GLM53_TF_ROCE_LEAN=1` | 120.9 | 67.0 | 16.4 | 2.57 |
| `GLM53_TF_ROCE_STRIPE_KB=4096` (one HCA a shard) | 117.8 | 66.9 | 16.2 | 2.61 |
| `GLM53_TF_ROCE_POLLERS=3` | 121.1 | 66.6 | 16.1 | 2.60 |
| `GLM53_TF_ROCE_LAZY_CQ=1` | 118.7 | 67.0 | 16.5 | 2.85 |
| `GLM53_TF_ROCE_CPU=18` (pin the proxy) | 119.1 | 66.7 | 16.2 | 2.56 |
| `TF_DSV41_L2PF=0` | 119.0 | 67.7 | 15.9 | 2.56 |
| `TF_DSV41_L2PF_MB=6` / `24` | 114.9 / 120.0 | 67.3 / 66.7 | 16.1 / 15.9 | 3.00 / 2.56 |
| **`TF_DSV41_DRAFT_HEAD=q4`** (2 boots) | **122.8 / 123.9** | **68.2 / 67.3** | 15.8-15.9 | **2.42** |

Notes:
- Code tok/s moves ±2% between identical boots. The depth policy reads each boot's measured costs, so tokens per
  round move too (3.66-3.80 on code).
- Prose is steady at 1.60-1.63 tokens a round.
- The L2 prefetch is worth ~1.7 ms a window at two Sparks (Jay's G14a). At four it is worth nothing either way: each
  rank's dense groups are half the size.

## 2. Exchange trace

Method:
- `GLM53_TF_ROCE_TRACE=65536`, `GLM53_TF_ROCE_TRACE_DUMP_S=2`;
- per exchange and rank, the GPU timestamps of start, doorbell, peer flags seen and end;
- ranks paired by sequence number, and only same-rank differences used (the clocks differ between nodes);
- 367 decode windows of 92 exchanges each (mixed 1-6 rows; median span 25.7 ms on rank 0).

Medians over windows, ms a window:

| | rank 0 (forge) | rank 1 (anvil) | rank 2 (ember) | rank 3 (flame) |
| --- | ---: | ---: | ---: | ---: |
| compute between exchanges | 22.25 | 22.10 | 20.57 | 21.06 |
| inside exchange kernels | 2.53 | 3.06 | 4.35 | 4.34 |
| of which waiting for peers | 1.90 | 2.43 | 3.70 | 3.71 |
| last to arrive, share of exchanges | 42% | 27% | 9% | 21% |
| compute vs the four-rank mean, a segment | +10.0 us | +7.4 us | −10.4 us | −7.0 us |

Summed over a window's 91 compute segments:

| sum of | ms |
| --- | ---: |
| the slowest rank's segment | 23.89 |
| the mean rank's | 21.34 |
| the fastest rank's | 19.79 |

So **~2.5 ms a window is ranks waiting for the slowest one**. About 0.9 ms of that is systematic: ranks 0 and 1 lose
every MoE segment by ~30 us (~260 vs ~230 us). The attention segments are even (~150 us each). The rest is jitter.

## 3. Levers, ranked

| # | lever | expected | exact? | effort |
| ---: | --- | --- | --- | --- |
| 1 | **Balance the expert split.** Rotate the 5th 128-column block across experts (expert e's extra blocks go to ranks e mod 4 and e+1 mod 4), so the active experts' extra work spreads over all four ranks. Needs x3ld with a per-expert width and offset, the loader, and a re-prepared weight folder | −0.6 to −0.9 ms a window: **+3-4%** single user and concurrent | yes (drafted == serial); new bits vs today's split | large (CUDA kernel + loader) |
| 2 | Drafter refit to the uncensored target (Jay's G11 delta A: prose +5.5%, code −4.4%), applied per workload or per slot by running acceptance | prose **+5%** | yes (drafts only) | medium (training + port fidelity) |
| 3 | Trimmed draft head (`TF_DSV41_DRAFT_HEAD=trim:M`). Needs a token ranking file; none is shipped, so we'd build one from our own replies | another ~0.1-0.2 ms a round, **+0.5-1%** | yes | small |
| 4 | Jitter: anything that makes one GPU late now costs all four (Engram NVMe reads, host threads, compaction). Per-step jitter is ~1.6 ms a window | up to +6% if it could all go; realistically a part | yes | unknown |
| 5 | More expert pruning (`TF_DSV41_EXPERT_TOPP` below 0.85) or lower-bit routed experts | +10-15% | **no**: precision trade, needs quality gates | small / large |
| 6 | Jay's kernel-fusion roadmap (a 1-row window is 16 ms against a ~9.4 ms bandwidth floor a rank) | lands upstream; we rebase | yes | his |

Not worth it at four Sparks:
- RoCE micro-switches: lean, stripe, pollers, lazy completion, CPU pin;
- L2 prefetch size.

## Files

- `rocetrace4.py`: the per-rank exchange summary.
- `decode_windows.py`: the decode-window split (the tables in section 2).
- `ab-summary.json`: the A/B table above.

The trace itself (60 MB a run) stays on the head in `pf/ab/trace/`.
