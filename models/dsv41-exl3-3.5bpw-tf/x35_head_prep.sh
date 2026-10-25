#!/bin/bash
# Head (rank 0, spark3) prep after node_inputs finishes:
#   1. wait for rank-0 inputs, 2. local Engram copy (shards 47/48 of base 1017), 3. make + verify the kernel kit
#   (RoPE tables + image bias), 4. push the finished kit to the workers over the fabric.
set -u
T=/var/tmp/tf1017
ST=$HOME/x35-state
exec >> "$HOME/logs/x35-prep-head.log" 2>&1
echo "=== head prep $(date -u +%FT%TZ) ==="
rm -f "$ST/PREP_DONE_r0" "$ST/PREP_FAIL_r0"
until grep -q 'INPUTS_EXIT=' "$HOME/logs/x35-inputs-r0.log"; do sleep 20; done
grep -q 'INPUTS_EXIT=0' "$HOME/logs/x35-inputs-r0.log" || { echo "rank0 inputs FAILED"; touch "$ST/PREP_FAIL_r0"; exit 1; }
echo "rank0 inputs ok"

mkdir -p $T/engram
for n in 47 48; do
  f=model-000$n-of-00048.safetensors
  S=/var/tmp/models/DeepSeek-V4.1-Flash-1017/$f
  if [ "$(stat -c %s $T/engram/$f 2>/dev/null)" = "$(stat -c %s $S)" ]; then echo "$f already complete"; continue; fi
  dd if=$S of=$T/engram/$f bs=16M iflag=direct oflag=direct 2>&1 | tail -1
done
cp /var/tmp/models/DeepSeek-V4.1-Flash-1017/model.safetensors.index.json $T/engram/

cd $T/recipe/kit || exit 1
./verify_kit.sh /var/tmp/models/DeepSeek-V4.1-Flash-1017-EXL3-3.5bpw /var/tmp/models/DeepSeek-V4.1-Flash-1017 2>&1 | tail -6
echo "verify_kit rc=${PIPESTATUS[0]}"
tail -1 "$HOME/logs/x35-prep-head.log" | grep -q 'rc=0' || { echo "kit verify FAILED"; touch "$ST/PREP_FAIL_r0"; exit 1; }

for t in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  rsync -a --delete $T/recipe/kit/ $t:$T/kit/ && echo "kit pushed $t"
  rsync -a --exclude='*.safetensors' $T/model/ $t:$T/model/ && echo "model-dir (small files) pushed $t"
done
touch "$ST/PREP_DONE_r0"
echo "=== head prep DONE $(date -u +%FT%TZ) ==="
