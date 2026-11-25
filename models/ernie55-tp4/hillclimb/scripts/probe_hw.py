"""Measured GB10 ceilings: device copy bandwidth, read-only reduction bandwidth, BF16 and FP8 GEMM throughput."""
import json, torch

def t_ms(fn, it):
    for _ in range(3):
        fn()
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    best = 1e30
    for _ in range(5):  # min of 5 interleaved timings
        s.record()
        for _ in range(it):
            fn()
        e.record(); torch.cuda.synchronize()
        best = min(best, s.elapsed_time(e) / it)
    return best

out = {"device": torch.cuda.get_device_name(0), "torch": torch.__version__}
n = 4 << 30  # 4 GiB buffers, well past L2
x = torch.empty(n, dtype=torch.uint8, device="cuda"); y = torch.empty_like(x)
ms = t_ms(lambda: y.copy_(x), 10)
out["copy_GBps"] = round(2 * n / (ms / 1e3) / 1e9, 1)  # read + write
xf = x.view(torch.float32)
ms = t_ms(lambda: xf.sum(), 10)
out["read_GBps"] = round(n / (ms / 1e3) / 1e9, 1)
del x, y, xf
for N in (4096, 8192):
    a = torch.randn(N, N, dtype=torch.bfloat16, device="cuda"); b = torch.randn(N, N, dtype=torch.bfloat16, device="cuda")
    ms = t_ms(lambda: a @ b, 10)
    out[f"bf16_gemm_{N}_TFLOPS"] = round(2 * N ** 3 / (ms / 1e3) / 1e12, 1)
try:
    N = 8192
    a = torch.randn(N, N, device="cuda").to(torch.float8_e4m3fn); b = torch.randn(N, N, device="cuda").to(torch.float8_e4m3fn).t()
    one = torch.tensor(1.0, device="cuda")
    ms = t_ms(lambda: torch._scaled_mm(a, b, scale_a=one, scale_b=one, out_dtype=torch.bfloat16), 10)
    out["fp8_gemm_8192_TFLOPS"] = round(2 * N ** 3 / (ms / 1e3) / 1e12, 1)
except Exception as ex:
    out["fp8_gemm_error"] = repr(ex)[:160]
print(json.dumps(out))
