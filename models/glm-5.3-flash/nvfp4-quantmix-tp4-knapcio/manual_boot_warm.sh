#!/usr/bin/env bash
# Manual boot-warm mitigation for the GLM-5.3-Flash TP4 (knapcio) recipe.
#
# Upstream's own BOOT_WARM=1 mechanism (scripts/boot_warm.py) is broken -
# it imports bench/prefill_bench.py, which does not exist in this repo, and
# crashes silently on every launch with no log/pid file and no visible error
# in start.sh's own output. See README.md "Real root cause of the garbled
# first-interaction bug" in this directory for the full writeup.
#
# Run this AFTER `./start.sh status` reports `health 200` and BEFORE pointing
# any real traffic at the endpoint. Sends a couple of long-context requests at
# non-zero temperature (matching real agent traffic, not qeval's greedy
# temperature=0) to warm the prefix cache, CUDA graphs, and the custom
# adaptive-k scheduler before a real user's first request can land on a cold
# engine.
#
# usage: ./manual_boot_warm.sh [base_url] [served_model_name]
set -euo pipefail
BASE=${1:-http://127.0.0.1:8888}
MODEL=${2:-GLM-5.3-Flash-EXL3}

# ~16k token filler, matches upstream's intended BOOT_WARM_TOKENS default, so the
# first real long-context prompt doesn't also pay a first-long-prefill cost.
FILLER=$(python3 -c "print(('The quick brown fox jumps over the lazy dog. ' * 3000)[:65000])")

for i in 1 2; do
  echo "warm-up request $i/2..."
  curl -s -X POST "$BASE/v1/chat/completions" -H "Content-Type: application/json" -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\": \"user\", \"content\": \"Context follows, then answer: what is 2+2?\\n\\n$FILLER\"}],
    \"max_tokens\": 64,
    \"temperature\": 0.7
  }" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  finish_reason:', d['choices'][0].get('finish_reason'), '| tokens:', d.get('usage',{}).get('completion_tokens'))"
done
echo "boot-warm (manual) done"
