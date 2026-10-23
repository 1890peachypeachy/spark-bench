#!/bin/bash
# Stop this node's m31 downloader/hangovers WITHOUT killing the calling ssh session.
# pkill patterns must not appear as literals anywhere else in the call, so this lives
# in a file and the caller passes nothing but the script path.
set -u
tmux kill-session -t m31 2>/dev/null
tmux kill-session -t m31fan 2>/dev/null
P='m31_downl''oad.py'
for pid in $(ps -eo pid,args | grep -F "$P" | grep -v grep | awk '{print $1}'); do
  kill -9 "$pid" 2>/dev/null
done
sleep 1
echo "remaining: $(ps -eo args | grep -F "$P" | grep -v grep | wc -l)"