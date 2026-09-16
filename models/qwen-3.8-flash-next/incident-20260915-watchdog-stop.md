# Qwen single-Spark incident 2026-09-15 — watchdog stop after NV_ERR_NO_MEMORY

## What happened
~2 h after the single-Spark cutover, `vllm-fn-tp1` (spark2) exited 137.
Not a cgroup OOM (`OOMKilled=false`): Mia's `memwatch.sh` watchdog saw
**MemFree < 2 GiB for 5 consecutive samples** (1.21 GiB) and stopped the
container ("MemFree under 2 GiB for 5 samples -> stopping vllm-fn-tp1").
Root trigger: **7 NV_ERR_NO_MEMORY events** from the GB10 driver during
agent-loop traffic (large prefill bursts + MTP-3 verify on UMA). Exit 137 is
docker's 30s-force after the graceful stop path stalled.

## Fix (her documented remedy)
`.env`: `HOST_RESERVE_GIB=26 -> 30` (two 2-GiB steps per README guidance).
Result: GPU budget cap 91.69 GiB, KV pool 17.94 GiB/1.198M tokens ->
**12.70 GiB / 989,996 tokens (3.78× @262K)**. MemFree floor unchanged at
2 GiB (that check is the UVM-livelock protection — do not loosen).

## Post-fix verification
health 200, canary "PONG post-fix", watchdog live with MemFree ~4.6 GiB
(3.7× more headroom than the 1.2 GiB that triggered the stop), zero floor
breaches post-restart. KV usage at kill was 11.8% — the pool cut costs
nothing under real demand (agent fleet).

## Lesson
On a single-UMA box serving an agent fleet, size HOST_RESERVE_GIB for the
*burst* profile (long-prompt prefills + PLE build spikes), not the average.
The watchdog is the tripwire; read `logs/memwatch-*.log` before any "why did
the lane die" question on this kit.
