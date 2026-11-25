
# 11. GB10 (sm_12x) low-M bf16 x bf16 -> fp32 GEMVs through vLLM's cuteDSL ll_bf16_gemm instead of cuBLAS / fp32 F.linear.
# cuBLAS drops to an SM80 16x16 WMMA kernel for narrow N at 2-16 tokens on sm_12x (vLLM's own note in layers/utils.py), and
# GateLinear's specialized router tiers are gated to Hopper / Blackwell-100. Both GEMVs below are bf16 x bf16 with fp32
# accumulation and fp32 output before and after; only the summation order changes. Applied for M <= 16 only.
import os as _os11
_P11 = "/usr/local/lib/python3.12/dist-packages"

# 11a. DeepSeek-V4 compressor fused wkv/wgate projection (ERNIE's HCA layers): torch.mm(out_dtype=fp32) -> ll_bf16_gemm.
p11a = _P11 + "/vllm/models/deepseek_v4/compressor.py"
s11a = open(p11a).read()
old11a = """class DeepseekV4CompressorKVScoreLinear(MergedColumnParallelLinear):
    \"\"\"Fused `wkv`/`wgate` projection with the FP32 output the compressor
    state accumulates in.\"\"\"

    def forward(self, input_: torch.Tensor) -> torch.Tensor:
        return torch.mm(input_, self.weight.T, out_dtype=torch.float32)"""
new11a = """def _sm12x_ll_bf16_gemm():
    try:
        if not (current_platform.is_cuda() and current_platform.is_device_capability_family(120)):
            return None
        from vllm.model_executor.kernels.linear.cute_dsl.ll_bf16 import is_available, ll_bf16_gemm
        return ll_bf16_gemm if is_available() else None
    except Exception:
        return None


_SM12X_LL_BF16_GEMM = _sm12x_ll_bf16_gemm()


class DeepseekV4CompressorKVScoreLinear(MergedColumnParallelLinear):
    \"\"\"Fused `wkv`/`wgate` projection with the FP32 output the compressor
    state accumulates in.\"\"\"

    def forward(self, input_: torch.Tensor) -> torch.Tensor:
        if (
            _SM12X_LL_BF16_GEMM is not None
            and input_.dim() == 2
            and input_.shape[0] <= 16
            and input_.dtype == torch.bfloat16
            and self.weight.dtype == torch.bfloat16
        ):
            return _SM12X_LL_BF16_GEMM(input_, self.weight, torch.float32)
        return torch.mm(input_, self.weight.T, out_dtype=torch.float32)"""
assert s11a.count(old11a) == 1, "compressor.py DeepseekV4CompressorKVScoreLinear target not found"
open(p11a, "w").write(s11a.replace(old11a, new11a, 1))
print("Patched compressor.py (sm_12x ll_bf16_gemm for M<=16) cleanly!")

# 11b. ERNIE router: keep the gate in the checkpoint's bf16 and let GateLinear's tier 1 (ll_bf16_gemm, fp32 out) run on sm_12x.
p11b = _P11 + "/vllm_ernie/models/ernie5_5/nvidia/moe.py"
s11b = open(p11b).read()
old11b = """        self.gate = GateLinear(
            hidden_size,
            2 * num_experts,
            bias=False,
            out_dtype=torch.float32,
            params_dtype=torch.float32,
            prefix=f"{prefix}.gate",
        )"""
new11b = """        _sm12x_ll = _ernie_sm12x_ll_bf16_available()
        self.gate = GateLinear(
            hidden_size,
            2 * num_experts,
            bias=False,
            out_dtype=torch.float32,
            params_dtype=torch.bfloat16 if _sm12x_ll else torch.float32,
            prefix=f"{prefix}.gate",
        )
        if _sm12x_ll:
            self.gate.allow_ll_bf16_gemm = True"""
assert s11b.count(old11b) == 1, "moe.py Ernie5_5MoE gate target not found"
s11b = s11b.replace(old11b, new11b, 1)
old11c = "class Ernie5_5MoE(nn.Module):"
new11c = """def _ernie_sm12x_ll_bf16_available() -> bool:
    try:
        from vllm.platforms import current_platform

        if not (current_platform.is_cuda() and current_platform.is_device_capability_family(120)):
            return False
        from vllm.model_executor.kernels.linear.cute_dsl.ll_bf16 import is_available

        return bool(is_available())
    except Exception:
        return False


class Ernie5_5MoE(nn.Module):"""
assert s11b.count(old11c) == 1, "moe.py Ernie5_5MoE class target not found"
open(p11b, "w").write(s11b.replace(old11c, new11c, 1))
print("Patched moe.py (bf16 router weights + GateLinear ll_bf16_gemm tier on sm_12x) cleanly!")
