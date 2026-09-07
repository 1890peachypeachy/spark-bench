#!/bin/bash
# tel-collect.sh — per-rank telemetry collector (2s cadence), staged to each host.
# CSV: ts_utc, MemAvailable_kB, SwapFree_kB, compact_stall, compact_daemon_wake,
#      pgmigrate_success, psi_mem_some_avg10
while true; do
  TS=$(date -u +%s.%N)
  MEM=$(grep MemAvailable /proc/meminfo | tr -dc 0-9)
  SWAP=$(grep SwapFree /proc/meminfo | tr -dc 0-9)
  CS=$(grep "^compact_stall " /proc/vmstat | awk '{print $2}')
  CW=$(grep "^compact_daemon_wake " /proc/vmstat | awk '{print $2}')
  MS=$(grep "^pgmigrate_success " /proc/vmstat | awk '{print $2}')
  PSI=$(awk '/^some/ {print $2}' /proc/pressure/memory | tr -d 'avg=10: ')
  echo "$TS,$MEM,$SWAP,$CS,$CW,$MS,$PSI"
  sleep 2
done
