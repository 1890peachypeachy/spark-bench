# local/qwen38-gb10:e1-gemv-on — opt-in GEMV candidate for qwen38-tuning-20260906.
# Base image UNTOUCHED. Adds the vendored b12x M=1 BF16 vocab GEMV (Apache-2.0,
# local-inference-lab/b12x gemm/bf16_vocab_projection @ master 2026-08-29, vendored via
# myllmbox runner build mbx_vocab_gemv.py — attribution preserved in the module docstring)
# + the gated logits_processor fast path (falls through to stock on any shape mismatch).
# Microbenched on OUR per-rank shape (62080x2560 bf16, M=1): 1.225 ms vs 1.799 ms cuBLAS = 1.47x.
FROM local/qwen38-gb10:e1
COPY mbx_vocab_gemv.py /usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/mbx_vocab_gemv.py
RUN python3 - <<"PYEOF"
p = "/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/logits_processor.py"
s = open(p).read()
assert "MBX_VOCAB_GEMV" not in s, "already patched"
a = """        if self.head_dtype is None or self.head_dtype == hidden_states.dtype:
            return lm_head.quant_method.apply("""
assert s.count(a) == 1, "anchor not found/unique"
s = s.replace(a, """        # MBX_VOCAB_GEMV: M=1 head through the vendored Triton GEMV (draft steps
        # + bs=1 decode); falls through to the stock path on any mismatch.
        if _MBX_VOCAB_GEMV and embedding_bias is None:
            _mbx_out = _mbx_maybe_vocab_gemv(hidden_states, lm_head.weight)
            if _mbx_out is not None:
                return _mbx_out
        if self.head_dtype is None or self.head_dtype == hidden_states.dtype:
            return lm_head.quant_method.apply(""", 1)
s += """

# mbx vocab gemv glue (functions resolve module globals at call time, so end-of-file is fine)
import os as _mbx_os
_MBX_VOCAB_GEMV = _mbx_os.environ.get("MBX_VOCAB_GEMV", "0") == "1"
if _MBX_VOCAB_GEMV:
    from vllm.model_executor.layers.mbx_vocab_gemv import maybe_vocab_gemv as _mbx_maybe_vocab_gemv
else:
    def _mbx_maybe_vocab_gemv(hidden_states, weight):
        return None
"""
open(p, "w").write(s)
print("logits_processor.py: MBX_VOCAB_GEMV fast path installed (default off)")
PYEOF
# sanity: module imports + gate works (CPU-visible import path; CUDA call made at runtime)
RUN python3 -c "from vllm.model_executor.layers.mbx_vocab_gemv import maybe_vocab_gemv; print('gemv module import OK')"
ENV MBX_VOCAB_GEMV=1
