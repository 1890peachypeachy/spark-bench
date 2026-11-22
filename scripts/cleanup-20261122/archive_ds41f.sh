#!/bin/bash
# Runs ON spark1 (via ssh 'bash -s'). Archive docker image spark-ds41f:1107 to the NAS, hash on both ends. Read-only on the image.
set -uo pipefail
IMG=spark-ds41f:1107
ID=$(docker image inspect $IMG --format '{{.Id}}')
DEST=/volume1/homes/hermes/spark-models/spark1/retired-20261122-spark-ds41f
NAS="ssh -i $HOME/.ssh/hermes_huanghouse_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes hermes@huang-nas"
echo "image id: $ID"
echo "size: $(docker image inspect $IMG --format '{{.Size}}')"
$NAS -n "mkdir -p $DEST" || { echo "mkdir failed"; exit 1; }
S=$(date +%s)
docker save $IMG | tee >(sha256sum | cut -d' ' -f1 > /tmp/ds41f.sha) | $NAS "cat > $DEST/spark-ds41f-1107.tar"
echo "pipe rc=${PIPESTATUS[0]}/${PIPESTATUS[2]}  elapsed=$(( $(date +%s)-S ))s"
sleep 3
LOCAL=$(cat /tmp/ds41f.sha)
NASZ=$($NAS "stat -c %s $DEST/spark-ds41f-1107.tar")
echo "local sha256: $LOCAL"
echo "nas size:     $NASZ"
NASH=$($NAS "sha256sum $DEST/spark-ds41f-1107.tar | cut -d' ' -f1")
echo "nas sha256:   $NASH"
if [ "$LOCAL" = "$NASH" ] && [ -n "$LOCAL" ]; then echo "VERIFIED: archive hash matches"; else echo "MISMATCH"; exit 2; fi
$NAS "cat > $DEST/README.txt" <<EOF
spark-ds41f:1107 docker image, archived 2026-11-22 by spark (Hermes) at Victor's request.
image id:  $ID
sha256 (tar): $LOCAL
load with: docker load -i spark-ds41f-1107.tar   (then docker tag if needed)
rebuild:   git clone https://github.com/christopherowen/spark-ds41f ; checkout release spark-ds41f-1107 ; build per its README
why: DeepSeek-V4.1-Flash-1017 experiment lane (Victor, 2026-11-07/08), crashed 2026-11-09 (exit 139), not a registered spark-lane lane. Removed from spark1-4 to free 23.9 GB per node.
EOF
echo "archive done"
