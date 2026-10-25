#!/bin/bash
# make_blobs.sh for OUR lane: per-rank wo_b blobs of the Keys 1017 EXL3 overlay for the TensorFold rank caches.
# Adapted from tonyd2wild runs/2026-10-18-1017-tensorfold-uncensored/tools/make_blobs.sh for:
#   - our engine dir (engine-bin-v035, which carries the TF_RDMA_GID / TF_SEED_RANDOM patches) and our pack path
#   - our sidecar location on spark3 (/home/spark3/dsv41-1017-wo-b-ablit, sha256 verified)
#   - our fabric (rank 0 = spark3@10.73.0.3)
# Runs ON spark3. Produces /var/tmp/tf1017-ablit/{idx,blobs/r0..r3}.
set -euo pipefail
W=/var/tmp/tf1017-ablit
M=/var/tmp/models/DeepSeek-V4.1-Flash-1017-EXL3-3.5bpw
RC=/var/tmp/tf1017/engine-bin-v035/tf-dsv41-rank-cache
OV=/var/tmp/tf1017-ablit/overlay
mkdir -p $W/idx $OV
# overlay files: sidecar + the two patch scripts, copied from the verified local set
for f in exl3_wo_b_l10_35_1017.safetensors patch_rank_cache_wob.py apply_rank_blobs.py; do
  [ -s $OV/$f ] || cp /home/spark3/dsv41-1017-wo-b-ablit/$f $OV/$f
done
echo "$(sha256sum $OV/exl3_wo_b_l10_35_1017.safetensors | cut -d' ' -f1)  (expect ce06dfb0e75a40a471bdff60676a687cf6efe4a126d33f54c2af482795ac6609)"

for g in 0 1 2 3; do
  mkdir -p $W/idx/r$g
  $RC $M $W/idx/r$g $g 4 --parity --index-only > $W/idx/r$g/index.json
  python3 - $W/idx/r$g/index.json $W/idx/idx_r$g.json <<'PY'
import json, sys
rows = json.load(open(sys.argv[1])); out = []
for name, dt, shape, off, nb in rows:
    base, *rest = name.split("|")
    p = base.split(".")
    if len(p) == 4 and p[0] == "layers" and p[2] == "attn" and p[3] == "wo_b" and 10 <= int(p[1]) <= 35:
        out.append({"layer": int(p[1]), "rest": "|".join(rest), "off": off, "nbytes": nb, "name": name})
json.dump(out, open(sys.argv[2], "w"))
print("rank", sys.argv[1].split("/")[-2], "wo_b rows", len(out), "bytes", sum(r["nbytes"] for r in out))
PY
done

docker run --rm --network none --user "$(id -u):$(id -g)" -e HOME=/tmp -v $W:/w --entrypoint bash nvcr.io/nvidia/pytorch:26.07-py3 -c '
python3 -c "import safetensors" 2>/dev/null || pip install -q --user safetensors 2>&1 | tail -1
for g in 0 1 2 3; do python3 /w/overlay/patch_rank_cache_wob.py --sidecar /w/overlay/exl3_wo_b_l10_35_1017.safetensors --idx /w/idx/idx_r$g.json --dump-dir /w/blobs/r$g; done'
du -sh $W/blobs/r*
