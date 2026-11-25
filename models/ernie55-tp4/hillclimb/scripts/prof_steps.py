"""Per-step breakdown: split the kernel timeline at the first lm_head AllGather of each step (2 AllGathers per step)."""
import gzip, json, re, sys, collections, statistics

tr = json.load(gzip.open(sys.argv[1]))
ev = tr["traceEvents"] if isinstance(tr, dict) else tr
kern = sorted([e for e in ev if e.get("cat") == "kernel" and e.get("ph") == "X"], key=lambda e: e["ts"])
ag = [e["ts"] for e in kern if "AllGather" in e["name"]]
# cluster AllGathers: a new step starts when the gap to the previous AllGather exceeds 5 ms
starts = [ag[0]]; prev = ag[0]
for t in ag[1:]:
    if t - prev > 5000:
        starts.append(t)
    prev = t
print(f"AllGather kernels={len(ag)}  step starts={len(starts)}")

def cat(n):
    for c, p in [("nccl_allreduce_bf16", r"AllReduce_bf16"), ("nccl_allreduce_f32", r"AllReduce_f32"), ("nccl_allgather", r"AllGather"),
                 ("moe_b12x", r"b12x"), ("fp8fp4_gemm", r"deep_gemm::sm120_fp8_fp4_gemm"), ("splitk", r"split_k_reduce"),
                 ("bf16_wmma_gemm", r"cutlass_80_wmma"), ("fp32_gemmSN", r"gemmSN_TN_kernel<float"), ("gemm_other", r"gemm|Gemm|cutlass|cublas"),
                 ("sparse_mla", r"sparse_mla"), ("mhc", r"mhc"), ("quant", r"quant"), ("other", r".")]:
        if re.search(p, n):
            return c

rows = []
ki = 0
for i in range(len(starts) - 1):
    t0, t1 = starts[i], starts[i + 1]
    while ki < len(kern) and kern[ki]["ts"] < t0:
        ki += 1
    j = ki; busy = 0.0; end = t0; c = collections.Counter(); n = 0
    while j < len(kern) and kern[j]["ts"] < t1:
        s, d = kern[j]["ts"], kern[j]["dur"]
        c[cat(kern[j]["name"])] += d; n += 1
        if s + d > end:
            busy += s + d - max(s, end); end = s + d
        j += 1
    rows.append((t1 - t0, busy, c, n))
per = statistics.median(r[0] for r in rows) / 1e3
busy = statistics.median(r[1] for r in rows) / 1e3
print(f"steps={len(rows)}  median step period {per:.2f} ms  GPU busy {busy:.2f} ms ({100*busy/per:.0f}%)  idle {per-busy:.2f} ms"
      f"  kernels/step {statistics.median(r[3] for r in rows):.0f}")
tot = collections.Counter()
for r in rows:
    tot.update(r[2])
n = len(rows)
print(f"kernel-time per step (sum, overlapping streams can exceed busy): {sum(tot.values())/n/1e3:.2f} ms")
for k, v in tot.most_common():
    print(f"  {k:20s} {v/n/1e3:6.2f} ms  {100*v/sum(tot.values()):5.1f}%")
# NCCL calls per step and their individual durations
nc = [e["dur"] for e in kern if "AllReduce" in e["name"]]
print(f"\nall-reduce calls total {len(nc)}  per step {len(nc)/max(n,1):.1f}  median {statistics.median(nc):.1f} us  p10 {sorted(nc)[len(nc)//10]:.1f} us")
