#!/usr/bin/env bash
# Build tensorfold-native at an exact commit of the production tree (kernels included), for bisecting, and stage it
# on all 4 Sparks at /var/tmp/ernie55/exp/<name>/bin/tensorfold-native. Production's bin/ and fatbins/ are never
# touched: the commit's own ERNIE kernels are compiled into /var/tmp/ernie55/fatbins-<name> (other fatbins copied).
# Usage: build_at.sh <name> <commit> [optimize=fast]
set -euo pipefail
NAME=${1:?name}; COMMIT=${2:?commit}; OPT=${3:-fast}
ZIG=/var/tmp/tf1017/zig-aarch64-linux-0.17.0/zig
export PATH=/usr/local/cuda/bin:$PATH
PROD=/var/tmp/ernie55/tensorfold-ernie
WT=/var/tmp/ernie55/wt/$NAME
FB=/var/tmp/ernie55/fatbins-$NAME
if [ ! -d "$WT" ]; then git -C $PROD worktree add -q --detach "$WT" "$COMMIT"; fi
cd "$WT" && git checkout -q --detach "$COMMIT" && git reset -q --hard "$COMMIT"
echo "== $(date -Is) building $NAME ($OPT) at $(git rev-parse --short HEAD)"
mkdir -p "$FB" && cp -n /var/tmp/ernie55/fatbins/*.fatbin "$FB/" 2>/dev/null || true
TORCH="-D__CUDA_NO_HALF_OPERATORS__ -D__CUDA_NO_HALF_CONVERSIONS__ -D__CUDA_NO_BFLOAT16_CONVERSIONS__ -D__CUDA_NO_HALF2_OPERATORS__ --expt-relaxed-constexpr -std=c++20"
GEN="-gencode=arch=compute_121a,code=sm_121a -gencode=arch=compute_121a,code=compute_121a -gencode=arch=compute_121,code=compute_121"
for k in "ernie55_ops ops" "ernie55_mxfp4 mxfp4_situ" "ernie55_dsa dsa_attn" "ernie55_hca hca_attn"; do
  set -- $k
  nice -n 15 nvcc -fatbin $TORCH -O3 -I"$WT/zig/kernels/cuda" $GEN -o "$FB/$1.fatbin" "$WT/zig/kernels/cuda/ernie55/$2.cu"
  echo "$1: $(cuobjdump -symbols "$FB/$1.fatbin" 2>/dev/null | grep -c tf_ernie55_) symbols"
done
t0=$(date +%s)
nice -n 15 $ZIG build native -Dfatbins="$FB" -Doptimize=$OPT --cache-dir $PROD/.zig-cache 2>&1 | tail -20
echo "build took $(( $(date +%s) - t0 ))s"
OUT=/var/tmp/ernie55/exp/$NAME/bin
mkdir -p $OUT && cp zig-out/native/bin/tensorfold-native $OUT/tensorfold-native
md=$(md5sum $OUT/tensorfold-native | cut -c1-12)
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  ssh -o BatchMode=yes $h "mkdir -p $OUT" && scp -q $OUT/tensorfold-native $h:$OUT/tensorfold-native &
done
wait
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  m=$(ssh $h "md5sum $OUT/tensorfold-native | cut -c1-12"); [ "$m" = "$md" ] || { echo "MD5 MISMATCH on $h"; exit 1; }
done
echo "STAGED $NAME md5=$md at $OUT ($(git rev-parse --short HEAD))"
