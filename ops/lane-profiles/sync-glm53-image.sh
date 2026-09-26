#!/usr/bin/env bash
# sync-glm53-image.sh — push the head's current GLM EXL3 image to the workers over
# the RoCE fabric (10.73.0.x), so all three ranks carry the SAME recipe stamp and
# start-tp3.sh does not trigger a rebuild on the workers.
#
# Run ON the head (spark3). The Mac cannot route to 10.73.0.x.
set -euo pipefail
IMG="ghcr.io/miaai-lab/glm-5.3-flash-2x-dgx-sparks:exl3-instanttensor"
HEAD_STAMP="$(docker image inspect "$IMG" --format '{{ index .Config.Labels "glm53.recipe.stamp" }}')"
echo "head stamp: $HEAD_STAMP"
for target in "spark@10.73.0.1" "spark4@10.73.0.4"; do
  echo "=== syncing to $target ==="
  remote_stamp="$(ssh -o ConnectTimeout=10 "$target" "docker image inspect $IMG --format '{{ index .Config.Labels \"glm53.recipe.stamp\" }}' 2>/dev/null || echo MISSING")"
  if [[ "$remote_stamp" == "$HEAD_STAMP" ]]; then
    echo "  already current ($remote_stamp) — skipping"
    continue
  fi
  echo "  remote has $remote_stamp — pushing head image over fabric"
  docker save "$IMG" | ssh -o ConnectTimeout=10 "$target" "docker load"
  new_stamp="$(ssh -o ConnectTimeout=10 "$target" "docker image inspect $IMG --format '{{ index .Config.Labels \"glm53.recipe.stamp\" }}' 2>/dev/null || echo MISSING")"
  if [[ "$new_stamp" == "$HEAD_STAMP" ]]; then
    echo "  OK: $target now $new_stamp"
  else
    echo "  FAIL: $target still $new_stamp" >&2
    exit 1
  fi
done
echo "=== all ranks current: $HEAD_STAMP ==="
