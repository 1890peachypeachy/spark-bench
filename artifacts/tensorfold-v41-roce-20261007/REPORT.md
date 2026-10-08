# DeepSeek V4.1 Flash · TensorFold · 4× Spark: G19 back on RoCE (2026-10-07)

**Result.** The live G19 server had been exchanging over NCCL (TCP sockets) instead of RoCE since 2026-10-05 17:32. A stale
failure marker caused it. With RoCE back, the published depth sweep beats the 2026-10-04 table at nearly every cell:

| prompt | prose 10-04 | **prose G19 + RoCE** | code 10-04 | **code G19 + RoCE** | cold first token 10-04 | **G19 + RoCE** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1k | 63.6 | **66.0** | 104.9 | **107.2** | 0.3 / 0.8 s | 0.9 / 0.7 s |
| 20k | 65.7 | **66.7** | 97.0 | **103.5** | 14.2 / 12.9 s | **6.0 / 5.3 s** |
| 40k | 64.0 | **68.7** | 96.4 | **105.0** | 24.5 / 24.7 s | **9.3 / 9.4 s** |
| 80k | 62.8 | **69.6** | 103.1 | 101.7 | 45.9 / 46.8 s | **17.9 / 17.8 s** |
| 160k | 61.0 | **62.0** | 99.8 | **103.4** | 99.8 / 97.4 s | **35.9 / 35.8 s** |
| geometric mean | 63.4 | **66.5** (+5%) | 100.2 | **104.1** (+4%) | | |

Writing speed in tok/s, median of 3 a cell; cold first token is prose / code. Four users at once (`dsbench`):
**122.2 tok/s** aggregate (was 119.2), single-stream median 63.8 (was 62.6).

## What happened

- RoCE's run-time failure path writes `/cache/roce-failed`. While that file exists, every start falls back to NCCL, and
  the RDMA plan link falls back to TCP.
- A deliberate crash test on 2026-10-05 17:32 timed out one exchange and wrote it. Nothing removed it.
- Everything after that ran on NCCL:
  - the 2026-10-05 evening runs;
  - the G13 vs G19 candidate window (2026-10-06/07);
  - the TP=2 evidence for Jay's PR #6.

  Both sides of each comparison were on NCCL, so those comparisons still hold. Only their absolute decode numbers
  are low.
- The marker was moved aside (`roce-failed.20261005`, not deleted) and the server restarted. Boot log:
  - "all-gathers of up to 1024 KiB a rank over RoCE";
  - "plan link: rdma".

## The same build on NCCL vs RoCE

`m2bench`, one stream, same boot settings (`roce-verdict.txt` on the head):

| | NCCL (marker present) | RoCE |
| --- | ---: | ---: |
| code, tok/s | 107.2 | **119.6** (+12%) |
| prose, tok/s | 55.8 | **66.4** (+19%) |
| 1-row verify window, ms (boot calibration) | 18.7 | **16.3** |
| exact (drafted == serial) | yes | yes |

## Method

- Server: the live G19 configuration, unchanged except the marker:
  - `tp4.env`, image `tp4g19b`;
  - 420K context, images native;
  - expert pruning on.
- Depth sweep: `depth-tf.sh g19-roce`, the same harness and fixtures as the 2026-10-04 report:
  - 512 tokens, thinking off, greedy, 3 trials a cell;
  - trial 0 cold, trials 1-2 repeats;
  - isolated with an iptables rule on port 8000.
- Four users: `c4.sh g19-roce` (`dsbench-local.py`, 4 streams), isolated the same way.

## Files

- `g19-roce.jsonl`: the 30 sweep rows, without the `events` and `output` fields. Each row keeps `output_sha256`.
- `summary-g19-roce-vs-20261004.json`: the cell medians beside the 2026-10-04 run.
- `c4-g19-roce.txt`: the `dsbench` line.

## Follow-up

The keeper should alert when `/cache/roce-failed` exists. A silent fallback to NCCL costs 12-19% of decode and was
invisible for two days.
