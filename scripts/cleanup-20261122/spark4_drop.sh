#!/bin/bash
# Runs ON spark4 as user spark4 (all targets are owned by it). Drops the ComfyUI + DeepSeek payload that is replicated on other Sparks.
set -u
M=/var/tmp/spark4-dropped-manifest-20261122.txt
echo "# spark4 payload dropped 2026-11-22 (Victor). Peers verified identical (names+sizes): comfy h3/models/yue2 on spark1+spark3; tf1017 engram/model on spark2+spark3." > $M
for d in /var/tmp/comfy/h3 /var/tmp/comfy/models /var/tmp/comfy/yue2 /var/tmp/tf1017/engram /var/tmp/tf1017/model /var/tmp/tf1017/cache; do
  echo "## $d" >> $M; find "$d" -type f -printf '%s %p\n' 2>/dev/null >> $M
done
echo "manifest: $(wc -l < $M) lines"
docker inspect comfy-studio > /var/tmp/spark4-comfy-studio-container-inspect-20261122.json 2>/dev/null && echo "saved container inspect"
echo "before: $(df -h / | tail -1 | awk '{print $4" free ("$5" used)"}')"
if docker ps -q --filter name=comfy-studio | grep -q .; then echo "comfy-studio is RUNNING - abort"; exit 2; fi
docker rm comfy-studio 2>&1 | tail -1
for d in /var/tmp/comfy/h3 /var/tmp/comfy/models /var/tmp/comfy/yue2 /var/tmp/tf1017/engram /var/tmp/tf1017/model /var/tmp/tf1017/cache; do
  case "$d" in /var/tmp/comfy/*|/var/tmp/tf1017/*) ;; *) echo "REFUSE $d"; continue;; esac
  [ -L "$d" ] && { echo "REFUSE symlink $d"; continue; }
  s=$(du -sh "$d" 2>/dev/null | cut -f1)
  rm -rf -- "$d" && echo "removed $d ($s)  -> free now $(df -h / | tail -1 | awk '{print $4}')"
done
docker rmi spark-comfy:m-fd7639f4 2>&1 | tail -2
echo "after:  $(df -h / | tail -1 | awk '{print $4" free ("$5" used)"}')"
echo "left in place: $(du -sh /var/tmp/comfy /var/tmp/tf1017 2>/dev/null | tr '\n' ' ')"
