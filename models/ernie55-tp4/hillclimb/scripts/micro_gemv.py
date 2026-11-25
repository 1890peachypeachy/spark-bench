"""GB10 microbench: bf16 x bf16 -> fp32 GEMV at ERNIE's router/compressor shape (N=1024, K=4096), M = 1..16.

Candidates: cuBLAS torch.mm(out_dtype=fp32) [compressor today], fp32 F.linear [router today], the same under cuBLASLt,
and vLLM's cuteDSL ll_bf16_gemm. Timing: CUDA-graph replay of 48 calls rotating 24 weight copies (cold, DRAM-bound like the model), min of 7 (interleaved).
Accuracy: max |out - fp64 reference| and max |out - cuBLAS bf16->fp32| (summation-order differences only expected).
"""
import json, traceback
import torch

torch.manual_seed(0)
N, K = 1024, 4096
NW = 24  # rotate weight copies (24 x 8 MB bf16 = 192 MB, 24 x 16 MB fp32) so every call reads cold from DRAM, as in the model
Ws = [(torch.randn(N, K, device="cuda") * 0.02).to(torch.bfloat16).contiguous() for _ in range(NW)]
W32s = [w.float() for w in Ws]
W, W32 = Ws[0], W32s[0]
res = {"shape": [N, K], "device": torch.cuda.get_device_name(0), "rows": {}}

def graph_us(fn, reps=48, trials=7):
    fn(0); torch.cuda.synchronize()
    s = torch.cuda.Stream()
    with torch.cuda.stream(s):
        fn(1)
    torch.cuda.synchronize()
    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        for i in range(reps):
            fn(i % NW)
    best = 1e30
    for _ in range(trials):
        a, b = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        a.record(); g.replay(); b.record(); torch.cuda.synchronize()
        best = min(best, a.elapsed_time(b) * 1e3 / reps)
    return round(best, 2)

def cands(x):
    c = {
        "cublas_bf16_out32": lambda i=0: torch.mm(x, Ws[i].T, out_dtype=torch.float32),
        "fp32_linear": lambda i=0: torch.nn.functional.linear(x.float(), W32s[i]),
    }
    try:
        from vllm.model_executor.kernels.linear.cute_dsl.ll_bf16 import ll_bf16_gemm, is_available
        res["ll_bf16_available"] = bool(is_available())
        c["ll_bf16_gemm"] = lambda i=0: ll_bf16_gemm(x, Ws[i], torch.float32)
    except Exception as e:
        res["ll_bf16_import_error"] = repr(e)[:200]
    return c

for M in (1, 2, 4, 8, 16):
    x = (torch.randn(M, K, device="cuda")).to(torch.bfloat16)
    ref = (x.double() @ W.double().T)
    base = torch.mm(x, W.T, out_dtype=torch.float32)
    row = {}
    for lib in ("default", "cublaslt"):
        torch.backends.cuda.preferred_blas_library("cublaslt" if lib == "cublaslt" else "cublas")
        for name, fn in cands(x).items():
            key = name if lib == "default" else name + "@lt"
            if lib == "cublaslt" and name == "ll_bf16_gemm":
                continue
            try:
                out = fn(0)
                row[key] = {"us": graph_us(fn),
                            "err_vs_fp64": float((out.double() - ref).abs().max()),
                            "diff_vs_cublas": float((out.float() - base).abs().max())}
            except Exception as e:
                row[key] = {"error": repr(e)[:240], "trace": traceback.format_exc().splitlines()[-3:]}
    torch.backends.cuda.preferred_blas_library("cublas")
    res["rows"][M] = row
res["bytes_bf16_weight"] = N * K * 2
res["floor_us_at_238GBps"] = round(N * K * 2 / 238.6e9 * 1e6, 1)
print(json.dumps(res))
