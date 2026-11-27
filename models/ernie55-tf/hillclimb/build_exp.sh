#!/usr/bin/env bash
# Build an experiment binary on spark3 from the production tree's commit + a diff, in its own worktree, then stage it
# on all 4 Sparks at /var/tmp/ernie55/exp/<name>/bin/tensorfold-native (the production bin is never touched).
# Usage: build_exp.sh <name> <diff file> [optimize=ReleaseSafe]
set -euo pipefail
NAME=${1:?name}; DIFF=${2:?diff}; OPT=${3:-ReleaseSafe}
ZIG=/var/tmp/tf1017/zig-aarch64-linux-0.17.0/zig
export PATH=/usr/local/cuda/bin:$PATH
PROD=/var/tmp/ernie55/tensorfold-ernie
WT=/var/tmp/ernie55/wt/$NAME
BASE=$(git -C $PROD rev-parse HEAD)
if [ ! -d "$WT" ]; then git -C $PROD worktree add -q --detach "$WT" "$BASE"; fi
cd "$WT"
git checkout -q --detach "$BASE" && git reset -q --hard "$BASE"
git apply --check "$DIFF" && git apply "$DIFF"
git -c user.name="Spark Agent" -c user.email="spark-agent@localhost" commit -qam "exp $NAME" || true
echo "== $(date -Is) building $NAME ($OPT) at $(git rev-parse --short HEAD) on $BASE"
t0=$(date +%s)
nice -n 15 $ZIG build native -Dfatbins=/var/tmp/ernie55/fatbins -Doptimize=$OPT --cache-dir $PROD/.zig-cache 2>&1 | tail -20
echo "build took $(( $(date +%s) - t0 ))s"
OUT=/var/tmp/ernie55/exp/$NAME/bin
mkdir -p $OUT
cp zig-out/native/bin/tensorfold-native $OUT/tensorfold-native
md=$(md5sum $OUT/tensorfold-native | cut -c1-12)
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  ssh -o BatchMode=yes $h "mkdir -p $OUT" && scp -q $OUT/tensorfold-native $h:$OUT/tensorfold-native &
done
wait
for h in spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4; do
  m=$(ssh $h "md5sum $OUT/tensorfold-native | cut -c1-12"); echo "$h $m"; [ "$m" = "$md" ] || { echo "MD5 MISMATCH on $h"; exit 1; }
done
echo "STAGED $NAME md5=$md at $OUT"
