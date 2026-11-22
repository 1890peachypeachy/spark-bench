#!/bin/bash
# Runs on each Spark (ssh -n node 'bash -s' is NOT used: copied then executed). Removes spark-ds41f:1107 only if it IS the archived image and nothing runs it.
WANT=sha256:d686c3673e732cc10630ffabff115ed5d3c7e9082449faa49d31fd49c7aca54d
IMG=spark-ds41f:1107
b=$(df -B1 --output=avail / | tail -1)
id=$(docker image inspect $IMG --format '{{.Id}}' 2>/dev/null)
[ -n "$id" ] || { echo "no $IMG here"; exit 0; }
[ "$id" = "$WANT" ] || { echo "DIFFERENT image id ($id) - NOT removing"; exit 3; }
if [ -n "$(docker ps -q --filter ancestor=$IMG)" ]; then echo "a RUNNING container uses it - NOT removing"; exit 4; fi
c=$(docker ps -aq --filter ancestor=$IMG)
[ -n "$c" ] && echo "removing stopped containers: $(docker rm $c | tr '\n' ' ')"
docker rmi $IMG 2>&1 | tail -1
a=$(df -B1 --output=avail / | tail -1)
echo "free $(awk -v x=$b 'BEGIN{printf "%.1f", x/1e9}') -> $(awk -v x=$a 'BEGIN{printf "%.1f", x/1e9}') GB   still has image: $(docker image inspect $IMG >/dev/null 2>&1 && echo YES || echo no)"
