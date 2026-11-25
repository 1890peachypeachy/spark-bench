"""Which cuBLAS kernel does torch.mm(x[4,4096] bf16, W[1024,4096].T, out_dtype=fp32) pick, contiguous vs strided input?"""
import json, torch
from torch.profiler import profile, ProfilerActivity

N, K, M = 1024, 4096, 4
Ws = [(torch.randn(N, K, device="cuda") * 0.02).to(torch.bfloat16) for _ in range(24)]
base = torch.randn(M, 4 * K, device="cuda").to(torch.bfloat16)
variants = {
    "contiguous": torch.randn(M, K, device="cuda").to(torch.bfloat16),
    "row_stride_4K": base[:, :K],             # a column slice of a wider buffer (stride 16384)
    "transposed_view": torch.randn(K, M, device="cuda").to(torch.bfloat16).t(),
}
out = {}
for name, x in variants.items():
    for i in range(3):
        torch.mm(x, Ws[i].T, out_dtype=torch.float32)
    torch.cuda.synchronize()
    with profile(activities=[ProfilerActivity.CUDA]) as p:
        for i in range(48):
            torch.mm(x, Ws[i % 24].T, out_dtype=torch.float32)
        torch.cuda.synchronize()
    ks = {}
    for e in p.events():
        if e.device_type.name == "CUDA":
            k = ks.setdefault(e.name[:90], [0, 0.0]); k[0] += 1; k[1] += e.device_time
    out[name] = {k: {"n": v[0], "avg_us": round(v[1] / v[0], 1)} for k, v in ks.items()}
    out[name]["stride"] = list(x.stride())
print(json.dumps(out, indent=1))
