#!/usr/bin/env bash
# Evict everything ComfyUI is holding WITHOUT taking the UI down.
#
# Use when you are DONE creating and want the memory back for something else
# (bringing a GLM/vLLM rank up, another lane, etc).
#
# You do NOT need this to switch between ComfyUI models -- Dynamic VRAM already
# evicts its own weights under pressure. ComfyUI only ever evicts for ITSELF; it
# will not release memory because another process wants it. Hence this script.
set -uo pipefail

# NOTE: the container publishes to the tailnet IP ONLY (never 0.0.0.0), so
# 127.0.0.1:8188 does NOT resolve even on spark2 itself. Default to the tailnet IP.
HOST="${COMFY_HOST:-$(tailscale ip -4 2>/dev/null | head -1)}"
HOST="${HOST:-127.0.0.1}"
PORT="${COMFY_PORT:-8188}"
BASE="http://${HOST}:${PORT}"

# Host/container stats only work when run ON spark2. Running this from the Mac mini
# over Tailscale still evicts correctly; it just can't report local memory.
mem() {
  command -v free >/dev/null 2>&1 \
    && free -g | awk '/Mem:/{printf "used %sG / avail %sG", $3, $7}' \
    || printf 'n/a (not spark2)'
}
cmem() {
  command -v docker >/dev/null 2>&1 \
    && docker stats spark-comfy --no-stream --format '{{.MemUsage}}' 2>/dev/null \
    || printf 'n/a'
}

echo "before:  host $(mem)   |  spark-comfy $(cmem)"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
  -X POST -H 'Content-Type: application/json' \
  -d '{"unload_models":true,"free_memory":true}' \
  "${BASE}/free")

if [ "$code" != "200" ]; then
  echo "FAILED: /free returned HTTP ${code}" >&2
  exit 1
fi

sleep 4
echo "after:   host $(mem)   |  spark-comfy $(cmem)"

# prove the UI is still serving
ui=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${BASE}/system_stats")
echo "ui:      HTTP ${ui} (server still up -- browser tab stays usable)"
