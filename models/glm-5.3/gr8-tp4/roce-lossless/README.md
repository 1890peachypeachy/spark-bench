# gr8 on the CRS804 fabric: lossless RoCE (GR8_FABRIC_TC) — 2026-11-22

## Why
Two unplanned lane restarts in 24 h (2026-11-21 10:37, 2026-11-22 09:37 PST). The second logged `[fabric r1] bulk WC error transport retry counter exceeded (peer 3)` in a
427k-token prefill: an RC QP gave up after retry_cnt=7 (max). Cause measured read-only: gr8 sends RDMA with IP traffic class 0, so the switch put 99.96% of bytes in
best-effort TC1 (2 MB buffer/port) and dropped 3.95% of packets (12.2 B of 309.6 B since switch boot, all lanes); the Spark NICs trusted PCP with PFC off on every priority.
The switch (CRS804-4DDQ, RouterOS 7.25.1) was already correct: DSCP 26 -> TC3 lossless, ECN on TC3, pfc-tc3 on the four -N-1 ports.

## What changed
1. gr8: new knob `GR8_FABRIC_TC` (scope agree, int 0..255, default 0 = unchanged) sets `ah_attr.grh.traffic_class` at both RTR sites in `engine/comms/fabric.cpp`.
   `gr8-fabric-tc-knob-on-a3f44a0.patch` applies on top of the attic client on kindlingai/gr8 a3f44a0 (knob tables regenerated with cargo in rust:1-slim).
   Image `gr8:a3f44a0-attic-tc` (id 011d5db9ea28) on all four nodes; `.env` EXTRA_ENV gets `GR8_FABRIC_TC=106` (DSCP 26 + ECT(0)). Rollback image `gr8:a3f44a0-attic` kept.
2. NICs, all four, both fabric netdevs (enp1s0f1np1 + enP2p1s0f1np1, which are separate PCI functions): `mlnx_qos --trust dscp` and `--pfc 0,0,0,1,0,0,0,0`
   (DSCP 24-31 -> prio 3 and 48-55 -> prio 6 are the default map). Persisted by `/etc/systemd/system/gr8-roce-qos.service` (oneshot; `systemctl stop` resets to pcp / no PFC).
3. The switch was NOT changed.

## Proof (all numbers from this rig)
Stock perftest 2-to-1 incast (spark1+spark4 -> spark2, 12 s, 4 QPs, 1 MiB writes), `roce_incast_test.py`:
| | unmarked (tclass 0, NICs as before) | marked (tclass 106, NICs configured) |
|---|---|---|
| aggregate | 87.1 Gb/s | 98.0 Gb/s |
| switch drops toward spark2 | 482,548 (1.33%), all TC1 | 0 |
| traffic class used | TC1 148.6 GB, TC3 0 | TC3 143.3 GB, TC1 0 |
| pause frames | 0 | switch tx-pause 6,258 / 4,372 to the senders (PFC working) |
| sender packet_seq_err | +32,010 / +32,271 | 0 |
gr8 itself (lane up, GR8_FABRIC_TC=106): smoke 14/14; two concurrent ~170k-token prefills completed; across the smoke + prefill + full benchmark, ~1,200 GB per port went
through TC3, **0 bytes through TC1 and 0 dropped packets** (`sw_snap.py diff before_lane t2`). Idle `packet_seq_err` fell from ~9,400 per 20 s to 0.
Benchmark vs the pre-fix v3.2.1 run on the same harness (not RigMark): 1 stream 41.0 vs 43.9; 4 streams 97.2 vs 98.1 (25.1/stream); 6 streams 120.5 vs 121.2; 8 streams 139.9 vs 142.5 (19.4/stream).
Free memory under load 11.3-11.8 GiB per node. Within run-to-run noise; no throughput cost.

## Caveats
- The 3.95% drop figure is the switch's lifetime counter across every lane since its last boot, not gr8 alone.
- One post-fix soak is not a proof of no more crashes: watch for `transport retry counter exceeded` / `rank N failed` in the head log over the coming days.
- Heavy PFC use is expected under prefill (~950k pause frames per port in the first 1.2 TB). A pause storm or stuck-pause would show as stalled prefill with TC3 byte counters flat.
- Upstream (bertholomus / kindlingai) have not seen this patch; it is ours.
