#!/usr/bin/env bash
# rotate-all.sh — autonomous full-rotation test for the DGX Spark fleet.
#
# Rotates through EVERY lane in sequence, verifying each with a real chat canary,
# and reports a per-lane PASS/FAIL summary. Designed to be invoked by ANY model or
# user with zero judgement: it parks whatever is running, brings up the target lane,
# waits for it, verifies it, and moves on. Ends with a one-line summary.
#
# Usage:
#   rotate-all.sh [--end <lane>] [--skip <lane>] [--only <lane>]
#
#   --end <lane>   leave the fleet on this lane when done (default: dsv41-tp4)
#   --skip <lane>  skip a lane in the rotation (repeatable)
#   --only <lane>  rotate through ONLY this lane, then leave it up
#
# Exit code: 0 if every lane passed, 1 if any lane failed.
#
# NOTE: this is a LONG run. Each LLM boot is ~15-25 min. The full matrix
# (creative-engine, dsv41-tp3, dsv41-tp4, glm53-tp3) can take 1.5-2 hours.
# Run it detached:  setsid nohup bash rotate-all.sh > /tmp/rotate-all.log 2>&1 &
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SPARK_LANE="${SPARK_LANE:-$HERE/spark-lane}"
END_LANE="${END_LANE:-dsv41-tp4}"
SKIP_LANES=""
ONLY_LANE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --end) END_LANE="$2"; shift 2 ;;
    --skip) SKIP_LANES="$SKIP_LANES $2"; shift 2 ;;
    --only) ONLY_LANE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ALL_LANES="creative-engine dsv41-tp3 dsv41-tp4 glm53-tp3"
if [[ -n "$ONLY_LANE" ]]; then
  ALL_LANES="$ONLY_LANE"
fi

START=$(date +%s)
PASSED=""
FAILED=""
declare -A RESULTS

log() { echo "[$(date +%H:%M:%S) +$(( $(date +%s) - START ))s] $*"; }

run_lane() {
  local lane="$1"
  log "===== ROTATE -> $lane ====="
  if ! "$SPARK_LANE" rotate "$lane"; then
    log "!!! rotate $lane FAILED"
    RESULTS["$lane"]="FAIL(rotate)"
    FAILED="$FAILED $lane"
    return 1
  fi
  log "----- verify $lane -----"
  if "$SPARK_LANE" verify "$lane"; then
    log "===== $lane PASS ====="
    RESULTS["$lane"]="PASS"
    PASSED="$PASSED $lane"
    return 0
  else
    log "!!! verify $lane FAILED"
    RESULTS["$lane"]="FAIL(verify)"
    FAILED="$FAILED $lane"
    return 1
  fi
}

log "=== rotate-all: full rotation test starting ==="
log "lanes: $ALL_LANES"
log "end lane: $END_LANE"

for lane in $ALL_LANES; do
  if [[ " $SKIP_LANES " == *" $lane "* ]]; then
    log "skipping $lane (--skip)"
    continue
  fi
  run_lane "$lane"
done

# Leave the fleet on the requested end lane (if not already there and not skipped).
if [[ -n "$ONLY_LANE" ]]; then
  log "=== --only mode: leaving fleet on $ONLY_LANE ==="
elif [[ " $SKIP_LANES " != *" $END_LANE "* ]]; then
  log "=== leaving fleet on $END_LANE ==="
  if [[ " $ALL_LANES " != *" $END_LANE "* ]]; then
    # end lane wasn't in the rotation set — bring it up directly
    if ! "$SPARK_LANE" rotate "$END_LANE"; then
      log "!!! could not bring up end lane $END_LANE"
      FAILED="$FAILED $END_LANE"
    fi
  fi
fi

echo
echo "================ ROTATION TEST SUMMARY ================"
for lane in $ALL_LANES; do
  printf '  %-16s %s\n' "$lane" "${RESULTS[$lane]:-SKIPPED}"
done
echo "========================================================"
echo "PASSED:$PASSED"
echo "FAILED:${FAILED:-none}"
echo "elapsed: $(( $(date +%s) - START ))s"
if [[ -n "$FAILED" ]]; then
  echo "RESULT: FAIL"
  exit 1
else
  echo "RESULT: PASS"
  exit 0
fi
