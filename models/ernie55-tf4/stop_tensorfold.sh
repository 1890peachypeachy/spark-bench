#!/usr/bin/env bash
set -euo pipefail
for h in local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  if [ "$h" = local ]; then
    pkill -f "bin/tensorfold-native" >/dev/null 2>&1 || true
  else
    ssh -o BatchMode=yes "$h" "pkill -f "bin/tensorfold-native" >/dev/null 2>&1 || true" &
  fi
done
wait
echo "stopped tensorfold-native on all 4 Sparks"
