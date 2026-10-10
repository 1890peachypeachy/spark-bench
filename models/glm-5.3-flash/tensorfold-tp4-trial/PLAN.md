# Mia TensorFold TP4 trial — staging plan (NOT executed; bring-up is Victor's call)

Found: `MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks-TensorFold` branch `tp4` (tip `d220030`, 2026-10-10).
Working checkout: `~/recipe-db/GLM-5.3-Flash-EXL3-2x-DGX-Sparks-TensorFold/tp4-trial` (branch `fleet/tp4-trial`).

## Why a trial, not a diff-and-port

The live `glm53-tp4` lane and Mia's tp4 branch are **different engines**:

| | live lane | Mia tp4 branch |
|---|---|---|
| Engine | vLLM (`glm53-roce:v11-b58f34ea`, knapcio align-fix lineage) | TensorFold v0.6.0-7a37454d3238 + 106 patches |
| Checkpoint | local `glm-quant-mix/lossless8` + incoai DFlash2 drafter | `Mia-AiLab/GLM-5.3-Flash-EXL3-4bpw-TensorFold` (~176 GB) + DFlash2 |
| Window | 262,144 | 1,048,576 (FP8 KV) |
| KV pool | 24 GiB | 32 GiB shared = 5,834,752 tokens |
| Topology | CRS504 switch, rail rocep1s0f1 | ring (measured) / switch (`start-tp4.sh`, untested by author) |
| Measured decode (ours idle-gated 2026-09-29) | prose 62.1 / code 81.1 / structured 126.7 | hers (ring): 85.6-86.2 / 144-150 / 200-209 (1/4/8 streams) |

Comparing numbers: hers are 4/8-stream sparkDash figures, ours are c1 idle-gated —
NOT directly comparable. A trial measures both under our harness.

## Mutual exclusion (hard rule)

Registry: `glm53-tp4` needs spark1-4 and owns :8888. The TF trial lane is a NEW lane id
(`glm53-tf4`) in `spark-bench/ops/spark-lane`, same endpoint class, mutually exclusive.
Consumers must NOT be re-pointed during the trial. Live lane stays untouched and serving.

## Bring-up sequence (when Victor green-lights)

1. **spark4 disk gate (binding constraint).** 349G free of 916G; her stack wants ~205 GB/Spark
   (176 GB checkpoint + drafter + image ~25 GB). Do NOT put the checkpoint on spark4 unless
   cleanup first frees ≥210G — rotation decision is Victor's. Alternatives: run trial on
   spark1+2+3-only is NOT possible (TP=4 needs 4 ranks); so spark4 cleanup or NFS-weights
   (our live lane already proves NFS-weights works) — prefer NFS weights from spark1/3, keeping
   spark4's payload to drafter+image (~28 GB).
2. Stage image `v0.6.0-7a37454d3238` on all 4 (fabric push from a sibling, verify digest match).
3. Stage checkpoint on spark3 (1.2T free) → NFS-export to 1/2/4; drafter on all 4.
4. Configure `scripts/local.sh` WORKER/WORKER2/WORKER3 = 10.73.0.1/.2/.4 per fleet SSH map,
   `IB_HCA=rocep1s0f1`, `FABRIC_EXPECT=mesh` (switch).
5. `DRY_RUN=1 ./start-tp4.sh` first — validates mesh discovery on CRS504. Mia never ran
   a switch topology; our CRS504 config is the untested path, treat every step as first-boot.
6. Smoke: her `tools/exact.py` bit-equality + `/tokenize` + a 1-stream decode probe.
7. Then our harness idle-gated c1 (prose/code/structured) + prefix-scan corruption gate
   (same one that cleared the align-fix cutover) — comparability requires OUR harness on BOTH.

## Risks

- Switch-topology TP4 is untested upstream (ring is the measured path). Expect first-boot
  friction in mesh discovery / NCCL IB HCA pinning.
- GPU memory: ~110 GiB free/Spark required at boot — lanes co-tenanted on nodes must be
  checked before launch (live glm53-tp4 holds the GPUs; trial runs ONLY while it is down,
  which is itself an outage decision for Victor).
- DFlash2 license: CC BY-NC-ND 4.0 non-commercial (flagged in branch README). Our use is
  non-commercial; DRAFTER=mtp avoids the license if ever needed.
- Benchmark trap (from our own lane history): GLM_LV_MODE=batch-uniform — a c1 benchmark
  with any concurrent consumer reads 1.6x low. Idle-gate on num_requests_running==0.

## Decision point for Victor

The trial requires taking the live glm53-tp4 lane DOWN (same nodes, same GPUs). That is an
outage of the model that serves this fleet's own profile. Recommended shape: a bounded window
(stage everything first, then one bring-up + benchmark session), with the live lane's
documented rollback (`/var/tmp/glm53-recipe-tp4` relaunch, ~5.3 min boot-to-health) ready.
