#!/usr/bin/env bash
# Idle-window experiment chain for the shared :8888 lane (Victor's live agents use it).
#  - waits until the lane has served NO request for IDLE_MIN minutes (request counter frozen, nothing running);
#  - runs one experiment; if foreign requests arrive during it (counter delta beyond the bench's own), marks it
#    CONTAMINATED and waits for the next idle window before re-running it (max 2 tries);
#  - when the list is done (or on abort), restores the recipe's production launcher, again only when idle.
# Usage: idle_chain.sh exp1 exp2 ...     env: IDLE_MIN (default 15)  PROFILE_EXPS (names run with prof_run.sh)
set -uo pipefail
HC=/var/tmp/ernie55/hillclimb/tf
LOG=$HC/logs/idle_chain.log
IDLE_MIN=${IDLE_MIN:-15}
metric() { curl -s --max-time 3 http://127.0.0.1:8888/metrics | awk -v k="$1" '$1==k{print $2}'; }
count() { local c; c=$(metric tensorfold:request_latency_seconds_count); echo "${c%.*}"; }
say() { echo "$(date -Is) $*" | tee -a $LOG; }

wait_idle() { # $1 minutes of no traffic
  local need=$(( $1 * 60 )) quiet=0 last=""
  while true; do
    local c r; c=$(count); r=$(metric tensorfold:requests_running); r=${r%.*}
    if [ -z "$c" ]; then quiet=$((quiet + 30)); # server down: counts as idle
    elif [ "$c" = "$last" ] && [ "${r:-0}" = 0 ]; then quiet=$((quiet + 30)); else quiet=0; fi
    last=$c
    [ $quiet -ge $need ] && return 0
    [ -f $HC/STOP ] && { say "STOP file present"; return 1; }
    sleep 30
  done
}

run_one() { # name -> 0 clean, 2 contaminated, 1 failed
  local name=$1 c0 c1 exp_n
  c0=$(count)
  if [[ " ${PROFILE_EXPS:-} " == *" $name "* ]]; then
    bash $HC/prof_run.sh "$name" > $HC/logs/$name.tmux.log 2>&1 || return 1
    exp_n=8      # warm 1 + dec1 2 + dec4 4 + pre16k 1
  else
    SKIP_LONG=${SKIP_LONG:-1} bash $HC/run_exp.sh "$name" > $HC/logs/$name.tmux.log 2>&1 || return 1
    exp_n=71     # measured: a clean SKIP_LONG run (e1a) finishes exactly 71 requests
  fi
  c1=$(count)
  r1=$(metric tensorfold:requests_running); r1=${r1%.*}
  # the launch restarts the server (counter resets to 0), so the post-run count IS the run's own request count
  if [ -n "$c1" ] && { [ "$c1" -gt "$exp_n" ] || [ "${r1:-0}" != 0 ]; }; then say "$name CONTAMINATED: $c1 requests (expected $exp_n), $r1 running"; return 2; fi
  say "$name clean: $c1 requests"; return 0
}

say "chain start: $* (idle window ${IDLE_MIN} min)"
for name in "$@"; do
  for try in 1 2; do
    wait_idle "$IDLE_MIN" || { say "aborted before $name"; break 2; }
    say "running $name (try $try)"
    run_one "$name"; rc=$?
    [ $rc = 0 ] && break
    [ $rc = 1 ] && { say "$name FAILED"; break; }
    mv $HC/results/$name $HC/results/$name.contaminated.$try 2>/dev/null || true
  done
done
wait_idle 1 || true
say "restoring production (recipe launcher)"
bash /var/tmp/ernie55/start_tensorfold.sh >> $LOG 2>&1
/usr/local/bin/nsys shutdown --session=tfprof >/dev/null 2>&1 || true
say "chain done; production restored"
