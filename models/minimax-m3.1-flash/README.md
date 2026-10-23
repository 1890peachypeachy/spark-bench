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

- spark1 `~/m31-state/`, spark2 `~/m31-state/`, spark4 `~/m31-state/`
- logs: `~/logs/m31-chunk-<node>.log`, `~/logs/m31-verify.log`
- helpers stage in `/var/tmp/m31/MiniMax-M3.1-Flash` (outside the dsv41-nfs export)

## Re-running

```bash
# per node, detached
ssh <node> "cd ~/m31-state && tmux new -d -s m31 'bash /tmp/m31_chunkdl.sh <node> <dest> \$HOME/m31-state > \$HOME/logs/m31-chunk-<node>.log 2>&1'"
```
chunkdl skips verified files, so a re-run resumes.