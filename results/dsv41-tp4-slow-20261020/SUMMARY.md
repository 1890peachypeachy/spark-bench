# DSv4.1-Flash 1017 TP4 vs TP3, and 1-rail vs 2-rail (2026-10-20)

Harness matters: `bench_sustained_decode.py` (1500 tok) reads ~32% below sparkDash DecodeBench on the same lane.

## Our harness (bench_sustained_decode, 1500 tok, thinking off, median of 3) - relative only
| lane | c1 per-stream | c4 aggregate | ttft c1/c4 |
|---|---:|---:|---|
| TP4 | 59.6 | 99.9 | 0.24/0.36 s |
| TP3 | 41.2 | 85.7 | 0.26/0.50 s |

## sparkDash DecodeBench (256 tok, thinking off, knapcio protocol), TP4
| | 1 rail | 2 rails | knapcio v2.4 README |
|---|---:|---:|---:|
| prose c1 | 87.2 | 87.2 | 89.9 |
| prose c4 agg | 161.5 | 162.1 | 164.9 |
| prose c8 agg | 212.8 | 214.9 | 237.2 |
| prose c16 agg | 307.0 | 308.8 | 341.3 |
| code c1 | 129.5 | 132.1 | 131.0 |
| json c1 | 121.4 | 122.3 | 128.4 |

Conclusion: TP4 is not slow. 2nd rail (roceP2p1s0f1, 10.74.0.x) is active and carries bytes but gives <=2% (noise).
Kept: free, lower c8/c16 TTFT (single run). Open: c8-c16 ~10% under README; untested DSV41_ENGRAM_DRM_NODE.
Revert: restore .env.tp4.bak-20261020-1rail on spark3 (IB_HCA/NCCL_IB_HCA/B12X_ROCE_HCA=rocep1s0f1, NCCL_IB_ADDR_RANGE=10.73.0.0/24).
Also fixed 2026-10-20: TP3 start.sh rsync spark@spark@host (pushed to deepseek-v41-flash-tp3-recipe 3c4112d).
