# MiniMax-M3.1-Flash — split-across-Sparks download

Direct-landing download of `MiniMaxAI/MiniMax-M3.1-Flash` (72 files / 235.1 GiB, MXFP8,
`MiniMaxM3SparseForConditionalGeneration`), landed on **spark2** under
`~/models/MiniMax-M3.1-Flash`. No recipe, no lane, no serving — download only.

Pinned revision: `9e7ebacac350497ad4a1272a2e817639bf11561c` (main at resolve time).

## Why split

One node's HF flow measured 1–3 MB/s; three nodes pulling disjoint file slices sustained a
higher aggregate, then the helper slices fan in to spark2 over the CX7 fabric
(`10.73.0.2`), never LAN/Tailscale. This is the "split ONE big HF download across Sparks"
method from `fleet-bulk-transfers`.

## Split (by bytes, greedy onto lowest filled fraction)

| node | role | files | bytes |
|---|---|---|---|
| spark2 | landing | 39 | 77.3 GiB |
| spark1 | helper | 16 | 79.2 GiB |
| spark4 | helper | 17 | 78.6 GiB |

Free space at planning time: spark1 790G (78%), spark2 543G (85%), spark4 407G (54%).
spark3 excluded — 302G free at 92%, and it is the head of the live `dsv41-tp4` lane.

## Mechanics

1. `manifest.json` — built from the tree API of the PINNED revision (`expand=true`, cursor
   followed, 72/72 entries, LFS `oid` kept as sha256). Doubles as the checksum source.
2. First attempt used `snapshot_download` per slice — starved (single stream ~1–3 MB/s).
   Killed; switched to `chunkdl.py` (64×2 MiB parallel range GETs, per-chunk retry,
   sha256-on-assemble) because short parallel ranges measured 13–16 MB/s on the same CDN.
3. `m31_chunkdl.sh <node> <dest> <state>` runs chunkdl over that node's slice and stamps
   `HALF_DONE_<node>` only on exit 0.
4. `m31_fanin.sh <node> <stage>` (helpers only) waits for its own HALF_DONE, rsyncs its
   slice to spark2 over the fabric `--files-from` (layout preserved), then stamps
   `FANIN_DONE_<node>` on spark2.
5. `m31_verify.py` (spark2) waits for all HALF_DONE + both FANIN_DONE, then sha256-checks
   every LFS file and size-checks the plain git blobs; writes `~/m31-state/VERIFIED.txt`
   ending `RESULT: PASS|FAIL`.

Everything is driven by artifact markers, not process liveness, so the pipeline completes
after the chat session ends.

## State

**COMPLETE — `RESULT: PASS` 2026-10-23T09:0xZ.** 50/50 LFS files sha256-verified, 22 plain
git blobs size-checked, 235.11 GiB exact, 48 shards + `dspark/` drafter on spark2.
`spark2:/home/spark2/models/MiniMax-M3.1-Flash` finished first, then the helper
slices were rsynced in over the fabric (FANIN_DONE_spark1 / FANIN_DONE_spark4).

Measured: ~20-28 MB/s aggregate across three nodes, 7-8 MB/s per node with chunkdl
(single-stream `snapshot_download` had collapsed to 1-3 MB/s). ~2 h wall clock.

Helper staging dirs on spark1 (`/var/tmp/m31`, 80G) and spark4 (81G) held verified
duplicates of the landing copy. **Cleared 2026-10-23:** every staged slice was first
proven size-identical to the hash-verified canonical (16/16 spark1, 17/17 spark4,
0 mismatches), then the weight trees were removed — ~79 GiB spark1, ~80 GiB spark4.
Marker + log record kept in `~/m31-state` on each node.

- spark1 `~/m31-state/`, spark2 `~/m31-state/`, spark4 `~/m31-state/`
- logs: `~/logs/m31-chunk-<node>.log`, `~/logs/m31-verify.log`
- helpers stage in `/var/tmp/m31/MiniMax-M3.1-Flash` (outside the dsv41-nfs export)

## Two bugs found and fixed in the tooling (a re-run needs the fixed copy)

1. **Verifier deadlock.** `m31_verify.py` waited for `HALF_DONE_<helper>` *on the landing
   node*, but helpers only ever replicate `FANIN_DONE_<helper>`. It would hang the full
   24 h timeout on a fully-downloaded, fully-validated set. Fixed: landing marker checked
   locally, helper half-markers checked **on the helper over the CX7 fabric**
   (`spark@10.73.0.1`, `spark4@10.73.0.4`) — the Spark nodes do NOT resolve the Mac's
   `spark1`/`spark4` ssh aliases.
2. **Watchdog false alarm.** It reported "STOPPED" because it gated on chunkdl being
   alive, but chunkdl EXITS on success. Fixed: silent when the verifier is running, when
   downloaders are running, or when all 5 markers exist; speaks only on a verdict or a
   genuine stall (nothing running, markers absent).

## Re-running

```bash
# per node, detached
ssh <node> "cd ~/m31-state && tmux new -d -s m31 'bash /tmp/m31_chunkdl.sh <node> <dest> \$HOME/m31-state > \$HOME/logs/m31-chunk-<node>.log 2>&1'"
```
chunkdl skips verified files, so a re-run resumes.