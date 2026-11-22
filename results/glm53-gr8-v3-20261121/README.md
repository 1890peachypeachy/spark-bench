# glm53-gr8 v3 (bit280, bertholomus/glm-5.3-exlr8-4x-spark af95a2e) — verification 2026-11-21

Lane: gr8:ca7e874-attic, SESS=6, CAP=776704, bit280 sha 748cdc59, attic on, 4x DGX Spark TP4, head spark3.
Deployed recipe dir /var/tmp/gr8/recipe is at upstream af95a2e on all 4 nodes (tracked files clean).

## Change made
BUSY_IDLE_SECS=120 BUSY_RETRY_AFTER=20 added to .env on all 4 nodes (backup .env.bak-pre-busy-20261121),
lane restarted via `spark-lane down/up glm53-gr8`. Clears the knobs.sh boot WARNING (retry >= idle at 60/60).
Verified live in show-config. Smoke 14/14. spark-lane verify PASS.

## Our measurements (one boot, idle lane; NOT RigMark — different prompts/harness, not comparable to upstream rows)
- c1 decode median (c1_decode_screen.py, 400 tok, effort low): prose 40.7 / code 48.6 / structured 74.2 tok/s
- conc.py (600 max tok, 6 mixed prompts, usage tokens incl. reasoning): 1 stream 39.8; 4 streams 85.0 agg (~21.9 each); 6 streams 92.1 agg (~16.6 each)
- Upstream claims (their boot, RigMark): C4 110.2 agg / 28.4 each; code/prose/structured 59.9/39.2/67.5. Not reproduced here on our harness.

## Incident 2026-11-21 10:36-10:39 PST (before the change)
Lane auto-restarted. Rank 3 (spark4) stopped answering on the LAN control channel mid-prefill (last chunk 10:36:42);
rank 0 got errno 110 send timeout, rank 3 got errno 104 reset, head stopped the cluster, KV saved (70 entries kept),
docker restart policy brought it back by 10:39. Ruled out: GPU/kernel fault, OOM kill, thermal, memory pressure, CX7 errors
(all counters 0). NVRM carveout OOM lines are per-boot noise on all 4 nodes. Root cause UNKNOWN. spark4 TCP counters
are in line with the others. Watch: spark4 disk 88% (113G free, 916G drive) vs 3.7T elsewhere.
Evidence archived: ~/.hermes/profiles/spark/backups/glm53-crash-20261121-1037PST/
