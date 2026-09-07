# local/qwen38-gb10:e1-gemv-on — opt-in GEMV candidate image

Built 2026-09-07 during the tuning campaign (see ../REPORT.md §GEMV).
Built on forge from this directory: `docker build -t local/qwen38-gb10:e1-gemv-on .`
Resulting image ID (identical on all 4 ranks, verified): sha256:1896b6b14e9c0c35ceec6510116145577384add840802d4327ec58f414b55f88

- Base: `local/qwen38-gb10:e1` (UNTOUCHED — candidate is additive and opt-in by image tag).
- Adds the vendored b12x M=1 BF16 vocab GEMV (Apache-2.0, local-inference-lab/b12x
  gemm/bf16_vocab_projection @ master 2026-08-29, vendored via myllmbox runner build
  cf0c755f20c595dcb0cae545a6dc7a36178eefd3; attribution in the module docstring) +
  the gated logits_processor fast path (default OFF; this tag sets ENV MBX_VOCAB_GEMV=1).
- Falls through to the stock cuBLAS path on any shape/dtype/contiguity mismatch.
- Microbench at our per-rank shape (62080x2560 bf16, M=1): 1.225 ms vs 1.799 ms = 1.47x,
  rel err 5.4e-05. Server A/B at k4: C1 code +4.0%, C16 +3.2%, C4/C8 neutral.
