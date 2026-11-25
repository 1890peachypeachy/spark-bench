#!/usr/bin/env bash
# Rebuild ERNIE 5.5's fatbins with TensorFold's own nvcc flags (zig/build/cuda_kernels.zig torch_flags + per-kernel
# flags + -I zig/kernels/cuda; sm_121a SASS like the originals). Run on spark3.
set -euo pipefail
export PATH=/usr/local/cuda/bin:$PATH
TF=/var/tmp/ernie55/tensorfold-ernie/zig
OUT=/var/tmp/ernie55/fatbins
TORCH="-D__CUDA_NO_HALF_OPERATORS__ -D__CUDA_NO_HALF_CONVERSIONS__ -D__CUDA_NO_BFLOAT16_CONVERSIONS__ -D__CUDA_NO_HALF2_OPERATORS__ --expt-relaxed-constexpr -std=c++20"
GLUE="-O3 --fmad=false --ftz=false --prec-div=true --prec-sqrt=true"
GEN="-gencode=arch=compute_121a,code=sm_121a -gencode=arch=compute_121a,code=compute_121a -gencode=arch=compute_121,code=compute_121"
build() { # name src flags
  nvcc -fatbin $TORCH $3 -I$TF/kernels/cuda $GEN -o $OUT/$1.fatbin $TF/kernels/cuda/$2.cu
  echo "$1: $(cuobjdump -symbols $OUT/$1.fatbin 2>/dev/null | grep -c 'tf_ernie55_') symbols"
}
build ernie55_ops ernie55/ops "$GLUE"
build ernie55_mxfp4 ernie55/mxfp4_situ "-O3"
build ernie55_dsa ernie55/dsa_attn "-O3"
