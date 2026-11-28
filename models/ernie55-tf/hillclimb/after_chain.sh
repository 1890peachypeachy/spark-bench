#!/usr/bin/env bash
# Start an idle-gated chain after the running one finishes: waits for a "chain done" line logged after the line that
# holds <anchor text> in logs/idle_chain.log. Does not start if that chain was aborted (STOP) or STOP is present.
# Usage: after_chain.sh "<anchor text>" exp1 exp2 ...   (IDLE_MIN / IDLE_NEXT / PROFILE_EXPS pass through)
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
ANCHOR=${1:?anchor}; shift
LOG=$HC/logs/idle_chain.log
start=$(grep -n -F "$ANCHOR" "$LOG" | tail -1 | cut -d: -f1)
[ -n "$start" ] || { echo "anchor not found in $LOG"; exit 2; }
echo "$(date -Is) after_chain: waiting for the chain at line $start to finish, then: $*"
while ! tail -n +"$start" "$LOG" | grep -q "chain done"; do sleep 60; done
if tail -n +"$start" "$LOG" | grep -q "aborted before"; then
  echo "$(date -Is) after_chain: that chain was aborted (STOP), not starting $*" | tee -a "$LOG"; exit 1
fi
[ -f $HC/STOP ] && { echo "$(date -Is) after_chain: STOP present, not starting $*" | tee -a "$LOG"; exit 1; }
exec bash $HC/idle_chain.sh "$@"
