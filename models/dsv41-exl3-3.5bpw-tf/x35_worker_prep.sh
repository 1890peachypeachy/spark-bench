#!/bin/bash
# Per-worker prep for the TensorFold TP4 lane (runs ON the worker, detached, markers in ~/x35-state).
# usage: x35_worker_prep.sh <rank>
#   1. load the NGC image from spark3 over the CX7 fabric (docker save | docker load)
#   2. node_inputs.sh: this rank's weight file + token map, reading the pack over NFS (/var/tmp/models, ro)
#   3. copy the two Engram shards (base 1017 checkpoint shards 47/48) to local NVMe (engine reads rows by offset)
set -u
R="${1:?rank}"
T=/var/tmp/tf1017
M=/var/tmp/models/DeepSeek-V4.1-Flash-1017-EXL3-3.5bpw
IMG=nvcr.io/nvidia/pytorch:26.07-py3
HEAD=spark3@10.73.0.3
ST=$HOME/x35-state; mkdir -p "$ST" $T/cache $T/engram
exec >> "$HOME/logs/x35-prep-r$R.log" 2>&1
echo "=== prep rank $R $(date -u +%FT%TZ) ==="
rm -f "$ST/PREP_DONE_r$R" "$ST/PREP_FAIL_r$R"

if ! docker image inspect $IMG >/dev/null 2>&1; then
  echo "loading image from head"
  ssh -o BatchMode=yes $HEAD "docker save $IMG" | docker load || { echo FAIL image; touch "$ST/PREP_FAIL_r$R"; exit 1; }
fi
docker image inspect $IMG --format '{{.Id}}' || { touch "$ST/PREP_FAIL_r$R"; exit 1; }

export IMAGE=$IMG
$T/engine-bin-v035/node_inputs.sh $M $T/cache $R || { echo FAIL inputs; touch "$ST/PREP_FAIL_r$R"; exit 1; }

for n in 47 48; do
  f=model-000$n-of-00048.safetensors
  S=/var/tmp/models/DeepSeek-V4.1-Flash-1017/$f
  if [ "$(stat -c %s $T/engram/$f 2>/dev/null)" = "$(stat -c %s $S)" ]; then echo "$f already complete"; continue; fi
  dd if=$S of=$T/engram/$f bs=16M iflag=direct oflag=direct 2>&1 | tail -1
done
cp /var/tmp/models/DeepSeek-V4.1-Flash-1017/model.safetensors.index.json $T/engram/
ls -la $T/engram $T/cache/rank-cache
touch "$ST/PREP_DONE_r$R"
echo "=== prep rank $R DONE $(date -u +%FT%TZ) ==="
