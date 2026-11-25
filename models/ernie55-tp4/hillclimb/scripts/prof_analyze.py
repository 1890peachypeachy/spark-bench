"""Break a vLLM torch-profiler trace into per-decode-step GPU time by kernel category, plus GPU idle inside steps."""
import gzip, json, re, sys, collections, statistics

tr = json.load(gzip.open(sys.argv[1]))
ev = tr["traceEvents"] if isinstance(tr, dict) else tr
kern = sorted([e for e in ev if e.get("cat") == "kernel" and e.get("ph") == "X"], key=lambda e: e["ts"])
ann = sorted([e for e in ev if e.get("cat") == "gpu_user_annotation" and e.get("ph") == "X"
              and str(e.get("name", "")).startswith("execute_context")], key=lambda e: e["ts"])

def cat(n):
    rules = [("nccl_allreduce_bf16", r"ncclDevKernel_AllReduce_bf16"), ("nccl_allreduce_f32", r"ncclDevKernel_AllReduce_f32"),
             ("nccl_other", r"nccl"), ("moe_b12x", r"b12xmoe|b12x"), ("fp8fp4_gemm(deep_gemm)", r"deep_gemm::sm120_fp8_fp4_gemm"),
             ("deep_gemm_splitk", r"split_k_reduce"), ("bf16_gemm_cutlass80_wmma", r"cutlass_80_wmma"),
             ("fp32_gemmSN", r"gemmSN_TN_kernel<float"), ("gemm_other", r"gemm|Gemm|sm90|sm100|cublas|cutlass"),
             ("attn_sparse_mla", r"sparse_mla"), ("mhc", r"mhc"), ("quant", r"quant"),
             ("indexer", r"indexer|topk|mqa_logits"), ("router", r"routing|sigmoid|topk_softmax"),
             ("elementwise/norm/other", r".")]
    for c, p in rules:
        if re.search(p, n):
            return c
    return "?"

# group kernels into steps using the annotation ranges (one per scheduler step); dedupe annotations by ts
steps = []
seen = set()
for a in ann:
    k = (round(a["ts"]), round(a["dur"]))
    if k in seen:
        continue
    seen.add(k)
    steps.append((a["ts"], a["ts"] + a["dur"], a["name"]))
steps.sort()
print(f"kernels={len(kern)} annotations={len(ann)} unique_steps={len(steps)}")
names = collections.Counter(s[2] for s in steps)
print("step kinds:", names.most_common(5))

# per-step: wall, busy (union of kernel intervals), per-category
rows = []
ki = 0
for (t0, t1, nm) in steps:
    while ki < len(kern) and kern[ki]["ts"] < t0:
        ki += 1
    j = ki; busy = 0.0; cur_end = t0; c = collections.Counter()
    while j < len(kern) and kern[j]["ts"] < t1:
        e = kern[j]; s, d = e["ts"], e["dur"]
        c[cat(e["name"])] += d
        if s + d > cur_end:
            busy += (s + d) - max(s, cur_end); cur_end = s + d
        j += 1
    rows.append((nm, t1 - t0, busy, c))

dec = [r for r in rows if "generation_1" in r[0] and "context_0" in r[0]]
print(f"pure-decode steps: {len(dec)}")
if dec:
    wall = statistics.median(r[1] for r in dec) / 1e3; busy = statistics.median(r[2] for r in dec) / 1e3
    print(f"median step wall {wall:.2f} ms, GPU busy {busy:.2f} ms ({100*busy/wall:.0f}%), idle {wall-busy:.2f} ms")
    tot = collections.Counter()
    for r in dec:
        tot.update(r[3])
    n = len(dec); s = sum(tot.values()) / n / 1e3
    print(f"\nmean kernel time per decode step: {s:.2f} ms")
    for k, v in tot.most_common():
        print(f"  {k:28s} {v/n/1e3:7.2f} ms  {100*v/sum(tot.values()):5.1f}%")
# step-to-step gaps (time between one step's end and the next's start)
gaps = [steps[i + 1][0] - steps[i][1] for i in range(len(steps) - 1)]
if gaps:
    print(f"\ninter-step gap median {statistics.median(gaps)/1e3:.2f} ms, p90 {sorted(gaps)[int(.9*len(gaps))]/1e3:.2f} ms")
    period = [steps[i + 1][0] - steps[i][0] for i in range(len(steps) - 1)]
    print(f"step period median {statistics.median(period)/1e3:.2f} ms -> {1e6/statistics.median(period):.1f} steps/s")
