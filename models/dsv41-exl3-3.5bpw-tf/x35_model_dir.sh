#!/bin/bash
# Build the rank-0 MODEL_DIR for the TensorFold lane from the LibertAI 3.5bpw pack.
# Real copies (not symlinks): the container mounts MODEL_DIR and the server opens the vision shards by name.
set -eu
T=/var/tmp/tf1017
M=/var/tmp/models/DeepSeek-V4.1-Flash-1017-EXL3-3.5bpw
if [ -d "$T/model" ]; then mv "$T/model" "$T/model.symlinks-bak-$(date +%H%M%S)"; fi
mkdir -p "$T/model"
cd "$T/model"
for f in config.json tokenizer.json tokenizer_config.json model.safetensors.index.json exl3_k_map.json generation_config.json; do
  if [ -f "$M/$f" ]; then cp "$M/$f" .; fi
done
cp "$M/model-00043-of-00044.safetensors" "$M/model-00044-of-00044.safetensors" .
cp "$T/recipe/chat/chat_template.jinja" ./chat_template.jinja
ls -la
if cmp -s "$M/chat_template.jinja" ./chat_template.jinja; then
  echo "template: identical to the pack's"
else
  echo "template: recipe's differs from the pack's (recipe's is checked 71/71 against DeepSeek's reference encoder)"
fi
du -sh .
python3 - <<EOF
import json
m = json.load(open("$T/model/model.safetensors.index.json"))["weight_map"]
print("vision/aligner files:", sorted({v for k, v in m.items() if k.startswith(("vision", "aligner", "image_"))}))
EOF
