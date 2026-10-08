#!/usr/bin/env bash
# Stage JSpark3 v2.0.2 alongside the LIVE v2.0.1 ring. I/O-only: does NOT stop,
# start, build, or split anything. Safe to run while v2.0.1 serves.
# Deferred to the cutover window (memory-churning, per INSTALL.md step 3/5 warning):
#   scripts/build-wheel.sh ; scripts/fetch-wheels.sh --verify-only ; scripts/split.sh --verify-only
set -euo pipefail

ROOT=/var/tmp/jspark3
LIVE_KIT=$ROOT/jspark3
LIVE_DATA=$ROOT/data
NEW_KIT=$ROOT/jspark3-v202
NEW_DATA=$ROOT/data-v202
TAG=v2.0.2

RANK=$(grep -E '^RANK=' "$LIVE_KIT/cluster.env" | cut -d= -f2 | tr -d '"')
echo "[$(hostname)] rank=$RANK"

# --- 1. checkout -----------------------------------------------------------
if [ -d "$NEW_KIT/.git" ]; then
  git -C "$NEW_KIT" fetch --tags --quiet origin
  git -C "$NEW_KIT" checkout --quiet "$TAG"
else
  [ -e "$NEW_KIT" ] && mv "$NEW_KIT" "$ROOT/backups-$(date +%s)-jspark3-v202" || true
  git clone --quiet --branch "$TAG" https://github.com/jakejharris/jspark3.git "$NEW_KIT"
fi
echo "kit: $(git -C "$NEW_KIT" describe --tags) $(git -C "$NEW_KIT" rev-parse --short HEAD)"
grep -E '^RELEASE=|^WHEEL_CONTENT_SHA256=' "$NEW_KIT/pins.env"

# --- 2. cluster.env: live wiring, new DATA --------------------------------
sed "s#^DATA=.*#DATA=$NEW_DATA#" "$LIVE_KIT/cluster.env" > "$NEW_KIT/cluster.env"
echo "--- cluster.env ---"; grep -vE '^#|^$' "$NEW_KIT/cluster.env"

# --- 3. fleet deviation: served model id pin ------------------------------
sed -i "s#^SERVE_NAME=.*#SERVE_NAME=GLM-5.3-Flash-EXL3#" "$NEW_KIT/config/serve.conf"
grep -E '^SERVE_NAME=|^SERVE_SESSION_NAMESPACE=' "$NEW_KIT/config/serve.conf"

# --- 3b. fleet deviation: shared KV pool ----------------------------------
# Upstream ships TF_GLM_POOL_TOKENS=360448 (1.375x context), just above the
# engine's legal floor. Our agents are capped at 256K context, so that pool
# holds only ONE max-size conversation and ~2 at observed (~156K) sizes, which
# caps usable concurrency at ~2 regardless of --parallel 8.
# Raised to 786432 (3x context) on 2026-10-07: ~5 concurrent 156K / ~3 at 256K.
# Verified granted in full ("786,432 usable tokens (requested 786,432)") and
# proven functionally: two concurrent 195K contexts (390,875 combined) stayed
# resident together, which the old pool could not hold.
# Legal range is --context .. parallel*--context (262,144 .. 2,097,152); the
# calibrated memory ceiling is ~1,287,442. Do NOT go to the max: it leaves zero
# spare against an ESTIMATE and an NVRM OOM wedges a GB10 node.
# MUST be identical on every rank - the engine hard-errors on a mismatch.
sed -i "s#^TF_GLM_POOL_TOKENS=.*#TF_GLM_POOL_TOKENS=786432#" "$NEW_KIT/config/serve.env"
grep -E '^TF_GLM_POOL_TOKENS=' "$NEW_KIT/config/serve.env"

# --- 3c. fleet deviation: disk session store size -------------------------
# Upstream ships 64 GiB. Real session files on this lane reach 3.0 GB each, so
# 64 GiB held only ~26 conversations -> the store ran permanently at its cap and
# evicted states it then needed again (265 store-evicted / observed-prior-prompt
# misses in one boot on 2026-10-07). Each such miss re-prefills the whole prompt:
# measured 232-476s for ~100-195K tokens, vs 21s for a resumed hit.
# Raised to 192 GiB (~78 conversations) on 2026-10-07.
# Sized by the TIGHTEST node, not the roomiest: the tier is per box, and serve.sh
# stops writing below 150 GiB free (warns when free < 150 + SERVE_SESSION_GIB).
# spark4 had 434 GiB free vs ~1250 on spark1/spark3, so 192 is the safe ceiling
# (needs 342, leaves 92 GiB margin). 384 would have exceeded spark4's budget.
# Costs NO GPU memory - unlike TF_GLM_CACHE_GIB, which competes with the pool.
# Both knobs must move together: serve.env drives the engine, serve.conf drives
# the free-space guard and the operator-facing message.
sed -i "s#^TF_GLM_DISK_GIB=.*#TF_GLM_DISK_GIB=192#" "$NEW_KIT/config/serve.env"
sed -i "s#^SERVE_SESSION_GIB=.*#SERVE_SESSION_GIB=192#" "$NEW_KIT/config/serve.conf"
grep -E '^TF_GLM_DISK_GIB=' "$NEW_KIT/config/serve.env"
grep -E '^SERVE_SESSION_GIB=' "$NEW_KIT/config/serve.conf"

# --- 4. DATA: reuse verified weights by symlink, fresh sessions ------------
# wheels.lock + manifests/{inputs,base} are byte-identical v2.0.1..v2.0.2,
# so the verified weights and dep wheels are valid for this release.
mkdir -p "$NEW_DATA" "$NEW_DATA/base" "$NEW_DATA/sessions" "$NEW_DATA/kernel-cache"
ln -sfn "$LIVE_DATA/base/rank$RANK" "$NEW_DATA/base/rank$RANK"
ln -sfn "$LIVE_DATA/drafter"        "$NEW_DATA/drafter"
cp -f "$LIVE_DATA/base/rank$RANK.verified" "$NEW_DATA/base/" 2>/dev/null || echo "WARN: no base rank marker"
cp -f "$LIVE_DATA/drafter.verified"        "$NEW_DATA/"      2>/dev/null || echo "WARN: no drafter marker"

# --- 5. dependency wheels (lock unchanged) --------------------------------
mkdir -p "$NEW_KIT/wheels"
find "$LIVE_KIT/wheels" -maxdepth 1 -name '*.whl' ! -name 'tensorfold-*' \
  -exec cp -n {} "$NEW_KIT/wheels/" \;

# --- 6. report -------------------------------------------------------------
echo "--- staged state ---"
echo "deps wheels:   $(ls "$NEW_KIT"/wheels/*.whl 2>/dev/null | grep -vc tensorfold || true)"
echo "engine wheel:  $(ls "$NEW_KIT"/wheels/tensorfold-*.whl 2>/dev/null | wc -l) (0 = build deferred to cutover)"
echo "weights:       $(readlink "$NEW_DATA/base/rank$RANK") -> $(find -L "$NEW_DATA/base/rank$RANK" -type f 2>/dev/null | wc -l) files"
echo "drafter:       $(find -L "$NEW_DATA/drafter" -type f 2>/dev/null | wc -l) files"
echo "sessions:      $(ls -A "$NEW_DATA/sessions" | wc -l) entries (0 = cold, required)"
echo "live ring:     $(docker ps --format '{{.Names}}' | grep -c '^jspark3-rank') container(s) untouched"
echo "STAGED_OK $(hostname) rank$RANK"
