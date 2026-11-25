"""Attribute GPU kernels to the CPU ops that launched them (eager trace): kernel -> correlation -> launch -> enclosing cpu_ops."""
import bisect, collections, gzip, json, re, sys

tr = json.load(gzip.open(sys.argv[1]))
ev = tr["traceEvents"]
pat = re.compile(sys.argv[2] if len(sys.argv) > 2 else r"cutlass_80_wmma|gemmSN_TN_kernel<float|AllReduce_f32|AllReduce_bf16|sm120_fp8_fp4_gemm")
kern = [e for e in ev if e.get("cat") == "kernel" and e.get("ph") == "X"]
launch = {e["args"]["correlation"]: e for e in ev if e.get("cat") in ("cuda_runtime", "cuda_driver") and "correlation" in e.get("args", {})}
ops = collections.defaultdict(list)
for e in ev:
    if e.get("cat") == "cpu_op" and e.get("ph") == "X":
        ops[e["tid"]].append(e)
for t in ops:
    ops[t].sort(key=lambda e: e["ts"])
starts = {t: [e["ts"] for e in v] for t, v in ops.items()}

def stack(tid, ts):
    v, s = ops.get(tid, []), starts.get(tid, [])
    i = bisect.bisect_right(s, ts)
    out = []
    for e in reversed(v[max(0, i - 4000):i]):  # enclosing ops started before ts and end after it
        if e["ts"] <= ts <= e["ts"] + e["dur"]:
            out.append(e)
    return sorted(out, key=lambda e: e["ts"])  # outermost first

agg = collections.defaultdict(lambda: [0, 0.0])
shapes = {}
for k in kern:
    m = pat.search(k["name"])
    if not m:
        continue
    l = launch.get(k["args"].get("correlation"))
    if not l:
        continue
    st = stack(l["tid"], l["ts"])
    names = [e["name"] for e in st if not e["name"].startswith(("aten::empty", "aten::to", "aten::_to"))]
    key = (m.group(0)[:28], " > ".join(names[-3:]))
    agg[key][0] += 1; agg[key][1] += k["dur"]
    if key not in shapes and st:
        shapes[key] = st[-1].get("args", {}).get("Input Dims")
for (kn, path), (n, d) in sorted(agg.items(), key=lambda x: -x[1][1])[:25]:
    print(f"{kn:28s} n={n:5d} {d/1e3:8.1f} ms  | {path[:150]}")
    if shapes.get((kn, path)):
        print(f"{'':28s} shapes {str(shapes[(kn, path)])[:150]}")
