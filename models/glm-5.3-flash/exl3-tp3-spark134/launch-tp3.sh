#!/bin/bash
# TP3 lane launcher (spark1+3+4, head spark3). See README.md for traps.
# Runs on the HEAD (spark3). Idempotent: stop-then-launch, then gate.
set -euo pipefail
DIR="\${GLM53_TP3_DIR:-\$HOME/GLM53-TP3}"
cd "\$DIR"
if [ "\${1:-}" = "status" ] || [ "\${1:-}" = "stop" ] || [ "\${1:-}" = "logs" ]; then
  exec ./start-tp3.sh "\$@"
fi
echo "[tp3] stopping any squatting ranks (port 29521 guard) ..."
./start-tp3.sh stop >/dev/null 2>&1 || true
sleep 5
echo "[tp3] launching TP3 ..."
./start-tp3.sh
echo "[tp3] waiting for /health ..."
for i in \$(seq 1 60); do
  code=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 127.0.0.1:8888/health 2>/dev/null || echo 000)
  [ "\$code" = 200 ] && { echo "[tp3] HEALTHY"; break; }
  sleep 30
done
echo "[tp3] post-ready gates:"
curl -s --max-time 8 127.0.0.1:8888/v1/models | head -c 160; echo
curl -s --max-time 8 127.0.0.1:8888/metrics | grep -E cache_config_info | grep -v '^#' | head -1
curl -s --max-time 90 127.0.0.1:8888/v1/chat/completions -H 'Content-Type: application/json' \\
  -d '{"model":"GLM-5.3-Flash-EXL3","messages":[{"role":"user","content":"Reply with exactly: PONG tp3"}],"max_tokens":64,"temperature":0,"enable_thinking":false}' | head -c 240; echo
[ "\$(docker ps --format '{{.Names}}' | grep -c glm53-exl3-tp3)" -ge 1 ] && echo "[tp3] head container up"
