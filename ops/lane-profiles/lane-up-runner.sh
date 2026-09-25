#!/usr/bin/env bash
# lane-up-runner.sh — runs the documented bring-up chain for one lane, inside that
# lane's kit, streaming everything to stdout.
#
# spark-lane launches this DETACHED (setsid nohup + redirect to a log) because a
# cold 4-Spark bring-up is long: the image build fetches pinned sources on all four
# nodes, then the engine takes 160-170 s to become healthy. Nothing here is
# interactive, and nothing here is allowed to prompt.
#
# Being a script (not a quoted one-liner over ssh) is deliberate: the chained
# phases, the first-time-only share/pack gate and the exit codes stay readable and
# can be re-run by hand exactly as written.
#
# Usage: lane-up-runner.sh <lane> <kit_dir> [--force-pack]
set -uo pipefail

LANE="${1:-}"; KIT="${2:-}"; FORCE_PACK="${3:-}"
[[ -n "$LANE" && -n "$KIT" ]] || { echo "usage: lane-up-runner.sh <lane> <kit_dir>" >&2; exit 2; }
cd "$KIT" || { echo "no kit at $KIT" >&2; exit 3; }

case "$LANE" in
  dsv41-tp4) CLI="./start-tp4.sh"; MARK="state-tp4/.spark-lane-packed" ;;
  dsv41-tp3) CLI="./start.sh";     MARK="state/.spark-lane-packed" ;;
  *) echo "lane-up-runner: unknown lane $LANE" >&2; exit 2 ;;
esac
[[ -x "$CLI" || -f "$CLI" ]] || { echo "no $CLI in $KIT" >&2; exit 3; }

START=$(date +%s)
phase() { echo; echo "=== [$(date +%H:%M:%S) +$(( $(date +%s) - START ))s] $CLI $* ==="; }

run() {
  phase "$@"
  "$CLI" "$@"
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "!!! FAILED: $CLI $* (exit $rc) — stopping the chain here."
    echo "!!! Re-run by hand:  cd $KIT && $CLI $*"
    exit $rc
  fi
  echo "=== ok: $CLI $* ==="
}

# 1. preflight — the kit's own gate, always worth re-running
run doctor

# 2. image — docker build per node; cached layers make a repeat cheap, and the
#    TP4 image fetches its pinned third-party sources during this phase
run build

# 3. weights share + Engram pack — genuinely first-time-only (the docs say so),
#    gated on a marker so a re-up does not rebuild the Engram shards
if [[ "$FORCE_PACK" == "--force-pack" || ! -f "$MARK" ]]; then
  run share
  run pack
  mkdir -p "$(dirname "$MARK")" && touch "$MARK"
  echo "=== first-time share+pack recorded: $MARK ==="
else
  echo "=== share+pack already done ($MARK) — skipping ==="
fi

# 4. serve — the launcher keeps the engine running in containers; this process may
#    tail logs and stay alive, which is fine under setsid
run serve

echo
echo "=== lane-up-runner: chain complete for $LANE after $(( $(date +%s) - START ))s ==="