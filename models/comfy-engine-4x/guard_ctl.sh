#!/bin/bash
# guard_ctl.sh start|stop|status — manage h3_guard.sh for the studio container.
#
# WHY THIS EXISTS: `ssh node "pkill -f 'h3_guard.sh comfy-studio'"` also kills the SSH shell, because
# that shell's OWN command line contains the pattern. Moving the pattern inside this script keeps every
# caller's command line clean, so stop/start cannot commit suicide.
# The guard itself is h3_guard.sh next to this file; it kills the ComfyUI container (never the rank)
# if MemAvailable drops under the floor (default 4096 MB).
N=${STUDIO_NAME:-comfy-studio}
G="$(cd "$(dirname "$0")" && pwd)/h3_guard.sh"
PAT="^/bin/bash $G $N"

case "${1:-status}" in
  start)
    if ! pgrep -f "$PAT" >/dev/null; then
      setsid nohup /bin/bash "$G" "$N" >/dev/null 2>&1 < /dev/null &
      sleep 4
    fi
    printf 'guard=%s comfy=%s\n' "$(pgrep -f "$PAT" | tr '\n' ' ')" \
      "$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${STUDIO_PORT:-8188}/system_stats")"
    ;;
  stop)
    if pgrep -f "$PAT" >/dev/null; then pkill -f "$PAT" && echo "guard stopped"; else echo "no guard running"; fi
    ;;
  status)
    pgrep -f "$PAT" >/dev/null && pgrep -af "$PAT" || { echo "no guard running"; exit 1; }
    ;;
  *) echo "usage: guard_ctl.sh start|stop|status" >&2; exit 2 ;;
esac
